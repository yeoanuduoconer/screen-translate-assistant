# 屏幕翻译助手

Windows 桌面工具。框选网页、图片或应用中的文字区域后，程序持续监测变化，在原文位置绘制译文覆盖层。默认识别英语和日语并译为简体中文，也可以在窗口中切换语言。

## 安装

需要 Windows 10 2004 或更新版本（x64）、Python 3.11 x64，以及用于联网翻译的个人 DeepL API Key。在仓库根目录运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

脚本创建项目自己的 `.venv`，从包索引安装依赖，并下载、校验 PP-OCRv6 Small 的 ONNX 模型。如果系统默认 Python 不是 3.11，可在命令后加 `-PythonExe <Python 3.11 的 python.exe 路径>`。模型下载失败时，可重试并指定 `-ModelSource modelscope` 或 `-ModelSource huggingface`。

## 使用

1. 双击根目录里的 `启动屏幕翻译助手.cmd`。
2. 在窗口内输入自己的 [DeepL API Key](https://developers.deepl.com/docs/getting-started/auth)，点击“保存设置”。
3. 选择源语言和目标语言，点“选择区域并开始”，拖出监测框。

| 快捷键 | 动作 |
| --- | --- |
| `Ctrl+Shift+T` | 开始、选区或恢复 |
| `Ctrl+Shift+O` | 切换原文与译文 |
| `Ctrl+Shift+P` | 暂停或恢复 |
| `Ctrl+Shift+S` | 停止当前会话 |

OCR 在本机运行，优先使用 ONNX Runtime；无法使用该后端时回退到 Paddle，首次回退可能需要下载 Paddle 模型。程序使用屏幕坐标绘制覆盖层，页面滚动时根据截图重新核对位置。画面动画、艺术字和复杂背景会影响识别与定位。在自动模式中，纯汉字行按中文保留，无法确认语言的纯汉字日文也可能被跳过。

## 隐私

- 选区截图用于本地识别。开启翻译后，需要翻译的识别文字及文字上下文会发往 DeepL。
- Key 经 Windows DPAPI 加密后保存在当前用户的 `%LOCALAPPDATA%\ScreenTranslateAssistant\config.json`。请在应用界面填写，发布源码时不要提交自己的配置、密钥或日志。
- 项目内的 `.cache/` 存放下载的模型和本地运行诊断，已从 Git 提交范围中排除。性能日志记录阶段耗时、识别模式和计数。

## 开发与测试

设置时加 `-Dev` 可安装 pytest 和 Ruff。测试使用生成的画面与模拟翻译响应。

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
```

安装模型后，可以运行 `scripts/benchmark_full_ocr_backends.py` 比较两种 OCR 后端的全图识别耗时和坐标。它需要 Windows 的日文字体，测量范围为本地 OCR。源码中的入口、识别、跟踪和翻译模块见 [实现说明](docs/architecture.md)。

依赖和模型各自适用上游许可。模型来源：[PP-OCRv6 Small 检测](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_det_onnx) · [PP-OCRv6 Small 识别](https://huggingface.co/PaddlePaddle/PP-OCRv6_small_rec_onnx)。
