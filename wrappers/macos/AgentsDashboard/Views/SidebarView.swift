import SwiftUI

/// The sidebar always uses the rich reorder experience defined in
/// `SidebarReorderPrototype` — a long-press on a project arms it for
/// drag-to-reorder, and other rows animate aside to make room. The old
/// native `.onMove` sidebar (with the blue insertion line) has been
/// retired.
struct SidebarView: View {
    var body: some View {
        SidebarReorderPrototype()
    }
}

struct ProjectRow: View {
    @EnvironmentObject var projectManager: ProjectManager
    @State private var showRemoveConfirm = false
    let project: Project

    private var isRunning: Bool {
        projectManager.isProjectRunning(project)
    }

    private var isAvailable: Bool {
        projectManager.isProjectAvailable(project)
    }

    private var dashboard: DashboardInstance? {
        projectManager.dashboardFor(project: project)
    }

    var body: some View {
        HStack {
            projectLabel

            Spacer()

            statusIndicator
        }
        .padding(.vertical, 4)
        .contentShape(Rectangle())
        .onTapGesture {
            if let d = dashboard {
                projectManager.selectedTab = d.id
            }
        }
        .contextMenu { contextMenuItems }
        .alert("Remove Project?", isPresented: $showRemoveConfirm) {
            Button("Remove", role: .destructive) {
                projectManager.removeProject(project)
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Remove \"\(project.name)\" from the sidebar? This won't delete any files.")
        }
    }

    /// Name (with an unavailable warning) above the path.
    private var projectLabel: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 4) {
                Text(project.name)
                    .font(.headline)
                if !isAvailable {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundColor(.orange)
                        .font(.caption)
                        .help("Project unavailable — no database found at \(project.path)/agents-lab/dashboard.db")
                }
            }
            Text(project.path)
                .font(.caption)
                .foregroundColor(.secondary)
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .help(project.path)
        .opacity(isAvailable ? 1.0 : 0.5)
    }

    @ViewBuilder
    private var contextMenuItems: some View {
        if isRunning {
            Button("Show Dashboard") {
                if let d = dashboard {
                    projectManager.selectedTab = d.id
                }
            }
            Divider()
            Button("Stop Dashboard") {
                if let d = dashboard {
                    projectManager.stopDashboard(id: d.id)
                }
            }
        } else if isAvailable {
            Button("Start Dashboard") {
                projectManager.startDashboard(for: project)
            }
        } else {
            Button("Project Unavailable") {}
                .disabled(true)
        }

        Divider()

        Button("Open in Terminal") {
            TerminalHelper.open(path: project.path)
        }

        Button("Recheck Availability") {
            projectManager.checkProjectAvailability()
        }

        Divider()

        Toggle("Experimental (Ollama, Kimi)", isOn: Binding(
            get: { project.experimental },
            set: { projectManager.setExperimental($0, for: project) }
        ))
        .help("Launch this project's dashboard with --experimental (enables experimental providers: Ollama, and Kimi models via the Kimi Agent SDK). Applies on next start.")

        Divider()

        Button("Remove Project", role: .destructive) {
            showRemoveConfirm = true
        }
    }

    private var terminalButton: some View {
        Button(action: { TerminalHelper.open(path: project.path) }) {
            Image(systemName: "terminal")
                .foregroundColor(.secondary)
                .font(.caption)
        }
        .buttonStyle(.plain)
        .help("Open in terminal")
    }

    private var removeButton: some View {
        Button(action: {
            showRemoveConfirm = true
        }) {
            Image(systemName: "trash")
                .foregroundColor(.secondary)
                .font(.caption)
        }
        .buttonStyle(.plain)
        .help("Remove project")
    }

    /// Terminal and remove buttons, then the control for the dashboard's state.
    private var statusIndicator: some View {
        HStack(spacing: 4) {
            terminalButton
            removeButton
            statusControl
        }
    }

    @ViewBuilder
    private var statusControl: some View {
        if let dashboard = dashboard {
            switch dashboard.status {
            case .running:
                Button(action: {
                    projectManager.stopDashboard(id: dashboard.id)
                }) {
                    Image(systemName: "stop.circle.fill")
                        .foregroundColor(.red)
                        .font(.title2)
                }
                .buttonStyle(.plain)
                .help("Stop dashboard (port \(dashboard.port ?? 0))")

            case .starting:
                ProgressView()
                    .controlSize(.small)
                    .help("Starting dashboard...")

            case .stopping:
                ProgressView()
                    .controlSize(.small)
                    .help("Stopping dashboard...")

            case .error:
                Image(systemName: "exclamationmark.circle.fill")
                    .foregroundColor(.red)
                    .help(dashboard.errorMessage ?? "Error")

            case .stopped:
                startControl
            }
        } else {
            startControl
        }
    }

    /// Start button, or a warning when the project has no database yet.
    @ViewBuilder
    private var startControl: some View {
        if isAvailable {
            Button(action: {
                projectManager.startDashboard(for: project)
            }) {
                Image(systemName: "play.circle")
                    .foregroundColor(.secondary)
                    .font(.title2)
            }
            .buttonStyle(.plain)
            .help("Start dashboard")
        } else {
            Image(systemName: "nosign")
                .foregroundColor(.orange)
                .font(.title2)
                .help("No database found — start the dashboard once via CLI first")
        }
    }
}
