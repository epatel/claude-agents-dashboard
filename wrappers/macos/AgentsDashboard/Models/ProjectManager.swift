import Foundation
import Combine
import AppKit

class ProjectManager: ObservableObject {
    @Published var projects: [Project] = []
    @Published var dashboards: [DashboardInstance] = []
    @Published var selectedTab: UUID?
    @Published var showAddProject = false
    @Published var showCreateProject = false
    @Published var showInstallSheet = false
    @Published var pendingProject: Project?
    /// Projects whose database file is missing (path/agents-lab/dashboard.db).
    @Published var unavailableProjectIDs: Set<UUID> = []
    let serverManager = ServerManager()

    private let storageKey = "saved_projects"
    private var outputPipes: [UUID: Pipe] = [:]
    private var errorPipes: [UUID: Pipe] = [:]
    /// Poll timer that periodically refreshes the per-tab questions/reviews counts.
    /// Started lazily when the first dashboard begins running.
    private var badgePollTimer: Timer?
    /// The user's full login-shell PATH, resolved once on first access.
    /// Exposed so that views (InstallSheet, ContentView) can pass it to checkClaudeCLI.
    lazy var resolvedUserPATH: String? = {
        // macOS GUI apps get a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin).
        // Spawn the user's login shell to get the fully-resolved PATH that
        // includes homebrew, nvm, rbenv, etc.
        let userShell = ProcessInfo.processInfo.environment["SHELL"] ?? "/bin/zsh"
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: userShell)
        proc.arguments = ["-l", "-c", "echo $PATH"]
        let pipe = Pipe()
        proc.standardOutput = pipe
        proc.standardError = FileHandle.nullDevice
        do {
            try proc.run()
            proc.waitUntilExit()
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let path = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines)
            return (path?.isEmpty == false) ? path : nil
        } catch {
            return nil
        }
    }()

    init() {
        loadProjects()
        checkProjectAvailability()
        startBadgePollTimer()
    }

    deinit {
        badgePollTimer?.invalidate()
    }

    // MARK: - Tab Badge Polling

    /// Start (or restart) the timer that refreshes per-tab badge counts.
    /// Polling is light: a single GET /api/items per running dashboard every
    /// 3 seconds. We only fetch column_name client-side and count locally.
    private func startBadgePollTimer() {
        badgePollTimer?.invalidate()
        let timer = Timer(timeInterval: 3.0, repeats: true) { [weak self] _ in
            self?.refreshBadgeCounts()
        }
        // Keep firing while menus / modal panels are up.
        RunLoop.main.add(timer, forMode: .common)
        badgePollTimer = timer
        // Also kick off an immediate refresh so tabs don't sit at 0 for 3s.
        refreshBadgeCounts()
    }

    private func refreshBadgeCounts() {
        for dashboard in dashboards where dashboard.status == .running {
            guard let port = dashboard.port,
                  let url = URL(string: "http://127.0.0.1:\(port)/api/items") else { continue }
            fetchBadgeCounts(from: url, for: dashboard.id)
        }
    }

    /// GET the dashboard's items and store its questions / review counts on its tab.
    private func fetchBadgeCounts(from url: URL, for dashboardId: UUID) {
        var request = URLRequest(url: url)
        request.timeoutInterval = 4
        URLSession.shared.dataTask(with: request) { [weak self] data, _, _ in
            guard let self = self,
                  let data = data,
                  let items = try? JSONSerialization.jsonObject(with: data) as? [[String: Any]] else { return }
            let counts = ProjectManager.badgeCounts(in: items)
            DispatchQueue.main.async {
                self.applyBadgeCounts(counts, to: dashboardId)
            }
        }.resume()
    }

    /// How many items sit in the "questions" and "review" columns.
    static func badgeCounts(in items: [[String: Any]]) -> (questions: Int, reviews: Int) {
        var questions = 0
        var reviews = 0
        for item in items {
            guard let column = item["column_name"] as? String else { continue }
            if column == "questions" { questions += 1 }
            else if column == "review" { reviews += 1 }
        }
        return (questions, reviews)
    }

    /// Store new badge counts on a tab, touching only the values that changed.
    private func applyBadgeCounts(_ counts: (questions: Int, reviews: Int), to dashboardId: UUID) {
        guard let index = dashboards.firstIndex(where: { $0.id == dashboardId }) else { return }
        if dashboards[index].questionsCount != counts.questions {
            dashboards[index].questionsCount = counts.questions
        }
        if dashboards[index].reviewsCount != counts.reviews {
            dashboards[index].reviewsCount = counts.reviews
        }
    }

    // MARK: - Availability

    /// Check which projects have an existing database file.
    /// A project is "available" if `<path>/agents-lab/dashboard.db` exists.
    func checkProjectAvailability() {
        var missing = Set<UUID>()
        let fm = FileManager.default
        for project in projects {
            let dbPath = (project.path as NSString).appendingPathComponent("agents-lab/dashboard.db")
            if !fm.fileExists(atPath: dbPath) {
                missing.insert(project.id)
            }
        }
        unavailableProjectIDs = missing
    }

    func isProjectAvailable(_ project: Project) -> Bool {
        !unavailableProjectIDs.contains(project.id)
    }

    // MARK: - Project Management

    func addProject(path: String) {
        let url = URL(fileURLWithPath: path)
        let name = url.lastPathComponent
        let project = Project(name: name, path: path)
        projects.append(project)
        saveProjects()
    }

    /// Toggle the per-entry experimental flag (`--experimental`, enables the
    /// Ollama UI and Kimi models).
    /// Persists the change and keeps any open dashboard tab's project snapshot in
    /// sync so a later restart launches with the new flag. Takes effect on next
    /// (re)start — it does not restart a running dashboard.
    func setExperimental(_ enabled: Bool, for project: Project) {
        guard let i = projects.firstIndex(where: { $0.id == project.id }) else { return }
        projects[i].experimental = enabled
        saveProjects()
        if let d = dashboards.firstIndex(where: { $0.project.id == project.id }) {
            let old = dashboards[d]
            dashboards[d] = DashboardInstance(
                id: old.id,
                project: projects[i],
                status: old.status,
                port: old.port,
                process: old.process,
                outputLog: old.outputLog,
                errorMessage: old.errorMessage,
                questionsCount: old.questionsCount,
                reviewsCount: old.reviewsCount
            )
        }
    }

    func moveProjects(from source: IndexSet, to destination: Int) {
        projects.move(fromOffsets: source, toOffset: destination)
        saveProjects()
    }

    /// Called by the prototype reorder view after it mutates `projects`
    /// directly via a binding. Persists the new order without changing it.
    func persistAfterReorder() {
        saveProjects()
    }

    func removeProject(_ project: Project) {
        // Remove dashboard (stops process and removes tab)
        if let dashboard = dashboards.first(where: { $0.project.id == project.id }) {
            removeDashboard(id: dashboard.id)
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

        // Reuse existing stopped/error dashboard tab if present
        if let existingIndex = dashboards.firstIndex(where: { $0.project.id == project.id }) {
            dashboards[existingIndex].status = .starting
            dashboards[existingIndex].port = nil
            dashboards[existingIndex].errorMessage = nil
            dashboards[existingIndex].outputLog = ""
            dashboards[existingIndex].questionsCount = 0
            dashboards[existingIndex].reviewsCount = 0
            selectedTab = dashboards[existingIndex].id
            launchServer(for: dashboards[existingIndex])
            return
        }

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

        guard let process = dashboards[index].process, process.isRunning else {
            cleanupDashboard(id: id)
            return
        }
        // Call the shutdown endpoint first so the server can gracefully
        // clean up all Claude agent sessions (child + grandchild processes).
        // pkill -P only kills direct children, so the HTTP endpoint is needed
        // to properly tear down SDK-spawned agent process trees.
        if let port = dashboards[index].port {
            callShutdownEndpoint(port: port) { [weak self] in
                // Whether the endpoint succeeded or not, terminate the process
                if process.isRunning {
                    process.terminate()
                }
                ProjectManager.interruptLaterThenCleanup(process, id: id, manager: self)
            }
        } else {
            // No port known — fall back to direct termination
            process.terminate()
            ProjectManager.interruptLaterThenCleanup(process, id: id, manager: self)
        }
    }

    /// Force-stop the process after 5 seconds if it is still running, then mark the tab stopped.
    private static func interruptLaterThenCleanup(_ process: Process, id: UUID, manager: ProjectManager?) {
        DispatchQueue.global().asyncAfter(deadline: .now() + 5) { [weak manager] in
            if process.isRunning {
                process.interrupt()
            }
            DispatchQueue.main.async {
                manager?.cleanupDashboard(id: id)
            }
        }
    }

    /// Call the server's /api/shutdown endpoint to gracefully stop all agents.
    /// Calls the completion handler when done (success or failure, with a short timeout).
    private func callShutdownEndpoint(port: Int, completion: @escaping () -> Void) {
        guard let url = URL(string: "http://127.0.0.1:\(port)/api/shutdown") else {
            completion()
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 5  // Don't wait too long

        URLSession.shared.dataTask(with: request) { _, _, _ in
            // Give the server a moment to finish cleanup before we terminate
            DispatchQueue.global().asyncAfter(deadline: .now() + 1) {
                completion()
            }
        }.resume()
    }

    func stopAllDashboards() {
        // Call shutdown endpoint on all running dashboards synchronously.
        // Used during app termination to ensure Claude agents are cleaned up.
        let running = dashboards.filter { $0.status == .running && $0.port != nil }
        let semaphore = DispatchSemaphore(value: 0)

        for dashboard in running {
            guard let port = dashboard.port,
                  let url = URL(string: "http://127.0.0.1:\(port)/api/shutdown") else { continue }
            postShutdown(to: url, signalling: semaphore)
            // Wait up to 3 seconds per server
            _ = semaphore.wait(timeout: .now() + 3)
        }

        // Now terminate all processes
        for case let process? in dashboards.map(\.process) where process.isRunning {
            process.terminate()
        }
    }

    /// POST /api/shutdown (3 s timeout) and signal ``semaphore`` when the request finishes.
    private func postShutdown(to url: URL, signalling semaphore: DispatchSemaphore) {
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = 3

        URLSession.shared.dataTask(with: request) { _, _, _ in
            semaphore.signal()
        }.resume()
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

        // Check Claude CLI prerequisites, then check for updates
        Task {
            let cliStatus = await serverManager.checkClaudeCLI(userPATH: resolvedUserPATH)
            await MainActor.run {
                guard cliStatus.isReady else {
                    pendingProject = instance.project
                    showInstallSheet = true
                    dashboards.removeAll { $0.id == instance.id }
                    return
                }
            }

            // Check for wrapper (app) updates via GitHub releases
            let wrapperStatus = await serverManager.checkForWrapperUpdate()
            await MainActor.run {
                if case .updateAvailable(let current, let latest) = wrapperStatus {
                    self.showWrapperUpdateAlert(current: current, latest: latest)
                }
            }

            // Check for server (git repo) updates
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

    private func showWrapperUpdateAlert(current: String, latest: String) {
        let confirmed = runInformationalAlert(
            message: "New version available",
            info: "Agents Dashboard v\(latest) is available (you have v\(current)). Visit GitHub to download the update.",
            confirm: "Open GitHub", cancel: "Later"
        )
        if confirmed {
            NSWorkspace.shared.open(ServerManager.releasesLatestURL)
        }
    }

    private func showUpdateAlert(count: Int, instance: DashboardInstance) {
        let confirmed = runInformationalAlert(
            message: "\(count) update(s) available",
            info: "A newer version of the dashboard server is available. Update now?",
            confirm: "Update", cancel: "Skip"
        )
        if confirmed {
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

    /// Show a modal informational alert with two buttons; true when the first (``confirm``) is chosen.
    private func runInformationalAlert(message: String, info: String, confirm: String, cancel: String) -> Bool {
        let alert = NSAlert()
        alert.messageText = message
        alert.informativeText = info
        alert.addButton(withTitle: confirm)
        alert.addButton(withTitle: cancel)
        alert.alertStyle = .informational
        return alert.runModal() == .alertFirstButtonReturn
    }

    private func launchProcess(for instance: DashboardInstance) {
        let id = instance.id
        let process = makeServerProcess(for: instance.project)
        let outputPipe = Pipe()
        let errorPipe = Pipe()
        process.standardOutput = outputPipe
        process.standardError = errorPipe

        self.outputPipes[id] = outputPipe
        self.errorPipes[id] = errorPipe

        readServerOutput(from: outputPipe, for: id)
        readServerOutput(from: errorPipe, for: id)

        process.terminationHandler = { [weak self] proc in
            // Detach pipe readers immediately on exit — the readabilityHandler
            // EOF guard already handles this, but cleaning up here too means
            // we don't rely on dispatch firing one more time to notice.
            outputPipe.fileHandleForReading.readabilityHandler = nil
            errorPipe.fileHandleForReading.readabilityHandler = nil

            DispatchQueue.main.async {
                self?.serverProcessExited(proc, for: id)
            }
        }

        do {
            try process.run()
            if let index = dashboards.firstIndex(where: { $0.id == id }) {
                dashboards[index].process = process
            }
        } catch {
            if let index = dashboards.firstIndex(where: { $0.id == id }) {
                dashboards[index].status = .error
                dashboards[index].errorMessage = error.localizedDescription
            }
        }
    }

    /// `bash run.sh <project> [--experimental]` in the server checkout, with the user's full PATH.
    private func makeServerProcess(for project: Project) -> Process {
        let process = Process()
        let runShPath = serverManager.serverPath + "/run.sh"

        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        var arguments = [runShPath, project.path]
        if project.experimental {
            arguments.append("--experimental")
        }
        process.arguments = arguments
        process.currentDirectoryURL = URL(fileURLWithPath: serverManager.serverPath)

        var env = ProcessInfo.processInfo.environment
        env["TERM"] = "xterm-256color"
        env["AGENTS_DASHBOARD_AUTO_UPDATE"] = "1"
        // Use the fully-resolved user PATH so spawned processes (Claude agents,
        // MCP servers) can find node, npx, etc.
        if let fullPATH = resolvedUserPATH {
            env["PATH"] = fullPATH
        }
        process.environment = env
        return process
    }

    /// Append everything the server writes on ``pipe`` to the tab's log (on the main queue).
    private func readServerOutput(from pipe: Pipe, for id: UUID) {
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            // EOF: child process closed the pipe. Detach so dispatch stops
            // re-firing on a perpetually-readable dead fd (otherwise the
            // wrapper pegs ~400% CPU after the server exits).
            if data.isEmpty {
                handle.readabilityHandler = nil
                return
            }
            guard let output = String(data: data, encoding: .utf8) else { return }

            DispatchQueue.main.async {
                self?.appendServerOutput(output, for: id)
            }
        }
    }

    /// Add ``output`` to the tab's log; the first server URL seen marks it running on that port.
    private func appendServerOutput(_ output: String, for id: UUID) {
        guard let index = dashboards.firstIndex(where: { $0.id == id }) else { return }

        dashboards[index].outputLog += output

        if dashboards[index].port == nil, let port = ProjectManager.serverPort(in: output) {
            dashboards[index].port = port
            dashboards[index].status = .running
        }
    }

    /// The port of the first `http://<ip>:<port>` URL in ``output``, if any.
    static func serverPort(in output: String) -> Int? {
        guard let range = output.range(of: #"http://[\d.]+:(\d+)"#, options: .regularExpression) else { return nil }
        return URL(string: String(output[range]))?.port
    }

    /// The server process ended: an error unless the user was stopping it.
    private func serverProcessExited(_ proc: Process, for id: UUID) {
        guard let index = dashboards.firstIndex(where: { $0.id == id }) else { return }

        // If a new process has already been launched (dashboard restarted),
        // don't let the old process's termination corrupt the new state.
        if let currentProcess = dashboards[index].process, currentProcess !== proc {
            return
        }

        if dashboards[index].status != .stopping {
            dashboards[index].status = .error
            dashboards[index].errorMessage = "Process exited with code \(proc.terminationStatus)"
        } else {
            dashboards[index].status = .stopped
        }
        dashboards[index].process = nil
    }

    private func cleanupDashboard(id: UUID) {
        guard let index = dashboards.firstIndex(where: { $0.id == id }),
              dashboards[index].status == .stopping else { return }
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
