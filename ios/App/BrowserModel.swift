import Foundation
import SwiftUI
import WebKit

enum ScanMode: String, CaseIterable, Identifiable {
    case dom, ocr
    var id: String { rawValue }
    var label: String { self == .dom ? "网页文字" : "图片 OCR" }
}

struct Selection: Equatable {
    var x: Double = 0
    var y: Double = 0
    var w: Double = 1
    var h: Double = 1
    var object: [String: Double] { ["x": x, "y": y, "w": w, "h": h] }
    func rect(in size: CGSize) -> CGRect {
        CGRect(x: x * size.width, y: y * size.height, width: w * size.width, height: h * size.height)
    }
    init() {}
    init(rect: CGRect, size: CGSize) {
        x = rect.minX / size.width
        y = rect.minY / size.height
        w = rect.width / size.width
        h = rect.height / size.height
    }
}

@MainActor
final class BrowserModel: NSObject, ObservableObject, WKNavigationDelegate, WKUIDelegate {
    @Published var address = ""
    @Published var status = "输入网址，或打开本地预览。"
    @Published var source: Language = .auto
    @Published var target: Language = .chinese
    @Published var mode: ScanMode = .dom
    @Published private(set) var enabled = false
    @Published private(set) var showingOriginal = false
    @Published private(set) var canGoBack = false
    @Published private(set) var selection = Selection()

    let web: WKWebView
    private let world: WKContentWorld
    private let translator = DeepL()
    private var key = APIKeyStore.load()
    private var epoch = 0
    private var loop: Task<Void, Never>?
    private var domTask: Task<Void, Never>?
    private var lastDOM: [DOMItem] = []
    private var lastOCR: (Int, Metrics)?
    private var demo = false
    private var ready = false

    private struct DOMItem: Codable, Equatable {
        let id: String
        let text: String
        let lang: String
    }
    private struct Scan: Decodable {
        let session: String
        let changed: Bool
        let items: [DOMItem]
    }
    private struct Metrics: Decodable, Equatable {
        let session: String
        let revision: Int
        let x, y, w, h, vx, vy, vw, vh, scrollX, scrollY: Double
        var stamp: [String: Any] { ["session": session, "revision": revision, "scrollX": scrollX, "scrollY": scrollY] }
    }

    override init() {
        let world = WKContentWorld.world(name: "ScreenTranslate.Isolated")
        self.world = world
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        if let url = Bundle.main.url(forResource: "Bridge", withExtension: "js"),
           let script = try? String(contentsOf: url, encoding: .utf8) {
            config.userContentController.addUserScript(WKUserScript(
                source: script, injectionTime: .atDocumentEnd, forMainFrameOnly: true, in: world
            ))
        }
        web = WKWebView(frame: .zero, configuration: config)
        super.init()
        web.navigationDelegate = self
        web.uiDelegate = self
        web.allowsBackForwardNavigationGestures = true
    }

    var hasKey: Bool { !key.isEmpty }

    func saveKey(_ value: String) throws {
        try APIKeyStore.save(value)
        key = value.trimmingCharacters(in: .whitespacesAndNewlines)
        stop()
        status = key.isEmpty ? "已清除本机 API Key。" : "已将 API Key 保存到本机。"
        Task { await translator.clear() }
    }

    func navigate() {
        let input = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !input.isEmpty,
              let url = URL(string: input.contains("://") ? input : "https://" + input),
              url.scheme?.lowercased() == "https", url.host != nil else {
            status = "请输入 HTTPS 网页地址。"; return
        }
        demo = false
        web.load(URLRequest(url: url))
    }

    func openDemo() {
        guard let url = Bundle.main.url(forResource: "Demo", withExtension: "html"),
              let html = try? String(contentsOf: url, encoding: .utf8) else { return }
        demo = true
        web.loadHTMLString(html, baseURL: nil)
    }

    func updateSelection(_ value: Selection) {
        selection = value
        if enabled { restart() }
    }

    func start() {
        guard ready else { status = AppFailure.bridge.localizedDescription; return }
        guard hasKey || demo else { status = AppFailure.missingKey.localizedDescription; return }
        guard !demo || mode == .dom else { status = "本地预览只演示网页文字。"; return }
        enabled = true
        showingOriginal = false
        restart()
    }

    func stop() {
        enabled = false
        showingOriginal = false
        cancelWork()
        status = "已停止，正在显示原文。"
        let token = epoch
        Task {
            guard token == epoch else { return }
            _ = try? await javascript("return screenTranslation.configure('off', area);", ["area": selection.object])
        }
    }

