# Server Installation at ~/.agents-dashboard/

## Problem

The macOS wrapper app currently resolves `run.sh` by walking up from the binary location. This only works when the app runs from inside the repo build directory. Moving the app (e.g., to /Applications) breaks it. There is no install or update mechanism — users must manually clone and manage the dashboard repo.

## Solution

The app manages a local clone of the dashboard repo at `~/.agents-dashboard/`. On first dashboard start (if missing), it prompts the user to install. On each subsequent dashboard start, it checks for updates. The `run.sh` script gains an env var (`AGENTS_DASHBOARD_AUTO_UPDATE=1`) to skip its interactive update prompt when the app has already handled the decision.

## Components

### 1. ServerManager (new class)

New file: `AgentsDashboard/Models/ServerManager.swift`

Responsibilities:
- **installationExists() -> Bool** — checks `~/.agents-dashboard/run.sh` exists
- **clone(progress: (String) -> Void) async throws** — clones `epatel/claude-agents-dashboard` into `~/.agents-dashboard/`, creates venv, runs pip install. Reports progress stages via callback: "Cloning repository...", "Setting up Python environment...", "Installing dependencies...", "Done."
- **checkForUpdates() async -> UpdateStatus** — runs `git fetch` on `~/.agents-dashboard/`, compares HEAD vs `@{u}`, returns `.upToDate`, `.updatesAvailable(Int)`, or `.error(String)`
- **pullUpdates() async throws** — runs `git pull` on `~/.agents-dashboard/`
- **serverPath: String** — returns `~/.agents-dashboard/` (expanded from `~`)

Git clone URL: `https://github.com/epatel/claude-agents-dashboard.git`

Uses HTTPS (not SSH) so it works without SSH key setup.

### 2. InstallSheet (new view)

New file: `AgentsDashboard/Views/InstallSheet.swift`

Shown as a `.sheet` when a dashboard start is attempted and `ServerManager.installationExists()` returns false.

**Initial state:**
- Title: "Agents Dashboard Server Required"
- Body: "The dashboard server is not installed. This will clone the repository into ~/.agents-dashboard/ and set up a Python virtual environment."
- Buttons: [Install] [Cancel]

**Progress state (after Install clicked):**
- Progress spinner with stage text ("Cloning repository...", "Setting up Python environment...", etc.)
- Install button disabled during progress
- On success: sheet dismisses, dashboard start proceeds
- On failure: error message shown with [Retry] [Cancel]

### 3. Update check flow

Happens in `ProjectManager.startDashboard(for:)` before launching run.sh.

- Calls `ServerManager.checkForUpdates()`
- If `.updatesAvailable(n)`: shows native `NSAlert` — "n update(s) available. Update now?" with [Update] [Skip] buttons
  - Update: calls `ServerManager.pullUpdates()`, then launches
  - Skip: launches as-is
- If `.upToDate` or `.error`: proceeds to launch

### 4. Changes to run.sh

When env var `AGENTS_DASHBOARD_AUTO_UPDATE=1` is set, skip lines 27-48 (the fetch + interactive prompt block). The rest of run.sh (venv check, pip install, server launch) runs normally.

```bash
# Replace lines 27-48 with:
if [ "${AGENTS_DASHBOARD_AUTO_UPDATE:-0}" != "1" ]; then
    # existing fetch + interactive prompt block
    ...
fi
```

### 5. Changes to ProjectManager

- Remove the `dashboardRepoPath` computed property (all 4 tiers)
- Add `let serverManager = ServerManager()` property
- `launchServer(for:)` changes:
  - Before launching process: check `serverManager.installationExists()`, if false trigger install sheet and return
  - If installed: check for updates, show alert if available
  - `runShPath` becomes `serverManager.serverPath + "/run.sh"`
  - Add `AGENTS_DASHBOARD_AUTO_UPDATE=1` to the process environment dict

### 6. Changes to ContentView

- Add `.sheet` binding for the install dialog, driven by a new `@Published var showInstallSheet` on ProjectManager
- After successful install, retry the pending dashboard start

## Flow

```
User clicks "Start Dashboard" on a project
  |
  v
ServerManager.installationExists()?
  |
  +-- No --> Show InstallSheet
  |            |
  |            +-- [Cancel] --> Return to sidebar
  |            +-- [Install] --> Clone + venv + pip (with progress)
  |                               |
  |                               +-- Success --> Continue below
  |                               +-- Failure --> Show error, [Retry]/[Cancel]
  |
  +-- Yes --> Continue
  |
  v
ServerManager.checkForUpdates()
  |
  +-- .updatesAvailable(n) --> NSAlert "n updates available"
  |     +-- [Update] --> git pull --> Launch run.sh
  |     +-- [Skip]   --> Launch run.sh
  |
  +-- .upToDate --> Launch run.sh
  +-- .error    --> Launch run.sh (log warning)
  |
  v
Launch run.sh with AGENTS_DASHBOARD_AUTO_UPDATE=1 in env
```

## What stays the same

- `Project` model, `AddProjectSheet`, sidebar, tabs, WebView — unchanged
- run.sh remains the canonical way to start the server for CLI users
- UserDefaults persistence for saved projects
- Server URL detection from process output
- Process lifecycle management (stop, terminate, cleanup)

## Files to create

- `AgentsDashboard/Models/ServerManager.swift`
- `AgentsDashboard/Views/InstallSheet.swift`

## Files to modify

- `AgentsDashboard/Models/ProjectManager.swift` — replace dashboardRepoPath, integrate ServerManager
- `AgentsDashboard/Views/ContentView.swift` — add install sheet binding
- `../../run.sh` — guard interactive block with env var check
