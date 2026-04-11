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

    var serverURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".agents-dashboard")
    }

    var serverPath: String { serverURL.path }

    func installationExists() -> Bool {
        let runSh = serverURL.appendingPathComponent("run.sh").path
        return FileManager.default.fileExists(atPath: runSh)
    }

    func clone() async throws {
        await MainActor.run { installStage = .cloning; installError = nil }

        var cloned = false
        do {
            // Clone repo
            try await runProcessBackground("/usr/bin/git", arguments: ["clone", Self.repoURL, serverPath])
            cloned = true

            // Create venv
            await MainActor.run { installStage = .creatingVenv }
            let venvPath = serverURL.appendingPathComponent("venv").path
            try await runProcessBackground("/usr/bin/python3", arguments: ["-m", "venv", venvPath])

            // Install dependencies
            await MainActor.run { installStage = .installingDeps }
            let pipPath = serverURL.appendingPathComponent("venv/bin/pip").path
            let reqPath = serverURL.appendingPathComponent("requirements.txt").path
            try await runProcessBackground(pipPath, arguments: ["install", "-q", "-r", reqPath])

            await MainActor.run { installStage = .done }
        } catch {
            // Clean up partial clone so a retry can start fresh
            if cloned {
                try? FileManager.default.removeItem(at: serverURL)
            }
            await MainActor.run { installError = error.localizedDescription }
            throw error
        }
    }

    func checkForUpdates() async -> UpdateStatus {
        guard installationExists() else { return .error("Not installed") }

        // Fetch
        do {
            try await runProcessBackground("/usr/bin/git", arguments: ["-C", serverPath, "fetch", "--quiet"])
        } catch {
            return .error("Fetch failed: \(error.localizedDescription)")
        }

        // Compare HEAD vs @{u}
        do {
            let local = try await runProcessBackground("/usr/bin/git", arguments: ["-C", serverPath, "rev-parse", "HEAD"])
            let remote = try await runProcessBackground("/usr/bin/git", arguments: ["-C", serverPath, "rev-parse", "@{u}"])

            if local.trimmingCharacters(in: .whitespacesAndNewlines)
                == remote.trimmingCharacters(in: .whitespacesAndNewlines) {
                return .upToDate
            }

            let behindStr = try await runProcessBackground(
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
        try await runProcessBackground("/usr/bin/git", arguments: ["-C", serverPath, "pull", "--quiet"])
    }

    /// Runs a process on a background thread and returns its stdout output.
    /// Throws if the process exits with a non-zero status.
    @discardableResult
    private func runProcessBackground(_ executablePath: String, arguments: [String]) async throws -> String {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .userInitiated).async {
                do {
                    let output = try self.runProcess(executablePath, arguments: arguments)
                    continuation.resume(returning: output)
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    /// Synchronous process runner — always captures stdout and returns it.
    /// Must only be called from a background thread (never from MainActor).
    @discardableResult
    private func runProcess(_ executablePath: String, arguments: [String]) throws -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executablePath)
        process.arguments = arguments

        let outputPipe = Pipe()
        let errorPipe = Pipe()
        process.standardOutput = outputPipe
        process.standardError = errorPipe

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

        let data = outputPipe.fileHandleForReading.readDataToEndOfFile()
        return String(data: data, encoding: .utf8) ?? ""
    }
}
