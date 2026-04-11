# Server Installation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The macOS app manages a local clone of the dashboard repo at `~/.agents-dashboard/`, with install and update dialogs.

**Architecture:** New `ServerManager` class owns git/venv lifecycle. `ProjectManager` delegates to it before launching `run.sh`. A sheet handles first-time install with progress. `run.sh` gains an env var guard to skip its interactive prompt.

**Tech Stack:** Swift/SwiftUI, Process/Pipe for git/python commands, async/await

**Spec:** `docs/superpowers/specs/2026-04-11-server-installation-design.md`

---

### File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `AgentsDashboard/Models/ServerManager.swift` | Create | Git clone, venv setup, update checks, pull |
| `AgentsDashboard/Views/InstallSheet.swift` | Create | First-time install dialog with progress |
| `AgentsDashboard/Models/ProjectManager.swift` | Modify | Remove `dashboardRepoPath`, integrate `ServerManager` |
| `AgentsDashboard/Views/ContentView.swift` | Modify | Add install sheet binding |
| `../../run.sh` | Modify | Guard interactive block with env var |

---

### Task 1: Create ServerManager

**Files:**
- Create: `AgentsDashboard/Models/ServerManager.swift`

- [ ] **Step 1: Create ServerManager with path and existence check**

```swift
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
}
```

- [ ] **Step 2: Add clone method**

Add to `ServerManager`:

```swift
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
```

- [ ] **Step 3: Add update check and pull methods**

Add to `ServerManager`:

```swift
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
```

- [ ] **Step 4: Verify it compiles**

Run: `cd /Users/epatel/Development/claude/claude-agents-dashboard/wrappers/macos && swift build 2>&1 | tail -5`

Expected: `Build complete!`

- [ ] **Step 5: Commit**

```bash
git add AgentsDashboard/Models/ServerManager.swift
git commit -m "feat: add ServerManager for git clone, venv setup, and update checks"
```

---

### Task 2: Create InstallSheet

**Files:**
- Create: `AgentsDashboard/Views/InstallSheet.swift`

- [ ] **Step 1: Create the install sheet view**

```swift
import SwiftUI

struct InstallSheet: View {
    @EnvironmentObject var projectManager: ProjectManager
    @ObservedObject var serverManager: ServerManager
    @State private var isInstalling = false

    var body: some View {
        VStack(spacing: 20) {
            if isInstalling {
                progressContent
            } else if let error = serverManager.installError {
                errorContent(error)
            } else {
                promptContent
            }
        }
        .padding(24)
        .frame(width: 460)
    }

    // MARK: - Prompt

    private var promptContent: some View {
        VStack(spacing: 16) {
            Image(systemName: "arrow.down.circle")
                .font(.system(size: 36))
                .foregroundColor(.accentColor)

            Text("Agents Dashboard Server Required")
                .font(.title2)
                .fontWeight(.semibold)

            Text("The dashboard server is not installed. This will clone the repository into ~/.agents-dashboard/ and set up a Python virtual environment.")
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)

            HStack {
                Button("Cancel") {
                    projectManager.showInstallSheet = false
                    projectManager.pendingProject = nil
                }
                .keyboardShortcut(.cancelAction)

                Spacer()

                Button("Install") {
                    install()
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
            }
        }
    }

    // MARK: - Progress

    private var progressContent: some View {
        VStack(spacing: 16) {
            ProgressView()
                .controlSize(.large)

            Text(stageText)
                .font(.title3)
                .foregroundColor(.secondary)
        }
    }

    private var stageText: String {
        switch serverManager.installStage {
        case .cloning: return "Cloning repository..."
        case .creatingVenv: return "Setting up Python environment..."
        case .installingDeps: return "Installing dependencies..."
        case .done: return "Done!"
        case nil: return "Preparing..."
        }
    }

    // MARK: - Error

    private func errorContent(_ error: String) -> some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 36))
                .foregroundColor(.red)

            Text("Installation Failed")
                .font(.title2)
                .fontWeight(.semibold)

            Text(error)
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)

            HStack {
                Button("Cancel") {
                    projectManager.showInstallSheet = false
                    projectManager.pendingProject = nil
                }
                .keyboardShortcut(.cancelAction)

                Spacer()

                Button("Retry") {
                    install()
                }
                .buttonStyle(.borderedProminent)
            }
        }
    }

    // MARK: - Actions

    private func install() {
        isInstalling = true
        Task {
            do {
                try await serverManager.clone()
                await MainActor.run {
                    isInstalling = false
                    projectManager.showInstallSheet = false
                    // Resume the pending dashboard start
                    if let project = projectManager.pendingProject {
                        projectManager.pendingProject = nil
                        projectManager.startDashboard(for: project)
                    }
                }
            } catch {
                await MainActor.run {
                    isInstalling = false
                    serverManager.installError = error.localizedDescription
                }
            }
        }
    }
}
```

- [ ] **Step 2: Verify it compiles**

Run: `swift build 2>&1 | tail -5`

Expected: Compile errors about `showInstallSheet` and `pendingProject` — these don't exist on ProjectManager yet. That's expected; Task 3 adds them.

- [ ] **Step 3: Commit**

```bash
git add AgentsDashboard/Views/InstallSheet.swift
git commit -m "feat: add InstallSheet view with progress and error states"
```

---

### Task 3: Integrate ServerManager into ProjectManager

