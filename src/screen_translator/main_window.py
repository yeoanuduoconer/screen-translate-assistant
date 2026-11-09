from __future__ import annotations

import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime
from time import perf_counter

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .capture import (
    ScreenCapturer,
    StableChangeGate,
    frame_changed,
    frame_difference,
    frame_signature,
)
from .coordinates import map_regions_to_logical_screen
from .hotkeys import GlobalHotkeys
from .language import filter_regions, same_language, translation_changes_text
from .models import PipelineResult, Rect, TextRegion
from .ocr import OcrSnapshot, PaddleOcrEngine, recognize_changed
from .overlays import SelectionOverlay, TranslationOverlay
from .paths import cache_root
from .region_tracking import RegionTemplateTracker
from .settings import SettingsStore, protect_secret, unprotect_secret
from .styling import apply_region_styles
from .translation import DeepLTranslator, TranslationError

_TRANSLATION_SLOTS = 2
_PERFORMANCE_LOG = cache_root() / "performance.jsonl"


def _record_performance(event: str, **metrics: object) -> None:
    try:
        _PERFORMANCE_LOG.parent.mkdir(parents=True, exist_ok=True)
        if _PERFORMANCE_LOG.exists() and _PERFORMANCE_LOG.stat().st_size > 64 * 1024:
            _PERFORMANCE_LOG.replace(_PERFORMANCE_LOG.with_suffix(".previous.jsonl"))
        with _PERFORMANCE_LOG.open("a", encoding="utf-8") as log:
            record = {
                "at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "event": event,
                **metrics,
            }
            log.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass


@dataclass(frozen=True, slots=True)
class _CaptureResult:
    session_id: int
    region: Rect
    image: Image.Image | None = None
    signature: np.ndarray | None = None
    should_analyze: bool = False
    tracked_regions: tuple[TextRegion, ...] | None = None
    tracking_lost: bool = False
    tracker_version: int = 0
    error: str = ""
    change_seen_at: float = 0.0
    stable_at: float = 0.0


@dataclass(frozen=True, slots=True)
class _AnalysisResult:
    session_id: int
    region: Rect
    snapshot: OcrSnapshot
    signature: np.ndarray
    pipeline: PipelineResult
    change_seen_at: float
    stable_at: float
    ocr_seconds: float


