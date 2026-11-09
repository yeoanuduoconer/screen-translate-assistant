# 实现说明

应用由 PySide6 窗口、屏幕采集线程、独立 OCR 进程、DeepL 请求线程和透明覆盖层组成。

1. [采集与变化检测](../src/screen_translator/capture.py) 获取选区截图，等待画面稳定。识别器空闲时才提交最新画面。
2. [OCR](../src/screen_translator/ocr.py) 尝试复用已核对的局部或滚动区域，必要时识别全图。优先选择本机 ONNX 模型，Paddle 作为回退。
3. [调度](../src/screen_translator/main_window.py) 筛选源语言，将截图坐标映射到桌面坐标，先显示已缓存的译文。[DeepL 客户端](../src/screen_translator/translation.py) 对未命中文本去重、分批请求。
4. [逐行跟踪](../src/screen_translator/region_tracking.py) 核对当前截图中的原文位置。[覆盖层](../src/screen_translator/overlays.py) 在选区内按字形边界绘制译文。
5. [用户设置](../src/screen_translator/settings.py) 使用 Windows 用户目录保存选项和加密后的 API Key。
