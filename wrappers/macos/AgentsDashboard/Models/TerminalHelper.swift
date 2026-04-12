import Foundation

enum TerminalHelper {
    static func open(path: String) {
        let iTermPath = "/Applications/iTerm.app"
        let app = FileManager.default.fileExists(atPath: iTermPath) ? iTermPath : "/System/Applications/Utilities/Terminal.app"
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        proc.arguments = ["-a", app, path]
        try? proc.run()
    }
}
