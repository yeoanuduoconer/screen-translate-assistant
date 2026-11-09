from __future__ import annotations

import atexit
import multiprocessing as mp
import os
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from importlib.util import find_spec
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops

from .models import Rect, TextRegion
from .paths import cache_root
from .tracking import FrameMotionTracker

os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(cache_root() / "paddlex"))
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("PADDLE_PDX_CPU_NUM_THREADS", "4")
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")


@dataclass(frozen=True, slots=True)
class OcrSnapshot:
    image: Image.Image
    regions: tuple[TextRegion, ...]
    mode: str = "全图"


def _scrolled_regions(
    image: Image.Image, previous: OcrSnapshot
) -> tuple[tuple[int, int, int, int] | None, list[TextRegion]] | None:
    width, height = image.size
    # Estimate scroll using the body; stationary headers and toolbars can
    # otherwise dominate phase correlation and make the estimate zero.
    inset = height // 8
    body = (0, inset, width, height - inset)
    tracker = FrameMotionTracker()
    tracker.observe(previous.image.crop(body))
    motion = tracker.observe(image.crop(body))
    estimate = round(motion.dy)
    if abs(motion.dx) > 2 or abs(estimate) < 4:
        return None

    old_rows = np.frombuffer(previous.image.tobytes(), dtype=np.uint8).reshape(height, -1)
    new_rows = np.frombuffer(image.tobytes(), dtype=np.uint8).reshape(height, -1)
    stationary = np.all(old_rows == new_rows, axis=1)
    best: tuple[int, int, int] | None = None
    best_moved_rows = 0
    for dy in (estimate, estimate - 1, estimate + 1):
        old_top, new_top = max(0, -dy), max(0, dy)
        overlap = height - abs(dy)
        matching = np.all(
            old_rows[old_top : old_top + overlap] == new_rows[new_top : new_top + overlap],
            axis=1,
        )
        edges = np.flatnonzero(np.diff(np.r_[False, matching, False]))
        for first, last in zip(edges[::2], edges[1::2], strict=True):
            top, bottom = new_top + int(first), new_top + int(last)
            if bottom - top < height * 0.25:
                continue
            moved_rows = int(np.count_nonzero(~stationary[top:bottom]))
            if moved_rows > best_moved_rows:
                best = top, bottom, dy
                best_moved_rows = moved_rows
    if best is None or best_moved_rows < 8:
        return None

    top, bottom, dy = best
    expected = previous.image.copy()
    expected.paste(previous.image.crop((0, top - dy, width, bottom - dy)), (0, top))
    dirty = ImageChops.difference(expected, image).getbbox(alpha_only=False)
    reusable: list[TextRegion] = []
    for region in previous.regions:
        box = region.box
        if box.bottom <= top or box.y >= bottom:
            reusable.append(region)
        shifted = box.offset(0, dy)
        if shifted.y >= top and shifted.bottom <= bottom:
            reusable.append(replace(region, box=shifted))
        # Re-read a boundary if a word was cut across it. Otherwise rows
        # known to be identical could still leave a half-line unrecognized.
        for seam in (top, bottom):
            if 0 < seam < height and (
                box.y < seam < box.bottom or shifted.y < seam < shifted.bottom
            ):
                left = max(0, box.x)
                right = min(width, box.right)
                if dirty is None:
                    dirty = (left, seam - 1, right, seam + 1)
                else:
                    x1, y1, x2, y2 = dirty
                    dirty = (min(x1, left), min(y1, seam - 1), max(x2, right), max(y2, seam + 1))
    return dirty, reusable


def recognize_changed(
    image: Image.Image,
    recognize: Callable[[Image.Image], list[TextRegion]],
    previous: OcrSnapshot | None,
) -> OcrSnapshot:
    if previous is None or previous.image.size != image.size or previous.image.mode != image.mode:
        return OcrSnapshot(image, tuple(recognize(image)))

    changed = ImageChops.difference(previous.image, image).getbbox(alpha_only=False)
    if changed is None:
        return OcrSnapshot(image, previous.regions, "复用")

    left, top, right, bottom = changed
    remaining = list(previous.regions)
    mode = "局部"
    if (right - left) * (bottom - top) >= image.width * image.height * 0.55:
        scrolled = _scrolled_regions(image, previous)
        if scrolled is None:
            return OcrSnapshot(image, tuple(recognize(image)))
        dirty, remaining = scrolled
        if dirty is None:
            remaining.sort(key=lambda region: (region.box.y, region.box.x))
            return OcrSnapshot(image, tuple(remaining), "滚动复用")
        left, top, right, bottom = dirty
        mode = "滚动增量"

    padding = 48  # Give the detector context beyond the changed glyphs.
    left, top = max(0, left - padding), max(0, top - padding)
    right, bottom = min(image.width, right + padding), min(image.height, bottom + padding)
    while True:
        # Keep the entire previous line in the crop if any part intersects it.
        # This also removes old text whose line shrank or disappeared.
        untouched = []
        for region in remaining:
            box = region.box
            if box.right <= left or box.x >= right or box.bottom <= top or box.y >= bottom:
                untouched.append(region)
                continue
            left, top = max(0, min(left, box.x)), max(0, min(top, box.y))
            right = min(image.width, max(right, box.right))
            bottom = min(image.height, max(bottom, box.bottom))
        if len(untouched) == len(remaining):
            break
        remaining = untouched

    if (right - left) * (bottom - top) >= image.width * image.height * 0.55:
        return OcrSnapshot(image, tuple(recognize(image)))

    for region in recognize(image.crop((left, top, right, bottom))):
        remaining.append(replace(region, box=region.box.offset(left, top)))
    remaining.sort(key=lambda region: (region.box.y, region.box.x))
    return OcrSnapshot(image, tuple(remaining), mode)


