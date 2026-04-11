import SwiftUI
import WebKit

struct DashboardWebView: NSViewRepresentable {
    let url: URL

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.preferences.setValue(true, forKey: "developerExtrasEnabled")

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
        // Load blank page to tear down any remaining connections
        webView.loadHTMLString("", baseURL: nil)
    }

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    class Coordinator: NSObject, WKNavigationDelegate {
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
