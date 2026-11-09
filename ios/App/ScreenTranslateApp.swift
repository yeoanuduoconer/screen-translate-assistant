import SwiftUI
import WebKit

@main
@MainActor
struct ScreenTranslateApp: App {
    var body: some Scene { WindowGroup { BrowserScreen() } }
}

@MainActor
private struct BrowserScreen: View {
    @StateObject private var model = BrowserModel()
    @FocusState private var addressFocused: Bool
    @State private var choosing = false
    @State private var draft: CGRect?
    @State private var settings = false
    @State private var draftKey = ""
    @State private var error = ""

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Button { model.web.goBack() } label: { Image(systemName: "chevron.left") }
                    .disabled(!model.canGoBack).accessibilityLabel("后退")
                TextField("输入网页地址", text: $model.address)
                    .textFieldStyle(.roundedBorder)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
                    .submitLabel(.go)
                    .focused($addressFocused)
                    .onSubmit(go)
                Button(action: go) { Image(systemName: "arrow.right.circle.fill") }
                    .accessibilityLabel("打开网页")
                Menu {
                    Button("刷新网页", systemImage: "arrow.clockwise") { model.web.reload() }
                    Button("本地预览", systemImage: "play.rectangle") {
                        choosing = false
                        model.openDemo()
                    }
                    Button("语言与密钥", systemImage: "gearshape") {
                        draftKey = ""
                        error = ""
                        settings = true
                    }
                } label: { Image(systemName: "ellipsis.circle") }
                .accessibilityLabel("更多")
            }
            .padding(.horizontal, 14).padding(.vertical, 9)
            Divider()
            GeometryReader { geometry in
                ZStack(alignment: .topLeading) {
                    WebSurface(view: model.web)
                    if choosing {
                        Color.black.opacity(0.12)
                            .contentShape(Rectangle())
                            .gesture(DragGesture(minimumDistance: 5, coordinateSpace: .local)
                                .onChanged { drag in draft = box(drag, in: geometry.size) }
                                .onEnded { drag in
                                    let rectangle = box(drag, in: geometry.size)
                                    if rectangle.width >= 24 && rectangle.height >= 24 {
                                        model.updateSelection(Selection(rect: rectangle, size: geometry.size))
                                        choosing = false
                                    }
                                    draft = nil
                                })
                        let box = draft ?? model.selection.rect(in: geometry.size)
                        RoundedRectangle(cornerRadius: 4).strokeBorder(.tint, lineWidth: 2)
                            .frame(width: box.width, height: box.height)
                            .offset(x: box.minX, y: box.minY)
                            .allowsHitTesting(false)
                    }
                }
                .clipped()
            }
            Divider()
            HStack {
                Text(choosing ? "在网页上拖出翻译区域" : model.status)
                    .font(.footnote).foregroundStyle(.secondary).lineLimit(2)
                Spacer()
                if choosing {
                    Button("全页") { model.updateSelection(Selection()); choosing = false }
                    Button("取消") { draft = nil; choosing = false }
                } else {
                    Text(model.mode.label).font(.caption2).foregroundStyle(.secondary)
                }
            }
            .padding(.horizontal, 14).frame(minHeight: 28)
            HStack(spacing: 8) {
                Button { addressFocused = false; choosing.toggle() } label: {
                    Label("选区", systemImage: "viewfinder")
                }
                Spacer()
                if model.enabled {
                    Button { model.toggleOriginal() } label: {
                        Label(model.showingOriginal ? "译文" : "原文", systemImage: "text.viewfinder")
                    }
                    .keyboardShortcut("o", modifiers: [.command, .shift])
                    Button { model.stop() } label: { Label("停止", systemImage: "stop.fill") }
                        .keyboardShortcut("s", modifiers: [.command, .shift])
                } else {
                    Button { addressFocused = false; choosing = false; model.start() } label: {
                        Label("开始", systemImage: "play.fill")
                    }
                    .keyboardShortcut("t", modifiers: [.command, .shift])
                }
            }
            .buttonStyle(.bordered).padding(.horizontal, 14).padding(.bottom, 8)
        }
        .onChange(of: model.mode) { _ in model.restartIfRunning() }
        .onChange(of: model.source) { _ in model.restartIfRunning() }
        .onChange(of: model.target) { _ in model.restartIfRunning() }
        .sheet(isPresented: $settings) { settingsForm }
    }

    private var settingsForm: some View {
        NavigationStack {
            Form {
                Section("识别与翻译") {
                    Picker("识别模式", selection: $model.mode) {
                        ForEach(ScanMode.allCases) { Text($0.label).tag($0) }
                    }
                    Picker("原文语言", selection: $model.source) {
                        ForEach(Language.allCases) { Text($0.label).tag($0) }
                    }
                    Picker("目标语言", selection: $model.target) {
                        ForEach(Language.allCases.filter { $0 != .auto }) { Text($0.label).tag($0) }
                    }
                    Text("网页模式直接读页面文字。图片模式在本机截图识别，只有需要翻译的文字会发送到 DeepL。")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("DeepL") {
                    Text(model.hasKey ? "本机已保存 Key" : "还未保存 Key").foregroundStyle(.secondary)
                    SecureField("输入或更换 API Key", text: $draftKey)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    Button("保存密钥") { save(draftKey) }
                        .disabled(draftKey.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    if model.hasKey {
                        Button("清除本机密钥", role: .destructive) { save("") }
                    }
                    if !error.isEmpty { Text(error).foregroundStyle(.red) }
                }
            }
            .navigationTitle("翻译设置")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { settings = false } } }
        }
    }

    private func save(_ value: String) {
        do {
            try model.saveKey(value)
            settings = false
        } catch let failure {
            error = failure.localizedDescription
        }
    }

    private func go() {
        addressFocused = false
        choosing = false
        model.navigate()
    }

    private func box(_ drag: DragGesture.Value, in size: CGSize) -> CGRect {
        let x1 = min(size.width, max(0, drag.startLocation.x))
        let y1 = min(size.height, max(0, drag.startLocation.y))
        let x2 = min(size.width, max(0, drag.location.x))
        let y2 = min(size.height, max(0, drag.location.y))
        return CGRect(x: min(x1, x2), y: min(y1, y2), width: abs(x2 - x1), height: abs(y2 - y1))
    }
}

private struct WebSurface: UIViewRepresentable {
    let view: WKWebView
    func makeUIView(context: Context) -> WKWebView { view }
    func updateUIView(_ uiView: WKWebView, context: Context) {}
}
