import Foundation
import Combine

class ProjectManager: ObservableObject {
    @Published var projects: [Project] = []
    @Published var dashboards: [DashboardInstance] = []
    @Published var selectedTab: UUID?
    @Published var showAddProject = false

    private let storageKey = "saved_projects"
    private var outputPipes: [UUID: Pipe] = [:]
    private var errorPipes: [UUID: Pipe] = [:]

    /// Path to the dashboard repo (parent of wrappers/macos/)
    var dashboardRepoPath: String {
        // Walk up from the app bundle to find run.sh
        // In development, use a relative path; in production, use the bundled path
        if let bundlePath = Bundle.main.resourcePath,
           FileManager.default.fileExists(atPath: bundlePath + "/run.sh") {
            return bundlePath
        }

        // Try to find run.sh relative to the executable
        let execURL = Bundle.main.executableURL?.deletingLastPathComponent()
        var searchDir = execURL

        for _ in 0..<10 {
            guard let dir = searchDir else { break }
            let runSh = dir.appendingPathComponent("run.sh")
            if FileManager.default.fileExists(atPath: runSh.path) {
                return dir.path
            }
            searchDir = dir.deletingLastPathComponent()
        }

        // Fallback: check for DASHBOARD_REPO_PATH environment variable
        if let envPath = ProcessInfo.processInfo.environment["DASHBOARD_REPO_PATH"] {
            return envPath
        }

        // Last resort: derive from the known project structure
        // The app is at wrappers/macos/ relative to the dashboard repo
        let appDir = Bundle.main.bundleURL.deletingLastPathComponent()
        return appDir
            .deletingLastPathComponent() // macos
            .deletingLastPathComponent() // wrappers
            .path
    }

    init() {
        loadProjects()
    }

    // MARK: - Project Management

    func addProject(path: String) {
        let url = URL(fileURLWithPath: path)
        let name = url.lastPathComponent
        let project = Project(name: name, path: path)
        projects.append(project)
        saveProjects()
    }

    func removeProject(_ project: Project) {
        // Stop dashboard if running
        if let dashboard = dashboards.first(where: { $0.project.id == project.id }) {
            stopDashboard(id: dashboard.id)
        }
        projects.removeAll { $0.id == project.id }
        saveProjects()
    }

    func isProjectRunning(_ project: Project) -> Bool {
        dashboards.contains { $0.project.id == project.id && $0.status != .stopped && $0.status != .error }
    }

    func dashboardFor(project: Project) -> DashboardInstance? {
        dashboards.first { $0.project.id == project.id }
    }

    // MARK: - Dashboard Lifecycle

    func startDashboard(for project: Project) {
        // Don't start if already running
        guard !isProjectRunning(project) else { return }

        let instance = DashboardInstance(
            id: UUID(),
            project: project,
            status: .starting,
            port: nil,
            process: nil
        )

        dashboards.append(instance)
        selectedTab = instance.id

        launchServer(for: instance)
    }

    func stopDashboard(id: UUID) {
        guard let index = dashboards.firstIndex(where: { $0.id == id }) else { return }

        dashboards[index].status = .stopping

        if let process = dashboards[index].process, process.isRunning {
            // Send SIGTERM for graceful shutdown
            process.terminate()

            // Force kill after 5 seconds if still running
            DispatchQueue.global().asyncAfter(deadline: .now() + 5) { [weak self] in
                if process.isRunning {
                    process.interrupt()
                }
                DispatchQueue.main.async {
                    self?.cleanupDashboard(id: id)
                }
            }
        } else {
            cleanupDashboard(id: id)
        }
    }

    func removeDashboard(id: UUID) {
        stopDashboard(id: id)

        // If tab was selected, switch to another
        if selectedTab == id {
            selectedTab = dashboards.first(where: { $0.id != id })?.id
        }

        dashboards.removeAll { $0.id == id }
        outputPipes.removeValue(forKey: id)
        errorPipes.removeValue(forKey: id)
    }

    // MARK: - Server Process

    private func launchServer(for instance: DashboardInstance) {
        let process = Process()
        let outputPipe = Pipe()
        let errorPipe = Pipe()

        let runShPath = dashboardRepoPath + "/run.sh"

        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [runShPath, instance.project.path]
        process.currentDirectoryURL = URL(fileURLWithPath: dashboardRepoPath)
        process.standardOutput = outputPipe
        process.standardError = errorPipe

        // Set environment to ensure proper terminal behavior
        var env = ProcessInfo.processInfo.environment
        env["TERM"] = "xterm-256color"
        process.environment = env

        self.outputPipes[instance.id] = outputPipe
        self.errorPipes[instance.id] = errorPipe

        // Shared handler: appends output to log and detects the server URL
        let handleOutput: (Pipe) -> Void = { pipe in
            pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
                let data = handle.availableData
                guard !data.isEmpty, let output = String(data: data, encoding: .utf8) else { return }

                DispatchQueue.main.async {
                    guard let self = self,
                          let index = self.dashboards.firstIndex(where: { $0.id == instance.id }) else { return }

                    self.dashboards[index].outputLog += output

                    // Detect "Uvicorn running on http://127.0.0.1:XXXX" (stderr)
                    // or "Starting on: http://127.0.0.1:XXXX" (stdout)
                    if self.dashboards[index].port == nil,
                       let range = output.range(of: #"http://[\d.]+:(\d+)"#, options: .regularExpression) {
                        let urlStr = String(output[range])
                        if let url = URL(string: urlStr),
                           let portStr = url.port {
                            self.dashboards[index].port = portStr
                            self.dashboards[index].status = .running
                        }
                    }
                }
            }
        }

        // Monitor both stdout and stderr for server URL and log output
        handleOutput(outputPipe)
        handleOutput(errorPipe)

        process.terminationHandler = { [weak self] proc in
            DispatchQueue.main.async {
                guard let self = self,
                      let index = self.dashboards.firstIndex(where: { $0.id == instance.id }) else { return }

                if self.dashboards[index].status != .stopping {
                    self.dashboards[index].status = .error
                    self.dashboards[index].errorMessage = "Process exited with code \(proc.terminationStatus)"
                } else {
                    self.dashboards[index].status = .stopped
                }
                self.dashboards[index].process = nil
            }
        }

        do {
            try process.run()
            if let index = dashboards.firstIndex(where: { $0.id == instance.id }) {
                dashboards[index].process = process
            }
        } catch {
            if let index = dashboards.firstIndex(where: { $0.id == instance.id }) {
                dashboards[index].status = .error
                dashboards[index].errorMessage = error.localizedDescription
            }
        }
    }

    private func cleanupDashboard(id: UUID) {
        guard let index = dashboards.firstIndex(where: { $0.id == id }) else { return }
        dashboards[index].status = .stopped
        dashboards[index].process = nil
        outputPipes[id]?.fileHandleForReading.readabilityHandler = nil
        errorPipes[id]?.fileHandleForReading.readabilityHandler = nil
    }

    // MARK: - Persistence

    private func saveProjects() {
        if let data = try? JSONEncoder().encode(projects) {
            UserDefaults.standard.set(data, forKey: storageKey)
        }
    }

    private func loadProjects() {
        guard let data = UserDefaults.standard.data(forKey: storageKey),
              let saved = try? JSONDecoder().decode([Project].self, from: data) else { return }
        projects = saved
    }
}
