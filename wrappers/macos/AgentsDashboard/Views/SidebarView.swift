import SwiftUI

struct SidebarView: View {
    @EnvironmentObject var projectManager: ProjectManager

    var body: some View {
        List {
            Section("Projects") {
                ForEach(projectManager.projects) { project in
                    ProjectRow(project: project)
                }
                .onMove { projectManager.moveProjects(from: $0, to: $1) }
            }
        }
        .listStyle(.sidebar)
        .frame(minWidth: 220)
        .toolbar {
            ToolbarItem {
                Button(action: { projectManager.showAddProject = true }) {
                    Label("Add Project", systemImage: "plus")
                }
                .help("Add a project")
            }
        }
        .navigationTitle("Agents Dashboard")
    }
}

struct ProjectRow: View {
    @EnvironmentObject var projectManager: ProjectManager
    @State private var showRemoveConfirm = false
    let project: Project

    private var isRunning: Bool {
        projectManager.isProjectRunning(project)
    }

    private var dashboard: DashboardInstance? {
        projectManager.dashboardFor(project: project)
    }

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(project.name)
                    .font(.headline)
                Text(project.path)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            .help(project.path)

            Spacer()

            statusIndicator
        }
        .padding(.vertical, 4)
        .contextMenu {
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
            } else {
                Button("Start Dashboard") {
                    projectManager.startDashboard(for: project)
                }
            }

            Divider()

            Button("Open in Terminal") {
                TerminalHelper.open(path: project.path)
            }

            Divider()

            Button("Remove Project", role: .destructive) {
                showRemoveConfirm = true
            }
        }
        .alert("Remove Project?", isPresented: $showRemoveConfirm) {
            Button("Remove", role: .destructive) {
                projectManager.removeProject(project)
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Remove \"\(project.name)\" from the sidebar? This won't delete any files.")
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

    @ViewBuilder
    private var statusIndicator: some View {
        if let dashboard = dashboard {
            switch dashboard.status {
            case .running:
                HStack(spacing: 4) {
                    terminalButton
                    removeButton
                    Button(action: {
                        projectManager.selectedTab = dashboard.id
                    }) {
                        Image(systemName: "play.circle.fill")
                            .foregroundColor(.green)
                            .font(.title2)
                    }
                    .buttonStyle(.plain)
                    .help("Show dashboard (port \(dashboard.port ?? 0))")
                }

            case .starting:
                HStack(spacing: 4) {
                    terminalButton
                    removeButton
                    ProgressView()
                        .controlSize(.small)
                        .help("Starting dashboard...")
                }

            case .stopping:
                HStack(spacing: 4) {
                    terminalButton
                    removeButton
                    ProgressView()
                        .controlSize(.small)
                        .help("Stopping dashboard...")
                }

            case .error:
                HStack(spacing: 4) {
                    terminalButton
                    removeButton
                    Image(systemName: "exclamationmark.circle.fill")
                        .foregroundColor(.red)
                        .help(dashboard.errorMessage ?? "Error")
                }

            case .stopped:
                HStack(spacing: 4) {
                    terminalButton
                    removeButton
                    Button(action: {
                        projectManager.startDashboard(for: project)
                    }) {
                        Image(systemName: "play.circle")
                            .foregroundColor(.secondary)
                            .font(.title2)
                    }
                    .buttonStyle(.plain)
                    .help("Start dashboard")
                }
            }
        } else {
            HStack(spacing: 4) {
                terminalButton
                removeButton
                Button(action: {
                    projectManager.startDashboard(for: project)
                }) {
                    Image(systemName: "play.circle")
                        .foregroundColor(.secondary)
                        .font(.title2)
                }
                .buttonStyle(.plain)
                .help("Start dashboard")
            }
        }
    }
}
