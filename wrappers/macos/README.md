# Agents Dashboard — macOS App

A native SwiftUI wrapper that provides a desktop interface for managing Claude agents dashboards across multiple projects. Prebuilt `.app` bundles are available under [Releases](../../releases).

## Features

- **Project management** — add local git repositories, start/stop dashboard instances per project
- **Tabbed interface** — switch between running dashboards, each rendered in an embedded WebView
- **Auto-install** — on first run, clones the server to `~/.agents-dashboard/`, creates a Python venv, and installs dependencies
- **Update detection** — checks for upstream changes and prompts to pull
- **Real-time logs** — view server startup output while the dashboard is loading
- **Smart suggestions** — file browser scans common directories (~/Developer, ~/Development, ~/Projects, etc.)

## Requirements

- macOS 14+
- Python 3.10+
- Git
- Claude Code (installed and logged in)

## Install from release

Download the latest `.app` bundle from [Releases](../../releases), unzip, and drag to `/Applications`.

## Build from source

```bash
# Debug build
make build

# Release build (.app bundle)
make release

# Run debug build
make run

# Install to /Applications
make install
```

The release build produces `Agents Dashboard.app` in `.build/release/`. Version is read from the `VERSION` file; build number is derived from git commit count.

### Code signing and notarization

For distribution outside the App Store, copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
# Edit .env with your signing identity and Apple ID

# Sign with Developer ID
make sign

# Notarize with Apple
make notarize
```

The `notarize` target signs, submits to Apple, waits for approval, staples the ticket, and produces a versioned zip.

## Architecture

```
AgentsDashboard/
├── AgentsDashboardApp.swift     # Entry point, window configuration
├── Models/
│   ├── Project.swift            # Project data model (persisted via UserDefaults)
│   ├── ProjectManager.swift     # State management, process lifecycle
│   └── ServerManager.swift      # Server install, update, Python discovery
└── Views/
    ├── ContentView.swift        # NavigationSplitView root layout
    ├── SidebarView.swift        # Project list with status indicators
    ├── DashboardTabsView.swift  # Tab bar + dashboard content
    ├── DashboardWebView.swift   # WKWebView wrapper
    ├── AddProjectSheet.swift    # Add project dialog with suggestions
    └── InstallSheet.swift       # First-run installation flow
```

**ServerManager** handles the server clone at `~/.agents-dashboard/` — installation, Python venv setup, dependency installation, and update checks.

**ProjectManager** orchestrates project CRUD and dashboard process lifecycle — launching `run.sh` as a subprocess, capturing output via pipes, detecting the server port from stdout, and graceful shutdown (SIGTERM → SIGKILL after 5s).

## Make targets

| Target | Description |
|--------|-------------|
| `build` | Debug build via Swift Package Manager |
| `release` | Release build + `.app` bundle with ad-hoc signing |
| `sign` | Sign with Developer ID (`SIGNING_IDENTITY`) |
| `notarize` | Sign, submit to Apple, staple ticket, produce zip |
| `zip` | Create versioned zip of release build |
| `run` | Run debug build |
| `install` | Copy `.app` to `/Applications` |
| `uninstall` | Remove from `/Applications` |
| `clean` | Remove build artifacts |
