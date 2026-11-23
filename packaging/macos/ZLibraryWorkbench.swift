import AppKit
import Darwin
import WebKit

private let appName = "书库工作台"

private func availablePort() -> Int? {
    let descriptor = socket(AF_INET, SOCK_STREAM, 0)
    guard descriptor >= 0 else { return nil }
    defer { close(descriptor) }
    var address = sockaddr_in()
    address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
    address.sin_family = sa_family_t(AF_INET)
    address.sin_addr = in_addr(s_addr: in_addr_t(0x0100007f))
    let bound = withUnsafePointer(to: &address) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            bind(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
        }
    }
    guard bound == 0 else { return nil }
    var length = socklen_t(MemoryLayout<sockaddr_in>.size)
    let found = withUnsafeMutablePointer(to: &address) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) {
            getsockname(descriptor, $0, &length)
        }
    }
    return found == 0 ? Int(UInt16(bigEndian: address.sin_port)) : nil
}

final class WorkbenchApp: NSObject, NSApplicationDelegate, WKNavigationDelegate {
    private var window: NSWindow!
    private var webView: WKWebView!
    private var server: Process?
    private var port = 0
    private var attempts = 0
    private var isQuitting = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        let menu = NSMenu()
        let appMenu = NSMenu()
        appMenu.addItem(withTitle: "退出书库工作台", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        let root = NSMenuItem()
        root.submenu = appMenu
        menu.addItem(root)
        let editMenu = NSMenu(title: "编辑")
        for (title, action, key) in [
            ("撤销", "undo:", "z"),
            ("重做", "redo:", "Z"),
            ("剪切", "cut:", "x"),
            ("复制", "copy:", "c"),
            ("粘贴", "paste:", "v"),
            ("全选", "selectAll:", "a"),
        ] {
            editMenu.addItem(withTitle: title, action: Selector((action)), keyEquivalent: key)
        }
        let editRoot = NSMenuItem()
        editRoot.submenu = editMenu
        menu.addItem(editRoot)
        let viewMenu = NSMenu(title: "显示")
        let reload = viewMenu.addItem(withTitle: "刷新", action: #selector(reloadPage), keyEquivalent: "r")
        reload.target = self
        let viewRoot = NSMenuItem()
        viewRoot.submenu = viewMenu
        menu.addItem(viewRoot)
        NSApp.mainMenu = menu

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1180, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = appName
        window.center()
        window.minSize = NSSize(width: 720, height: 560)
        webView = WKWebView(frame: window.contentView!.bounds)
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = self
        window.contentView = webView
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        guard let chosenPort = availablePort(),
              let resources = Bundle.main.resourceURL else {
            showError("无法分配本机服务端口。")
            return
        }
        port = chosenPort
        let python = resources.appendingPathComponent("python/bin/python3.14")
        guard FileManager.default.isExecutableFile(atPath: python.path) else {
            showError("应用包缺少 Python 运行时，请重新下载完整应用。")
            return
        }
        let process = Process()
        process.executableURL = python
        process.arguments = ["-m", "zlibrary_workbench.cli", "serve-gui", "--port", String(port)]
        var environment = ProcessInfo.processInfo.environment
        environment.removeValue(forKey: "PYTHONPATH")
        environment.removeValue(forKey: "PYTHONSTARTUP")
        environment.removeValue(forKey: "PYTHONUSERBASE")
        environment["PYTHONHOME"] = resources.appendingPathComponent("python").path
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["NO_PROXY"] = "127.0.0.1,localhost,::1"
        environment["no_proxy"] = "127.0.0.1,localhost,::1"
        process.environment = environment
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let self, !self.isQuitting, self.window.isVisible else { return }
                self.showError("本机服务意外退出，请重新打开应用。")
            }
        }
        do {
            try process.run()
            server = process
            checkServer()
        } catch {
            showError("无法启动本机服务：\(error.localizedDescription)")
        }
    }

    private func checkServer() {
        guard let url = URL(string: "http://127.0.0.1:\(port)/health") else { return }
        URLSession.shared.dataTask(with: url) { [weak self] _, response, _ in
            DispatchQueue.main.async {
                guard let self else { return }
                if (response as? HTTPURLResponse)?.statusCode == 200 {
                    self.webView.load(URLRequest(url: URL(string: "http://127.0.0.1:\(self.port)/")!))
                } else if self.attempts < 100 && self.server?.isRunning == true {
                    self.attempts += 1
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self.checkServer() }
                } else {
                    self.showError("本机服务启动失败，请检查应用包是否完整。")
                }
            }
        }.resume()
    }

    private func showError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = appName
        alert.informativeText = message
        alert.alertStyle = .warning
        alert.runModal()
    }

    @objc private func reloadPage() { webView.reload() }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        if url.host == "127.0.0.1" && url.port == port {
            decisionHandler(.allow)
        } else {
            NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationWillTerminate(_ notification: Notification) {
        isQuitting = true
        if server?.isRunning == true { server?.terminate() }
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.regular)
let delegate = WorkbenchApp()
app.delegate = delegate
app.run()
