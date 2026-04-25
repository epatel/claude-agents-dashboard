import SwiftUI

struct SidebarView: View {
    @EnvironmentObject var projectManager: ProjectManager

    var body: some View {
        List {
            Section("Projects") {
                ForEach(projectManager.projects) { project in
                    ProjectRow(project: project)
                }
                .onMove { source, destination in
                    projectManager.moveProjects(from: source, to: destination)
                }
            }
        }
        .listStyle(.sidebar)
        .frame(minWidth: 220)
        .toolbar {
            ToolbarItem {
                Menu {
                    Button(action: { projectManager.showCreateProject = true }) {
                        Label("New Project...", systemImage: "plus.rectangle.on.folder")
                    }
                    Button(action: { projectManager.showAddProject = true }) {
                        Label("Add Existing Project...", systemImage: "folder.badge.plus")
                    }
                } label: {
                    Label("Add", systemImage: "plus")
                }
                .help("Add or create a project")
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

    private var isAvailable: Bool {
        projectManager.isProjectAvailable(project)
    }

    private var dashboard: DashboardInstance? {
        projectManager.dashboardFor(project: project)
    }

    var body: some View {
        HStack {
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
                        projectManager.stopDashboard(id: dashboard.id)
                    }) {
                        Image(systemName: "stop.circle.fill")
                            .foregroundColor(.red)
                            .font(.title2)
                    }
                    .buttonStyle(.plain)
                    .help("Stop dashboard (port \(dashboard.port ?? 0))")
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
        } else {
            HStack(spacing: 4) {
                terminalButton
                removeButton
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
    }
}
