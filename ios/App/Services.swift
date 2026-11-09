import Foundation
import NaturalLanguage
import Security
import UIKit
import Vision

enum Language: String, CaseIterable, Identifiable {
    case auto, english, japanese, chinese
    var id: String { rawValue }
    var label: String {
        switch self {
        case .auto: "自动（英 / 日 / 中）"
        case .english: "英语"
        case .japanese: "日语"
        case .chinese: "简体中文"
        }
    }
    var source: String {
        switch self {
        case .auto: ""
        case .english: "EN"
        case .japanese: "JA"
        case .chinese: "ZH"
        }
    }
    var target: String { self == .chinese ? "ZH-HANS" : (self == .english ? "EN-US" : source) }

    static func guess(_ text: String, hint: String) -> Self? {
        let language = hint.lowercased().split(separator: "-").first
        if text.range(of: "[\\p{Hiragana}\\p{Katakana}]", options: .regularExpression) != nil {
            return .japanese
        }
        let hasHan = text.range(of: "\\p{Han}", options: .regularExpression) != nil
        if hasHan {
            // Pure Han text cannot be distinguished reliably without a page language hint.
            return language == "ja" ? .japanese : .chinese
        }
        let engine = NLLanguageRecognizer()
        engine.processString(text)
        if engine.dominantLanguage == .english || language == "en" { return .english }
        if engine.dominantLanguage == .japanese { return .japanese }
        return nil
    }
}

enum AppFailure: LocalizedError {
    case missingKey, keychain(OSStatus), response, service(Int), bridge
    var errorDescription: String? {
        switch self {
        case .missingKey: "请先在设置中填写 DeepL API Key。"
        case .keychain(let status): "无法保存密钥（Keychain \(status)）。"
        case .response: "翻译服务返回了无法读取的结果。"
        case .service(let status):
            switch status {
            case 401, 403: "DeepL 拒绝了请求，请检查 API Key。"
            case 429: "DeepL 请求过于频繁，请稍后重试。"
            case 456: "DeepL 翻译额度已用完。"
            default: "DeepL 请求失败（HTTP \(status)）。"
            }
        case .bridge: "当前页面还不能读取，请等加载完成后重试。"
        }
    }
}

enum APIKeyStore {
    private static let base: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "screen-translate-assistant.ios",
        kSecAttrAccount as String: "deepl"
    ]

    static func load() -> String {
        var query = base
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var item: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess,
              let bytes = item as? Data else { return "" }
        return String(decoding: bytes, as: UTF8.self)
    }

    static func save(_ value: String) throws {
        let value = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if value.isEmpty {
            let status = SecItemDelete(base as CFDictionary)
            if status != errSecSuccess && status != errSecItemNotFound { throw AppFailure.keychain(status) }
            return
        }
        let data = Data(value.utf8)
        let change = [kSecValueData as String: data]
        var status = SecItemUpdate(base as CFDictionary, change as CFDictionary)
        if status == errSecItemNotFound {
            var query = base
            query[kSecValueData as String] = data
            query[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
            status = SecItemAdd(query as CFDictionary, nil)
        }
        guard status == errSecSuccess else { throw AppFailure.keychain(status) }
    }
}