**Files:**
- Modify: `AgentsDashboard/Models/ProjectManager.swift`

- [ ] **Step 1: Add ServerManager and new published properties**

Add these properties to `ProjectManager` at the top of the class (after the existing `@Published` vars around line 7):

```swift
    @Published var showInstallSheet = false
    @Published var pendingProject: Project?
    let serverManager = ServerManager()
```

- [ ] **Step 2: Replace dashboardRepoPath with serverManager.serverPath**

Delete the entire `dashboardRepoPath` computed property (lines 15-48).

- [ ] **Step 3: Update launchServer to use ServerManager**

Replace the `launchServer(for:)` method. Replace lines 139-217 with:

```swift
    private func launchServer(for instance: DashboardInstance) {
        // Check if server is installed
        guard serverManager.installationExists() else {
            pendingProject = instance.project
            showInstallSheet = true
            // Remove the dashboard instance since we can't start yet
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

        // Set environment
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
```

- [ ] **Step 4: Verify it compiles**

Run: `swift build 2>&1 | tail -5`

Expected: `Build complete!`

- [ ] **Step 5: Commit**

```bash
git add AgentsDashboard/Models/ProjectManager.swift
git commit -m "feat: integrate ServerManager, add install/update flow to dashboard start"
```

---

### Task 4: Wire up InstallSheet in ContentView

**Files:**
- Modify: `AgentsDashboard/Views/ContentView.swift`

- [ ] **Step 1: Add the install sheet binding**

Replace the entire ContentView body:

```swift
import SwiftUI

struct ContentView: View {
    @EnvironmentObject var projectManager: ProjectManager

    var body: some View {
        NavigationSplitView {
            SidebarView()
        } detail: {
            DashboardTabsView()
        }
        .sheet(isPresented: $projectManager.showAddProject) {
            AddProjectSheet()
        }
        .sheet(isPresented: $projectManager.showInstallSheet) {
            InstallSheet(serverManager: projectManager.serverManager)
        }
    }
}
```

- [ ] **Step 2: Verify it compiles**

Run: `swift build 2>&1 | tail -5`

Expected: `Build complete!`

- [ ] **Step 3: Commit**

```bash
git add AgentsDashboard/Views/ContentView.swift
git commit -m "feat: wire InstallSheet into ContentView"
```

---

### Task 5: Guard interactive block in run.sh

**Files:**
- Modify: `../../run.sh` (lines 27-48)

- [ ] **Step 1: Wrap the interactive update block**

In `run.sh`, replace lines 27-48. The existing block that does `git fetch` + `read -rp` gets wrapped in a condition:

```bash
# Check if the dashboard repo has upstream commits to pull
if [ "${AGENTS_DASHBOARD_AUTO_UPDATE:-0}" != "1" ]; then
    if git -C "$SCRIPT_DIR" rev-parse --git-dir > /dev/null 2>&1; then
        # Fetch latest from remote (silently)
        if git -C "$SCRIPT_DIR" fetch --quiet 2>/dev/null; then
            LOCAL=$(git -C "$SCRIPT_DIR" rev-parse HEAD 2>/dev/null)
            REMOTE=$(git -C "$SCRIPT_DIR" rev-parse '@{u}' 2>/dev/null || echo "")
            if [ -n "$REMOTE" ] && [ "$LOCAL" != "$REMOTE" ]; then
                BEHIND=$(git -C "$SCRIPT_DIR" rev-list --count HEAD..'@{u}' 2>/dev/null || echo "0")
                if [ "$BEHIND" -gt 0 ]; then
                    echo "Dashboard repo has $BEHIND commit(s) available to pull."
                    read -rp "Pull latest updates? [Y/n] " answer
                    answer="${answer:-Y}"
                    if [[ "$answer" =~ ^[Yy]$ ]]; then
                        echo "Pulling updates..."
                        git -C "$SCRIPT_DIR" pull --quiet
                        echo "Updated successfully."
                    else
                        echo "Skipping update."
                    fi
                fi
            fi
        fi
    fi
fi
```

- [ ] **Step 2: Test run.sh still works from CLI**

Run: `cd /Users/epatel/Development/claude/claude-agents-dashboard && bash -n run.sh && echo "Syntax OK"`

Expected: `Syntax OK`

- [ ] **Step 3: Test with env var set**

Run: `AGENTS_DASHBOARD_AUTO_UPDATE=1 bash -x run.sh /tmp 2>&1 | head -10`

Expected: The script should skip the fetch/prompt block and proceed to venv setup. (It will fail on /tmp not being a git repo, which is fine — we're checking it skips the update block.)

- [ ] **Step 4: Commit**

```bash
git add ../../run.sh
git commit -m "feat: skip interactive update prompt when AGENTS_DASHBOARD_AUTO_UPDATE=1"
```

---

### Task 6: Build and smoke test

- [ ] **Step 1: Clean build**

Run: `make clean && swift build 2>&1 | tail -3`

Expected: `Build complete!`

- [ ] **Step 2: Release build**

Run: `make release 2>&1 | tail -3`

Expected: `Built: .build/release/Agents Dashboard.app`

- [ ] **Step 3: Open the app**

Run: `open ".build/release/Agents Dashboard.app"`

Verify: App launches. If `~/.agents-dashboard/` doesn't exist, clicking Start on a project should show the install dialog.

- [ ] **Step 4: Commit any fixes if needed**

Only if smoke test reveals issues.