class _LocalPaddleOcrEngine:
    def __init__(self) -> None:
        self.backend = "Paddle"
        root = Path(os.environ["PADDLE_PDX_CACHE_HOME"]) / "onnx_models"
        detector = root / "PP-OCRv6_small_det"
        recognizer = root / "PP-OCRv6_small_rec"
        if (
            os.environ.get("SCREEN_TRANSLATOR_FORCE_PADDLE") != "1"
            and all(
                (folder / name).is_file()
                for folder in (detector, recognizer)
                for name in ("inference.onnx", "inference.yml")
            )
            and find_spec("onnxruntime") is not None
        ):
            try:
                self._engine = self._make_pipeline(
                    engine="onnxruntime",
                    engine_config={"intra_op_num_threads": 4, "inter_op_num_threads": 1},
                    text_detection_model_dir=str(detector),
                    text_recognition_model_dir=str(recognizer),
                )
                self.backend = "ONNX Runtime"
                return
            except Exception:
                self.backend = "Paddle fallback"
        self._engine = self._make_pipeline()

    @staticmethod
    def _make_pipeline(**options):
        from paddleocr import PaddleOCR

        return PaddleOCR(
            text_detection_model_name="PP-OCRv6_small_det",
            text_recognition_model_name="PP-OCRv6_small_rec",
            device="cpu",
            cpu_threads=4,
            enable_mkldnn=False,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            text_det_thresh=0.16,
            text_det_box_thresh=0.32,
            text_det_unclip_ratio=1.45,
            text_rec_score_thresh=0.22,
            **options,
        )

    def recognize(self, image: Image.Image) -> list[TextRegion]:
        source = image.convert("RGB")
        scale = min(1.0, 1920.0 / max(source.width, source.height))
        working = source
        if scale < 1.0:
            working = source.resize(
                (max(1, round(source.width * scale)), max(1, round(source.height * scale))),
                Image.Resampling.LANCZOS,
            )

        pixels = np.asarray(working)
        try:
            predictions = list(self._engine.predict(pixels))
        except Exception:
            if self.backend != "ONNX Runtime":
                raise
            self.backend = "Paddle fallback"
            self._engine = self._make_pipeline()
            predictions = list(self._engine.predict(pixels))
        if not predictions:
            return []
        result = predictions[0].json["res"]
        texts = result.get("rec_texts", [])
        scores = result.get("rec_scores", [])
        polygons = result.get("rec_polys", [])
        regions: list[TextRegion] = []
        for text, score, polygon in zip(texts, scores, polygons, strict=False):
            normalized = str(text).strip()
            confidence = float(score)
            if not normalized or confidence < 0.22:
                continue
            points = np.asarray(polygon, dtype=np.float32) / scale
            left = int(round(float(points[:, 0].min())))
            top = int(round(float(points[:, 1].min())))
            right = int(round(float(points[:, 0].max())))
            bottom = int(round(float(points[:, 1].max())))
            regions.append(
                TextRegion(
                    Rect(left, top, max(1, right - left), max(1, bottom - top)),
                    normalized,
                    confidence,
                )
            )
        return regions


def _worker_main(requests, responses, cache_home: str) -> None:
    os.environ["PADDLE_PDX_CACHE_HOME"] = cache_home
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ["PADDLE_PDX_CPU_NUM_THREADS"] = "4"
    os.environ["OMP_NUM_THREADS"] = "2"
    os.environ["MKL_NUM_THREADS"] = "2"
    engine: _LocalPaddleOcrEngine | None = None
    initialization_error = ""
    try:
        # Load weights as soon as the desktop app opens. Usually this finishes
        # before the user has selected a region, removing model load time from
        # the first visible translation.
        engine = _LocalPaddleOcrEngine()
    except Exception as exc:
        initialization_error = f"OCR 初始化失败：{exc}"

    while True:
        request = requests.get()
        if request is None:
            return
        request_id, image = request
        try:
            if engine is None:
                raise RuntimeError(initialization_error or "OCR 引擎未初始化。")
            regions = engine.recognize(image)
            responses.put((request_id, regions, "", engine.backend))
        except Exception as exc:
            responses.put((request_id, [], f"OCR 子进程失败：{exc}", "unavailable"))


class PaddleOcrEngine:
    def __init__(self) -> None:
        self.backend = "initializing"
        self._context = mp.get_context("spawn")
        self._requests = self._context.Queue(maxsize=1)
        self._responses = self._context.Queue(maxsize=1)
        self._process = self._context.Process(
            target=_worker_main,
            args=(self._requests, self._responses, os.environ["PADDLE_PDX_CACHE_HOME"]),
            name="screen-translator-ocr",
            daemon=True,
        )
        self._process.start()
        self._lock = threading.Lock()
        self._next_request_id = 1
        self._closed = False
        atexit.register(self.close)

    def recognize(self, image: Image.Image) -> list[TextRegion]:
        with self._lock:
            if self._closed or not self._process.is_alive():
                raise RuntimeError("OCR 子进程未运行。")
            request_id = self._next_request_id
            self._next_request_id += 1
            self._requests.put((request_id, image), timeout=2.0)
            try:
                response_id, regions, error, backend = self._responses.get(timeout=90.0)
            except queue.Empty as exc:
                raise RuntimeError("OCR 子进程响应超时。") from exc
            if response_id != request_id:
                raise RuntimeError("OCR 子进程返回了错误的请求编号。")
            self.backend = backend
            if error:
                raise RuntimeError(error)
            return regions

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._requests.put_nowait(None)
        except (queue.Full, ValueError):
            pass
        if self._process.is_alive():
            self._process.join(timeout=2.0)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=1.0)