    func toggleOriginal() {
        showingOriginal.toggle()
        restart()
    }

    func restartIfRunning() {
        if enabled { restart() }
    }

    private func cancelWork() {
        epoch += 1
        loop?.cancel()
        domTask?.cancel()
        lastDOM = []
        lastOCR = nil
    }

    private func restart() {
        cancelWork()
        let token = epoch
        loop = Task { [weak self] in
            guard let self, token == epoch, ready else { return }
            do {
                let unsupportedDemo = demo && mode != .dom
                let actualMode = enabled && !showingOriginal && !unsupportedDemo ? mode.rawValue : "off"
                _ = try await javascript("screenTranslation.setHidden(false); return screenTranslation.configure(mode, area);",
                    ["mode": actualMode, "area": selection.object])
                guard token == epoch else { return }
                guard actualMode != "off" else {
                    status = unsupportedDemo ? "本地预览只演示网页文字。" : "显示原文"
                    return
                }
                status = demo ? "本地预览：不调用翻译服务" : "监测选区中"
                while token == epoch && !Task.isCancelled {
                    do {
                        if mode == .dom { try await pollDOM(token) }
                        else { try await pollOCR(token) }
                        try await Task.sleep(for: .milliseconds(mode == .dom ? 350 : 1450))
                    } catch is CancellationError {
                        return
                    } catch {
                        guard token == epoch else { return }
                        status = error.localizedDescription
                        try await Task.sleep(for: .seconds(3))
                    }
                }
            } catch is CancellationError {
                return
            } catch {
                if token == epoch { status = error.localizedDescription }
            }
        }
    }

    private func javascript(_ code: String, _ args: [String: Any] = [:]) async throws -> Any? {
        try await web.callAsyncJavaScript(code, arguments: args, in: nil, contentWorld: world)
    }

    private func decode<T: Decodable>(_ type: T.Type, _ expression: String) async throws -> T {
        guard let json = try await javascript("return JSON.stringify(" + expression + ");") as? String else {
            throw AppFailure.bridge
        }
        return try JSONDecoder().decode(type, from: Data(json.utf8))
    }

    private func plan(_ text: String, hint: String) -> DeepL.Entry? {
        let inferred = Language.guess(text, hint: hint)
        guard inferred != target else { return nil }
        if source == .auto {
            guard let inferred else { return nil }
            return .init(text: text, source: inferred, target: target)
        }
        guard source != target, inferred == nil || inferred == source ||
              (source == .japanese && mode == .ocr && inferred == .chinese) else { return nil }
        return .init(text: text, source: source, target: target)
    }

    private func pollDOM(_ token: Int) async throws {
        let scan = try await decode(Scan.self, "screenTranslation.scan()")
        guard token == epoch, scan.changed, scan.items != lastDOM else { return }
        lastDOM = scan.items
        domTask?.cancel()
        let items = scan.items.compactMap { item in
            plan(item.text, hint: item.lang).map { (item, $0) }
        }
        guard !items.isEmpty else { return }
        domTask = Task { [weak self] in
            guard let self else { return }
            do {
                for start in stride(from: 0, to: items.count, by: 12) {
                    try Task.checkCancellation()
                    let batch = items[start..<min(start + 12, items.count)]
                    let values = try await translate(batch.map { $0.1 })
                    try Task.checkCancellation()
                    guard token == epoch else { return }
                    let rendered = batch.compactMap { item, entry -> [String: String]? in
                        guard let translated = values[entry] else { return nil }
                        return ["original": item.text, "lang": item.lang, "translation": translated]
                    }
                    _ = try await javascript("return screenTranslation.accept(session, items);",
                        ["session": scan.session, "items": rendered])
                    if token == epoch { status = demo ? "本地预览：未联网" : "监测选区中 · 已翻译" }
                }
            } catch is CancellationError {
                return
            } catch {
                guard token == epoch else { return }
                status = error.localizedDescription
                try? await Task.sleep(for: .seconds(4))
                guard token == epoch, !Task.isCancelled else { return }
                lastDOM = []
                _ = try? await javascript("screenTranslation.retry();")
            }
        }
    }

