# 屏幕翻译助手 · iOS 原型

要求 iOS / iPadOS 17 或更新版本。本版处理内置浏览器中的 HTTPS 网页，不读取 Safari 或其他应用的窗口，也不在其他应用上绘制。

## 手机上试用

1. 在顶部输入网址并打开，或者从右上角菜单打开「本地预览」。预览不需要网络或 API Key；打开后点「开始」，再试着滚动和点页面里的 **Show new text**。
2. 真正翻译前，在「语言与密钥」中填写个人 DeepL API Key，选好原文和目标语言。密钥只存手机的 Keychain；只有待翻译的文字发给 DeepL，截图不上传。
3. 点「选区」，在网页内拖出矩形，再点「开始」。不框选则监测整个可见网页。网页变动后自动读取，译文尽量沿原文左缘绘制，普通页面滚动时已有译文随网页移动。「原文」暂时关闭译文，「停止」结束监测。
4. 普通网页使用默认的「网页文字」。文字绘在图片或 canvas 上时，手动切换「图片 OCR」，在手机上用 Vision 识别。滚动或画面变化时，旧的 OCR 译文会先撤掉，避免留在错误位置。

硬件键盘快捷键：⌘⇧T 开始，⌘⇧O 切换原文和译文，⌘⇧S 停止。

默认自动识别英、日、中并译为简体中文。自动模式会保留已是目标语言的内容。无假名且没有日语页面标记的纯汉字短句，无法可靠区分中日文，默认按中文保留。网页识别是针对正文文字节点的首版实现：不读跨域 iframe 或封闭的 shadow DOM，不保证复杂动画、页面缩放、特殊排版和艺术字的准确性。图片 OCR 不会自动和网页文字模式混合。

## 生成未签名 IPA

Windows 上的 ipasign 负责签名和安装，不能编译 Swift / iOS 工程。先在有 Xcode 15 或更新版本的 Mac 上，在本目录运行：

```bash
bash scripts/build-ipa.sh
```

生成 `build/ScreenTranslate-unsigned.ipa`。也可以打开 `ScreenTranslate.xcodeproj` 用 iOS Simulator 调试；模拟器产物不能拿来装到手机上。

没有 Mac 时，把公开源码提交到你自己的 GitHub 仓库，在 **Actions → Build unsigned iOS IPA → Run workflow** 手动构建。完成后下载 `ScreenTranslate-unsigned` 构建产物并解压。构建不需要 Apple 登录、证书或 DeepL API Key。

## 用 ipasign 签名和装机

将未签名 IPA 拿回 Windows，放到不上传的私有目录。使用自己的签名身份。在 ipasign 的 TUI 中选择「签名 IPA」和「安装到设备」，或使用已有的证书库条目：

```powershell
ipasign devices
ipasign renew "<证书库条目>" ".\ScreenTranslate-unsigned.ipa" -o ".\ScreenTranslate-signed.ipa" --install
```

在存放 IPA 的私有目录内运行这两条命令。Windows USB 装机需要 Apple Devices / iTunes 的设备驱动。Apple 账号、证书、描述文件和 DeepL Key 均不应出现在公开仓库中。有关签名身份、设备配对及开发者模式，参见 ipasign 仓库的中文使用说明。

## 验证范围

`tests/bridge-smoke.html` 可在 Chromium 中打开，在控制台查看 `document.body.dataset.smokeResult`。它验证网页选区、样式覆盖、滚动、缓存、动态文字、清除旧译文和 OCR 绘制的过期保护；不代替 Xcode 编译、iOS WebKit、Vision、DeepL 或真机签名测试。