@dataclass(frozen=True, slots=True)
class _TranslationResult:
    analysis: _AnalysisResult
    pipeline: PipelineResult
    translation_seconds: float = 0.0


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("屏幕翻译助手")
        self.setMinimumWidth(660)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        self._store = SettingsStore()
        self._settings = self._store.load()
        self._capturer = ScreenCapturer()
        self._gate = StableChangeGate(
            self._settings.change_threshold, self._settings.stable_frames, quiet_seconds=0.18
        )
        self._region_tracker = RegionTemplateTracker()
        self._tracker_version = 0
        self._tracking_lock = threading.Lock()
        self._ocr = PaddleOcrEngine()
        self._translator = DeepLTranslator()
        self._capture_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="capture-track"
        )
        self._analysis_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ocr")
        self._translation_executor = ThreadPoolExecutor(
            max_workers=_TRANSLATION_SLOTS, thread_name_prefix="translate"
        )
        self._capture_future: Future[_CaptureResult] | None = None
        self._analysis_future: Future[_AnalysisResult] | None = None
        self._translation_jobs: dict[Future[_TranslationResult], _AnalysisResult] = {}
        self._pending_capture: _CaptureResult | None = None
        self._pending_translation: _AnalysisResult | None = None
        self._ocr_snapshot: OcrSnapshot | None = None
        self._latest_image: Image.Image | None = None
        self._latest_signature: np.ndarray | None = None
        self._session_id = 0
        self._region: Rect | None = None
        self._selection: SelectionOverlay | None = None
        self._paused = False
        self._original_visible = False

        screen = QApplication.primaryScreen()
        if screen is None:
            raise RuntimeError("No screen is available.")
        self._virtual_geometry = screen.virtualGeometry()
        self._overlay = TranslationOverlay(self._virtual_geometry)

        self._capture_timer = QTimer(self)
        self._capture_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._capture_timer.setInterval(34)
        self._capture_timer.timeout.connect(self._schedule_capture)
        self._poll_timer = QTimer(self)
        self._poll_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._poll_timer.setInterval(10)
        self._poll_timer.timeout.connect(self._poll_results)
        self._poll_timer.start()

        self._hotkeys = GlobalHotkeys()
        self._hotkeys.triggered.connect(self._handle_hotkey)
        self._hotkeys.registration_error.connect(self._show_hotkey_error)
        self._build_ui()
        self._load_secret_into_ui()
        self._hotkeys.start()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        title = QLabel("屏幕文字识别与翻译助手")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(title)
        explanation = QLabel("框选区域后自动监测；局部文字变化时优先识别变化区域。")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        form = QFormLayout()
        self._provider = QComboBox()
        self._provider.addItem("DeepL")
        self._provider.setCurrentText(self._settings.provider)
        form.addRow("翻译服务", self._provider)

        language_row = QHBoxLayout()
        self._source_language = QComboBox()
        self._source_language.addItem("自动：英语/日语，跳过纯中文", "AUTO")
        self._source_language.addItem("英语", "EN")
        self._source_language.addItem("日语（保留纯汉字行）", "JA")
        self._source_language.addItem("中文", "ZH")
        source_index = self._source_language.findData(self._settings.source_language)
        self._source_language.setCurrentIndex(max(0, source_index))
        self._target_language = QComboBox()
        self._target_language.addItem("简体中文", "ZH-HANS")
        self._target_language.addItem("英语", "EN-US")
        self._target_language.addItem("日语", "JA")
        target_index = self._target_language.findData(self._settings.target_language)
        self._target_language.setCurrentIndex(max(0, target_index))
        self._source_language.currentIndexChanged.connect(self._language_changed)
        self._target_language.currentIndexChanged.connect(self._language_changed)
        language_row.addWidget(self._source_language, 2)
        language_row.addWidget(QLabel("→"))
        language_row.addWidget(self._target_language, 1)
        form.addRow("翻译语言", language_row)

        key_row = QHBoxLayout()
        self._api_key = QLineEdit()
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("DeepL API Key（免费版通常以 :fx 结尾）")
        save_key = QPushButton("保存设置")
        save_key.clicked.connect(self._save_settings)
        key_row.addWidget(self._api_key, 1)
        key_row.addWidget(save_key)
        form.addRow("API Key", key_row)
        layout.addLayout(form)

        button_row = QHBoxLayout()
        self._select_button = QPushButton("选择区域并开始")
        self._pause_button = QPushButton("暂停")
        self._original_button = QPushButton("显示原文")
        self._stop_button = QPushButton("停止")
        self._select_button.clicked.connect(self.select_region)
        self._pause_button.clicked.connect(self.toggle_pause)
        self._original_button.clicked.connect(self.toggle_original)
        self._stop_button.clicked.connect(self.stop_session)
        for button in (
            self._select_button,
            self._pause_button,
            self._original_button,
            self._stop_button,
        ):
            button_row.addWidget(button)
        layout.addLayout(button_row)

        self._region_label = QLabel("区域：未选择")
        self._status = QLabel("状态：正在后台预热 OCR 模型")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            "padding: 9px; background: #162033; color: #e8f2ff; border-radius: 5px;"
        )
        layout.addWidget(self._region_label)
        layout.addWidget(self._status)
        shortcuts = QLabel(
            "快捷键  Ctrl+Shift+T 开始/选择 · Ctrl+Shift+O 原文 · "
            "Ctrl+Shift+P 暂停 · Ctrl+Shift+S 停止"
        )
        shortcuts.setWordWrap(True)
        shortcuts.setStyleSheet("color: #667085;")
        layout.addWidget(shortcuts)
        self.setCentralWidget(root)

    def _source_code(self) -> str:
        return str(self._source_language.currentData())

    def _target_code(self) -> str:
        return str(self._target_language.currentData())

    def _language_changed(self) -> None:
        self._overlay.clear()
        self._reset_analysis()
        if same_language(self._source_code(), self._target_code()):
            self._set_status("源语言和目标语言相同，请重新选择。")
        elif self._region is not None:
            self._set_status("语言设置已改变，将按新设置重新识别。")

    def _load_secret_into_ui(self) -> None:
        try:
            self._api_key.setText(unprotect_secret(self._settings.encrypted_api_key))
        except Exception:
            self._api_key.clear()
            self._set_status("已保存的 API Key 无法解密，请重新输入。")

    def _save_settings(self) -> None:
        try:
            self._settings.provider = self._provider.currentText()
            self._settings.source_language = self._source_code()
            self._settings.target_language = self._target_code()
            self._settings.encrypted_api_key = protect_secret(self._api_key.text().strip())
            self._store.save(self._settings)
            self._set_status("设置已保存，API Key 使用 Windows DPAPI 加密。")
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))

    def _reset_analysis(self) -> None:
        self._session_id += 1
        self._latest_image = None
        self._latest_signature = None
        self._pending_capture = None
        self._pending_translation = None
        self._ocr_snapshot = None
        with self._tracking_lock:
            self._gate.reset()
            self._region_tracker.reset()
            self._tracker_version += 1

    def select_region(self) -> None:
        if same_language(self._source_code(), self._target_code()):
            self._set_status("源语言和目标语言不能相同。")
            return
        if self._selection is not None:
            return
        self._reset_analysis()
        self._capture_timer.stop()
        self._overlay.hide()
        self.hide()
        self._selection = SelectionOverlay(self._virtual_geometry)
        self._selection.region_selected.connect(self._region_selected)
        self._selection.canceled.connect(self._selection_canceled)
        self._selection.destroyed.connect(self._selection_destroyed)
        self._selection.show()

    def _selection_destroyed(self) -> None:
        self._selection = None

    def _selection_canceled(self) -> None:
        self.show()
        if self._region and not self._paused:
            self._capture_timer.start()
        self._set_status("已取消区域选择。")

    def _region_selected(self, region: Rect) -> None:
        self._region = region
        self._reset_analysis()
        self._paused = False
        self._original_visible = False
        self._overlay.clear()
        self._overlay.set_selection(region)
        self._overlay.set_original_visible(False)
        self._pause_button.setText("暂停")
        self._original_button.setText("显示原文")
        self._region_label.setText(
            f"区域：x={region.x}, y={region.y}, {region.width}×{region.height}"
        )
        self.show()
        self._capture_timer.start()
        self._set_status("正在监测；画面稳定后自动识别并翻译。")

    def _schedule_capture(self) -> None:
        if self._region is None or self._paused or self._capture_future is not None:
            return
        self._capture_future = self._capture_executor.submit(
            self._capture_frame,
            self._region,
            self._session_id,
            self._analysis_future is None,
        )

    def _capture_frame(self, region: Rect, session_id: int, can_submit: bool) -> _CaptureResult:
        try:
            captured_at = perf_counter()
            image = self._capturer.grab(region)
            signature = frame_signature(image)
            with self._tracking_lock:
                if session_id != self._session_id:
                    return _CaptureResult(session_id, region)
                should_analyze = self._gate.observe_signature(
                    signature, captured_at, can_submit=can_submit
                )
                change_seen_at = self._gate.candidate_since
                stable_at = self._gate.ready_since or captured_at
                tracking = self._region_tracker.track(image)
                tracker_version = self._tracker_version
            return _CaptureResult(
                session_id,
                region,
                image,
                signature,
                should_analyze,
                tracking.regions,
                tracking.lost,
                tracker_version,
                change_seen_at=change_seen_at,
                stable_at=stable_at,
            )
        except Exception as exc:
            return _CaptureResult(session_id, region, error=f"截屏失败：{exc}")

    def _analyze_frame(
        self,
        capture: _CaptureResult,
        previous: OcrSnapshot | None,
        source_language: str,
        target_language: str,
    ) -> _AnalysisResult:
        image, signature = capture.image, capture.signature
        assert image is not None and signature is not None
        started = perf_counter()
        snapshot = recognize_changed(image, self._ocr.recognize, previous)
        ocr_seconds = perf_counter() - started
        accepted = filter_regions(list(snapshot.regions), source_language, target_language)
        if accepted:
            styled = apply_region_styles(image, accepted)
            mapped = map_regions_to_logical_screen(styled, capture.region, image.size)
            pipeline = PipelineResult(tuple(mapped))
        elif snapshot.regions:
            pipeline = PipelineResult((), "检测到的文字不属于所选源语言，已跳过。")
        else:
            pipeline = PipelineResult(())
        return _AnalysisResult(
            capture.session_id,
            capture.region,
            snapshot,
            signature,
            pipeline,
            capture.change_seen_at,
            capture.stable_at,
            ocr_seconds,
        )

    def _translate_frame(
        self, analysis: _AnalysisResult, api_key: str, source_language: str, target_language: str
    ) -> _TranslationResult:
        pipeline = analysis.pipeline
        regions = pipeline.regions
        if not regions:
            return _TranslationResult(analysis, pipeline)
        started = perf_counter()
        try:
            if not api_key:
                raise TranslationError("已识别文字，请填写 DeepL API Key。")
            texts = [item.source_text for item in regions]
            source_code = None if source_language == "AUTO" else source_language
            translations = self._translator.translate(
                texts,
                api_key,
                context="\n".join(texts),
                source_lang=source_code,
                target_lang=target_language,
            )
            translation_seconds = perf_counter() - started
            translated = tuple(
                item.with_translation(value)
                for item, value in zip(regions, translations, strict=True)
                if translation_changes_text(item.source_text, value)
            )
            return _TranslationResult(analysis, PipelineResult(translated), translation_seconds)
        except TranslationError as exc:
            return _TranslationResult(
                analysis, PipelineResult((), str(exc)), perf_counter() - started
            )

    def _reconcile_regions(
        self,
        source_image: Image.Image,
        region: Rect,
        regions: tuple[TextRegion, ...],
    ) -> tuple[TextRegion, ...] | None:
        latest = self._latest_image if self._latest_image is not None else source_image
        with self._tracking_lock:
            self._region_tracker.remember(source_image, regions, region)
            tracking = self._region_tracker.track(latest)
            self._tracker_version += 1
        return tracking.regions

    def _poll_results(self) -> None:
        self._poll_capture_result()
        self._poll_analysis_result()
        self._poll_translation_results()
        if self._paused or self._region is None or self._selection is not None:
            return
        if self._analysis_future is None and self._pending_capture is not None:
            capture, self._pending_capture = self._pending_capture, None
            self._analysis_future = self._analysis_executor.submit(
                self._analyze_frame,
                capture,
                self._ocr_snapshot,
                self._source_code(),
                self._target_code(),
            )
        self._schedule_translation()

    def _schedule_translation(self) -> None:
        analysis = self._pending_translation
        if analysis is None or len(self._translation_jobs) >= _TRANSLATION_SLOTS:
            return
        # Requests for two viewports can overlap, but shared lines stay with
        # their original request. New lines can proceed in the free slot.
        reserved = {
            item.source_text
            for job in self._translation_jobs.values()
            if job.session_id == analysis.session_id
            for item in job.pipeline.regions
        }
        regions = analysis.pipeline.regions
        ready = tuple(item for item in regions if item.source_text not in reserved)
        waiting = tuple(item for item in regions if item.source_text in reserved)
        if regions and not ready:
            return
        self._pending_translation = (
            replace(analysis, pipeline=PipelineResult(waiting)) if waiting else None
        )
        if waiting:
            analysis = replace(analysis, pipeline=PipelineResult(ready))
        future = self._translation_executor.submit(
            self._translate_frame,
            analysis,
            self._api_key.text().strip(),
            self._source_code(),
            self._target_code(),
        )
        self._translation_jobs[future] = analysis

    def _viewport_moved(self, signature: np.ndarray) -> bool:
        return (
            self._latest_signature is not None
            and frame_difference(self._latest_signature, signature)
            > self._settings.change_threshold * 0.7
        )

    def _poll_capture_result(self) -> None:
        if self._capture_future is None or not self._capture_future.done():
            return
        future = self._capture_future
        self._capture_future = None
        try:
            result = future.result()
        except Exception as exc:
            self._set_status(f"截图跟踪任务失败：{exc}")
            return
        if (
            self._region is None
            or result.session_id != self._session_id
            or result.region != self._region
        ):
            return
        if result.error:
            self._set_status(result.error)
            return
        if result.image is None:
            return
        self._latest_image = result.image
        self._latest_signature = result.signature
        if self._pending_translation and self._viewport_moved(self._pending_translation.signature):
            self._pending_translation = None
        if result.tracker_version == self._tracker_version and result.tracked_regions is not None:
            self._overlay.set_regions(() if result.tracking_lost else result.tracked_regions)
        if result.should_analyze:
            self._pending_capture = result
            self._pending_translation = None

    def _poll_analysis_result(self) -> None:
        if self._analysis_future is None or not self._analysis_future.done():
            return
        future = self._analysis_future
        self._analysis_future = None
        try:
            analysis = future.result()
        except Exception as exc:
            self._set_status(f"OCR 后台任务失败：{exc}")
            return
        if analysis.session_id != self._session_id:
            return
        self._ocr_snapshot = analysis.snapshot
        stale = self._pending_capture is not None or self._viewport_moved(analysis.signature)
        _record_performance(
            "ocr",
            mode=analysis.snapshot.mode,
            backend=getattr(self._ocr, "backend", "unknown"),
            width=analysis.snapshot.image.width,
            height=analysis.snapshot.image.height,
            seconds=round(analysis.ocr_seconds, 3),
            stale=stale,
        )
        if not stale:
            self._show_cached_regions(analysis)
            self._pending_translation = analysis

    def _show_cached_regions(self, analysis: _AnalysisResult) -> None:
        regions = analysis.pipeline.regions
        lookup = getattr(self._translator, "cached_translations", None)
        if not regions or lookup is None:
            return
        source = self._source_code()
        cached = lookup(
            [item.source_text for item in regions],
            self._api_key.text().strip(),
            None if source == "AUTO" else source,
            self._target_code(),
        )
        ready = tuple(
            item.with_translation(value)
            for item, value in zip(regions, cached, strict=True)
            if value is not None and translation_changes_text(item.source_text, value)
        )
        if ready:
            located = self._reconcile_regions(analysis.snapshot.image, analysis.region, ready)
            if located is not None:
                self._overlay.set_regions(located)

    def _poll_translation_results(self) -> None:
        for future in tuple(self._translation_jobs):
            if future.done():
                self._translation_jobs.pop(future)
                self._finish_translation(future)

    def _finish_translation(self, future: Future[_TranslationResult]) -> None:
        try:
            translation = future.result()
        except Exception as exc:
            self._set_status(f"翻译后台任务失败：{exc}")
            return
        analysis = translation.analysis
        if analysis.session_id != self._session_id:
            return
        result = translation.pipeline
        translated_count = sum(bool(item.translated_text) for item in result.regions)
        if self._viewport_moved(analysis.signature):
            _record_performance(
                "discarded_translation",
                seconds=round(translation.translation_seconds, 3),
                translated=translated_count,
            )
            return
        if translated_count:
            reconciled = self._reconcile_regions(
                analysis.snapshot.image, analysis.region, result.regions
            )
            if not reconciled:
                return
            self._overlay.set_regions(reconciled)
            total = perf_counter() - analysis.change_seen_at
            settling = analysis.stable_at - analysis.change_seen_at
            ocr = analysis.ocr_seconds
            translate = translation.translation_seconds
            other = max(0.0, total - settling - ocr - translate)
            _record_performance(
                "display",
                mode=analysis.snapshot.mode,
                total=round(total, 3),
                stable=round(settling, 3),
                ocr=round(ocr, 3),
                translation=round(translate, 3),
                queue_and_paint=round(other, 3),
                translated=translated_count,
            )
            self._set_status(
                f"已更新 {translated_count} 处 · 总计 {total:.2f}s\n"
                f"稳定 {settling:.2f}s · OCR（{analysis.snapshot.mode}）{ocr:.2f}s"
                f" · 翻译 {translate:.2f}s · 排队/绘制 {other:.2f}s"
            )
        elif self._latest_signature is None or not frame_changed(
            self._latest_signature, analysis.signature, self._settings.change_threshold
        ):
            self._set_status(result.error or "当前画面没有新增需要覆盖的译文。")

    def toggle_pause(self) -> None:
        if self._region is None:
            self._set_status("请先选择翻译区域。")
            return
        self._paused = not self._paused
        if self._paused:
            self._session_id += 1
            self._capture_timer.stop()
            self._pause_button.setText("恢复")
            self._set_status("已暂停；当前译文保持显示。")
        else:
            self._reset_analysis()
            self._capture_timer.start()
            self._pause_button.setText("暂停")
            self._set_status("已恢复自动翻译。")

    def toggle_original(self) -> None:
        self._original_visible = not self._original_visible
        self._overlay.set_original_visible(self._original_visible)
        self._original_button.setText("显示译文" if self._original_visible else "显示原文")
        self._set_status("正在显示原文。" if self._original_visible else "正在显示译文。")

    def stop_session(self) -> None:
        self._capture_timer.stop()
        self._region = None
        self._paused = False
        self._reset_analysis()
        self._overlay.clear()
        self._region_label.setText("区域：未选择")
        self._pause_button.setText("暂停")
        self._set_status("当前会话已停止。")

    def _handle_hotkey(self, action: str) -> None:
        if action == "start":
            if self._region is None:
                self.select_region()
            elif self._paused:
                self.toggle_pause()
            else:
                self._reset_analysis()
                self._capture_timer.start()
                self._set_status("自动翻译已开始。")
        elif action == "original":
            self.toggle_original()
        elif action == "pause":
            self.toggle_pause()
        elif action == "stop":
            self.stop_session()

    def _show_hotkey_error(self, message: str) -> None:
        self._set_status(message)

    def _set_status(self, message: str) -> None:
        self._status.setText(f"状态：{message}")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._capture_timer.stop()
        self._poll_timer.stop()
        self._hotkeys.stop()
        self._overlay.close()
        if self._selection is not None:
            self._selection.close()
        self._capture_executor.shutdown(wait=False, cancel_futures=True)
        self._analysis_executor.shutdown(wait=False, cancel_futures=True)
        self._translation_executor.shutdown(wait=False, cancel_futures=True)
        self._translator.close()
        event.accept()
