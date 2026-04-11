import Foundation
import Combine
import AppKit

class ProjectManager: ObservableObject {
    @Published var projects: [Project] = []
    @Published var dashboards: [DashboardInstance] = []
    @Published var selectedTab: UUID?
    @Published var showAddProject = false
    @Published var showInstallSheet = false
    @Published var pendingProject: Project?
    let serverManager = ServerManager()

    private let storageKey = "saved_projects"
    private var outputPipes: [UUID: Pipe] = [:]
    private var errorPipes: [UUID: Pipe] = [:]

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
        // Check if server is installed
        guard serverManager.installationExists() else {
            pendingProject = instance.project
            showInstallSheet = true
            dashboards.removeAll { $0.id == instance.id }
            return
        }

        // Check for updates before launching
        Task {
            let status = await serverManager.checkForUpdates()
            await MainActor.run {
                switch status {
                case .updatesAvailable(let count):
                    showUpdateAlert(count: count, instance: instance)
                default:
                    launchProcess(for: instance)
                }
            }
        }
    }

    private func showUpdateAlert(count: Int, instance: DashboardInstance) {
        let alert = NSAlert()
        alert.messageText = "\(count) update(s) available"
        alert.informativeText = "A newer version of the dashboard server is available. Update now?"
        alert.addButton(withTitle: "Update")
        alert.addButton(withTitle: "Skip")
        alert.alertStyle = .informational

        let response = alert.runModal()
        if response == .alertFirstButtonReturn {
            Task {
                do {
                    try await serverManager.pullUpdates()
                } catch {
                    print("Update failed: \(error.localizedDescription)")
                }
                await MainActor.run {
                    launchProcess(for: instance)
                }
            }
        } else {
            launchProcess(for: instance)
        }
    }

    private func launchProcess(for instance: DashboardInstance) {
        let process = Process()
        let outputPipe = Pipe()
        let errorPipe = Pipe()

        let runShPath = serverManager.serverPath + "/run.sh"

        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [runShPath, instance.project.path]
        process.currentDirectoryURL = URL(fileURLWithPath: serverManager.serverPath)
        process.standardOutput = outputPipe
        process.standardError = errorPipe

        var env = ProcessInfo.processInfo.environment
        env["TERM"] = "xterm-256color"
        env["AGENTS_DASHBOARD_AUTO_UPDATE"] = "1"
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