    private func translate(_ batch: [DeepL.Entry]) async throws -> [DeepL.Entry: String] {
        if demo {
            let examples = [
                "Hello from the translation preview.": "你好，这里是翻译预览。",
                "日本語の文字を認識します。": "正在识别日语文字。",
                "This text appeared without a reload.": "这行文字无需刷新就出现了。",
                "The translation follows this paragraph.": "译文会跟随这段文字。"
            ]
            var result: [DeepL.Entry: String] = [:]
            for entry in batch { result[entry] = examples[entry.text] }
            return result
        }
        var result: [DeepL.Entry: String] = [:]
        var remaining = batch
        while let first = remaining.first {
            try Task.checkCancellation()
            let group = Array(remaining.filter { $0.source == first.source }.prefix(12))
            let values = try await translator.translate(group, key: key)
            result.merge(values, uniquingKeysWith: { _, new in new })
            let sent = Set(group)
            remaining.removeAll { sent.contains($0) }
        }
        return result
    }

    private func pollOCR(_ token: Int) async throws {
        let metrics = try await decode(Metrics.self, "screenTranslation.metrics()")
        guard token == epoch, metrics.w > 0, metrics.h > 0 else { return }
        let rect = selection.rect(in: web.bounds.size).intersection(web.bounds)
        guard !rect.isNull, rect.width > 10, rect.height > 10 else { return }
        _ = try await javascript("screenTranslation.setHidden(true);")
        let config = WKSnapshotConfiguration()
        config.rect = rect
        config.snapshotWidth = NSNumber(value: min(900, max(300, rect.width * 2)))
        let image: UIImage
        do {
            image = try await web.takeSnapshot(configuration: config)
        } catch {
            if token == epoch { _ = try? await javascript("screenTranslation.setHidden(false);") }
            throw error
        }
        guard token == epoch else { return }
        _ = try await javascript("screenTranslation.setHidden(false);")
        guard let cgImage = image.cgImage, let jpeg = image.jpegData(compressionQuality: 0.2) else { return }
        let signature = jpeg.hashValue
        if let (previous, stamp) = lastOCR, previous == signature, stamp == metrics { return }
        let language = source
        let ocrTask = Task.detached(priority: .userInitiated) { try ScreenOCR.recognize(cgImage, source: language) }
        let lines = try await withTaskCancellationHandler(operation: { try await ocrTask.value },
            onCancel: { ocrTask.cancel() })
        guard token == epoch, try await decode(Metrics.self, "screenTranslation.metrics()") == metrics else { return }
        let pairs = lines.compactMap { line in plan(line.text, hint: "").map { (line, $0) } }.prefix(60)
        var rendered: [[String: Any]] = []
        for start in stride(from: 0, to: pairs.count, by: 12) {
            let batch = pairs[start..<min(start + 12, pairs.count)]
            let translations = try await translate(batch.map { $0.1 })
            guard token == epoch else { return }
            for (line, entry) in batch {
                guard let translated = translations[entry] else { continue }
                rendered.append(["x": metrics.x + line.rect.minX * metrics.w,
                    "y": metrics.y + line.rect.minY * metrics.h, "w": line.rect.width * metrics.w,
                    "h": line.rect.height * metrics.h, "text": translated,
                    "background": line.background, "color": line.color])
            }
            let applied = try await javascript("return screenTranslation.applyOCR(stamp, items);",
                ["stamp": metrics.stamp, "items": rendered]) as? Bool ?? false
            guard applied else { return }
        }
        if rendered.isEmpty {
            _ = try await javascript("return screenTranslation.applyOCR(stamp, []);", ["stamp": metrics.stamp])
        }
        guard token == epoch else { return }
        lastOCR = (signature, metrics)
        status = "图片 OCR · \(rendered.count) 行译文"
    }

    func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
        ready = false
        cancelWork()
        status = "页面加载中…"
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        ready = true
        canGoBack = web.canGoBack
        address = demo ? "" : web.url?.absoluteString ?? address
        if enabled { restart() }
        else { status = demo ? "本地预览已就绪，点「开始」。" : "网页已就绪，点「开始」。" }
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).code != NSURLErrorCancelled { status = "页面未能加载：\(error.localizedDescription)" }
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        let scheme = action.request.url?.scheme?.lowercased()
        if action.targetFrame?.isMainFrame == true && scheme == "https" { demo = false }
        decisionHandler(scheme == "https" || scheme == "about" ? .allow : .cancel)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if action.targetFrame == nil, action.request.url?.scheme?.lowercased() == "https" {
            webView.load(action.request)
        }
        return nil
    }
}
