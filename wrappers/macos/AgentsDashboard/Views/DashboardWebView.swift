import SwiftUI
import WebKit
import IOKit.pwr_mgt

struct DashboardWebView: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")
        config.userContentController.add(context.coordinator, name: "wakeLock")

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        // Only reload if URL changed
        if webView.url != url {
            webView.load(URLRequest(url: url))
        }
    }

    static func dismantleNSView(_ webView: WKWebView, coordinator: Coordinator) {
        // Close WebSocket and stop all network activity before the view is deallocated.
        // Without this, closed wrapper tabs leave unbound connections on the server.
        webView.evaluateJavaScript(
            "if (typeof App !== 'undefined' && App.cleanup) { App.cleanup(); }",
            completionHandler: nil
        )
        webView.stopLoading()
        webView.navigationDelegate = nil
        webView.configuration.userContentController.removeScriptMessageHandler(forName: "wakeLock")
        coordinator.releaseWakeLock()
        // Load blank page to tear down any remaining connections
        webView.loadHTMLString("", baseURL: nil)
    }

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    class Coordinator: NSObject, WKNavigationDelegate, WKScriptMessageHandler {
        private var powerAssertionID: IOPMAssertionID = 0
        private var assertionHeld = false

        func acquireWakeLock() {
            guard !assertionHeld else { return }
            let success = IOPMAssertionCreateWithName(
                "AgentsDashboard agents running" as CFString,
                IOPMAssertionLevel(kIOPMAssertionLevelOn),
                "Preventing sleep while agents are running" as CFString,
                &powerAssertionID
            )
            if success == kIOReturnSuccess {
                assertionHeld = true
            }
        }

        func releaseWakeLock() {
            guard assertionHeld else { return }
            IOPMAssertionRelease(powerAssertionID)
            assertionHeld = false
        }

        // MARK: - WKScriptMessageHandler

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == "wakeLock", let action = message.body as? String else { return }
            if action == "acquire" {
                acquireWakeLock()
            } else if action == "release" {
                releaseWakeLock()
            }
        }

        // MARK: - WKNavigationDelegate

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            print("WebView navigation failed: \(error.localizedDescription)")
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            // Server might not be ready yet, retry after a short delay
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.0) {
                if let url = webView.url ?? URL(string: error.localizedDescription) {
                    webView.load(URLRequest(url: url))
                }
            }
        }
    }
}
