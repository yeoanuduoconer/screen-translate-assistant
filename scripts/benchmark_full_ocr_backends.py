import os
from pathlib import Path
from statistics import median
from time import perf_counter

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ONNX_MODELS = ROOT / ".cache" / "paddlex" / "onnx_models"
os.environ["PADDLE_PDX_CACHE_HOME"] = str(ROOT / ".cache" / "paddlex")
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["OMP_NUM_THREADS"] = "2"
os.environ["MKL_NUM_THREADS"] = "2"

import numpy as np  # noqa: E402
from paddleocr import PaddleOCR  # noqa: E402


def fixture(size, fontsize):
    page = Image.new("RGB", size, "#fdfdfd")
    draw = ImageDraw.Draw(page)
    font_dir = Path(os.environ["WINDIR"]) / "Fonts"
    font = ImageFont.truetype(str(font_dir / "NotoSansJP-VF.ttf"), fontsize)
    decorative = ImageFont.truetype(str(font_dir / "segoepr.ttf"), fontsize + 4)
    lines = [
        "Recent activity and settings",
        "Adjust the layout and font size for this page.",
        "システムの設定を変更してください。",
        "A new revision is available for review.",
        "通知を表示するタイミングを指定します。",
        "Read the full report before continuing.",
        "Decorative lettering with a period.",
        "更新されたページを確認してください。",
        "Only the highlighted section is required.",
        "画面の表示を自動的に更新します。",
        "Open the browser menu to view more tools.",
        "Select the original file and save a copy.",
        "翻訳の結果をここに表示します。",
        "Return to the previous screen.",
        "Status: 15 lines and a fixed toolbar.",
    ]
    spacing = (size[1] - 75) // len(lines)
    for i, line in enumerate(lines):
        draw.text(
            (42 + 9 * (i % 3), 28 + i * spacing),
            line,
            font=decorative if i == 6 else font,
            fill="#263348",
        )
    return np.asarray(page)


def bench(backend, images):
    options = {}
    if backend == "onnxruntime":
        options = {
            "engine": backend,
            "engine_config": {"intra_op_num_threads": 4, "inter_op_num_threads": 1},
            "text_detection_model_dir": str(ONNX_MODELS / "PP-OCRv6_small_det"),
            "text_recognition_model_dir": str(ONNX_MODELS / "PP-OCRv6_small_rec"),
        }
    engine = PaddleOCR(
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
    engine.predict(images[0])
    results = []
    for page in images:
        times = []
        for _ in range(3):
            start = perf_counter()
            result = engine.predict(page)[0].json["res"]
            times.append(perf_counter() - start)
        texts = tuple(result["rec_texts"])
        boxes = tuple(
            (min(x for x, y in p), min(y for x, y in p), max(x for x, y in p), max(y for x, y in p))
            for p in result["rec_polys"]
        )
        print(
            backend, page.shape, "median", round(median(times), 3), "lines", len(texts), flush=True
        )
        results.append((texts, boxes))
    engine.close()
    return results


if __name__ == "__main__":
    pages = [fixture((1600, 900), 31), fixture((1920, 1080), 39)]
    base = bench("paddle", pages)
    alternate = bench("onnxruntime", pages)
    for (texts, boxes), (new_texts, new_boxes) in zip(base, alternate, strict=True):
        print("identical_texts", texts == new_texts, "identical_boxes", boxes == new_boxes)
        if texts != new_texts:
            print(
                "text_differences",
                ascii(set(texts) - set(new_texts)),
                ascii(set(new_texts) - set(texts)),
            )
