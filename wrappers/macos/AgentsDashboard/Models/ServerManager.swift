import Foundation

enum UpdateStatus {
    case upToDate
    case updatesAvailable(Int)
    case error(String)
}

enum InstallStage {
    case cloning
    case creatingVenv
    case installingDeps
    case done
}

class ServerManager: ObservableObject {
    @Published var installStage: InstallStage?
    @Published var installError: String?

    static let repoURL = "https://github.com/epatel/claude-agents-dashboard.git"

    var serverPath: String {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".agents-dashboard")
            .path
    }

    func installationExists() -> Bool {
        let runSh = (serverPath as NSString).appendingPathComponent("run.sh")
        return FileManager.default.fileExists(atPath: runSh)
    }

    func clone() async throws {
        await MainActor.run { installStage = .cloning; installError = nil }

        // Clone repo
        try runProcess("/usr/bin/git", arguments: ["clone", Self.repoURL, serverPath])

        // Create venv
        await MainActor.run { installStage = .creatingVenv }
        let venvPath = (serverPath as NSString).appendingPathComponent("venv")
        try runProcess("/usr/bin/python3", arguments: ["-m", "venv", venvPath])

        // Install dependencies
        await MainActor.run { installStage = .installingDeps }
        let pipPath = (venvPath as NSString).appendingPathComponent("bin/pip")
        let reqPath = (serverPath as NSString).appendingPathComponent("requirements.txt")
        try runProcess(pipPath, arguments: ["install", "-q", "-r", reqPath])

        await MainActor.run { installStage = .done }
    }

    private func runProcess(_ executablePath: String, arguments: [String]) throws {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executablePath)
        process.arguments = arguments

        let errorPipe = Pipe()
        process.standardError = errorPipe
        process.standardOutput = FileHandle.nullDevice

        try process.run()
        process.waitUntilExit()

        if process.terminationStatus != 0 {
            let errorData = errorPipe.fileHandleForReading.readDataToEndOfFile()
            let errorMsg = String(data: errorData, encoding: .utf8) ?? "Unknown error"
            throw NSError(
                domain: "ServerManager",
                code: Int(process.terminationStatus),
                userInfo: [NSLocalizedDescriptionKey: errorMsg]
            )
        }
    }

    func checkForUpdates() async -> UpdateStatus {
        guard installationExists() else { return .error("Not installed") }

        // Fetch
        do {
            try runProcess("/usr/bin/git", arguments: ["-C", serverPath, "fetch", "--quiet"])
        } catch {
            return .error("Fetch failed: \(error.localizedDescription)")
        }

        // Compare HEAD vs @{u}
        do {
            let local = try runProcessOutput("/usr/bin/git", arguments: ["-C", serverPath, "rev-parse", "HEAD"])
            let remote = try runProcessOutput("/usr/bin/git", arguments: ["-C", serverPath, "rev-parse", "@{u}"])

            if local.trimmingCharacters(in: .whitespacesAndNewlines)
                == remote.trimmingCharacters(in: .whitespacesAndNewlines) {
                return .upToDate
            }

            let behindStr = try runProcessOutput(
                "/usr/bin/git",
                arguments: ["-C", serverPath, "rev-list", "--count", "HEAD..@{u}"]
            )
            let behind = Int(behindStr.trimmingCharacters(in: .whitespacesAndNewlines)) ?? 0
            return behind > 0 ? .updatesAvailable(behind) : .upToDate
        } catch {
            return .error(error.localizedDescription)
        }
    }

    func pullUpdates() async throws {
        try runProcess("/usr/bin/git", arguments: ["-C", serverPath, "pull", "--quiet"])
    }

    private func runProcessOutput(_ executablePath: String, arguments: [String]) throws -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executablePath)
        process.arguments = arguments

        let outputPipe = Pipe()
        process.standardOutput = outputPipe
        process.standardError = FileHandle.nullDevice

        try process.run()
        process.waitUntilExit()

        if process.terminationStatus != 0 {
            throw NSError(
                domain: "ServerManager",
                code: Int(process.terminationStatus),
                userInfo: [NSLocalizedDescriptionKey: "Command failed with status \(process.terminationStatus)"]
            )
        }

        let data = outputPipe.fileHandleForReading.readDataToEndOfFile()
        return String(data: data, encoding: .utf8) ?? ""
    }
}