actor DeepL {
    struct Entry: Hashable {
        let text: String
        let source: Language
        let target: Language
    }
    private struct Response: Decodable {
        struct Value: Decodable { let text: String }
        let translations: [Value]
    }
    private let session = URLSession(configuration: .ephemeral)
    private var cache: [Entry: String] = [:]

    func clear() { cache.removeAll() }

    func translate(_ batch: [Entry], key: String) async throws -> [Entry: String] {
        guard let first = batch.first else { return [:] }
        guard !key.isEmpty else { throw AppFailure.missingKey }
        var result: [Entry: String] = [:]
        var seen: Set<Entry> = []
        let missing = batch.filter { entry in
            if let cached = cache[entry] { result[entry] = cached; return false }
            return seen.insert(entry).inserted
        }
        guard !missing.isEmpty else { return result }
        let host = key.hasSuffix(":fx") ? "api-free.deepl.com" : "api.deepl.com"
        guard let url = URL(string: "https://\(host)/v2/translate") else { throw AppFailure.response }
        var request = URLRequest(url: url, timeoutInterval: 15)
        request.httpMethod = "POST"
        request.setValue("DeepL-Auth-Key \(key)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: [
            "text": missing.map(\.text), "source_lang": first.source.source, "target_lang": first.target.target
        ])
        let (data, response) = try await session.data(for: request)
        try Task.checkCancellation()
        guard let http = response as? HTTPURLResponse else { throw AppFailure.response }
        guard http.statusCode == 200 else { throw AppFailure.service(http.statusCode) }
        let translations = try JSONDecoder().decode(Response.self, from: data).translations
        guard translations.count == missing.count else { throw AppFailure.response }
        if cache.count + missing.count > 2000 { cache.removeAll(keepingCapacity: true) }
        for (entry, value) in zip(missing, translations) {
            cache[entry] = value.text
            result[entry] = value.text
        }
        return result
    }
}

enum ScreenOCR {
    struct Line: Sendable {
        let text: String
        let rect: CGRect
        let background: String
        let color: String
    }

    // Convert Vision's bottom-left image coordinates into normalized top-left viewport coordinates.
    static func recognize(_ image: CGImage, source: Language) throws -> [Line] {
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.usesLanguageCorrection = source != .chinese
        let desired: [String] = switch source {
        case .auto: ["en-US", "ja-JP", "zh-Hans"]
        case .english: ["en-US"]
        case .japanese: ["ja-JP"]
        case .chinese: ["zh-Hans", "zh-Hant"]
        }
        let supported = try request.supportedRecognitionLanguages()
        let selected = desired.filter(supported.contains)
        if !selected.isEmpty { request.recognitionLanguages = selected }
        try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
        let palette = Palette(image)
        return (request.results ?? []).compactMap { observation in
            guard let candidate = observation.topCandidates(1).first, candidate.confidence >= 0.4 else { return nil }
            let box = observation.boundingBox
            let rect = CGRect(x: box.minX, y: 1 - box.maxY, width: box.width, height: box.height)
            let (background, foreground) = palette.colors(at: rect)
            return Line(text: candidate.string, rect: rect, background: background, color: foreground)
        }.sorted { $0.rect.minY == $1.rect.minY ? $0.rect.minX < $1.rect.minX : $0.rect.minY < $1.rect.minY }
    }

    private struct Palette {
        private static let side = 120
        private let pixels: [UInt8]
        init(_ image: CGImage) {
            let width = Self.side
            var data = [UInt8](repeating: 255, count: width * width * 4)
            data.withUnsafeMutableBytes { bytes in
                guard let context = CGContext(data: bytes.baseAddress, width: width, height: width,
                    bitsPerComponent: 8, bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
                    bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue) else { return }
                context.draw(image, in: CGRect(x: 0, y: 0, width: width, height: width))
            }
            pixels = data
        }
        func colors(at r: CGRect) -> (String, String) {
            let side = Self.side
            let x = r.midX, y = r.midY
            let points = [(r.minX - 0.012, y), (r.maxX + 0.012, y), (x, r.minY - 0.012),
                          (x, r.maxY + 0.012), (r.minX, r.maxY + 0.012)]
            var channels: [[Int]] = [[], [], []]
            for (px, py) in points {
                let col = max(0, min(side - 1, Int(px * Double(side))))
                let row = max(0, min(side - 1, Int(py * Double(side))))
                let i = (row * side + col) * 4
                for c in 0..<3 { channels[c].append(Int(pixels[i + c])) }
            }
            let rgb = channels.map { $0.sorted()[2] }
            let bg = "rgb(\(rgb[0]),\(rgb[1]),\(rgb[2]))"
            let lum = rgb[0] * 299 + rgb[1] * 587 + rgb[2] * 114
            return (bg, lum > 140_000 ? "#161616" : "#f9f9f9")
        }
    }
}
