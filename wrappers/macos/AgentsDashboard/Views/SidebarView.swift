import SwiftUI

struct SidebarView: View {
    @EnvironmentObject var projectManager: ProjectManager

    var body: some View {
        List {
            Section("Projects") {
                ForEach(projectManager.projects) { project in
                    ProjectRow(project: project)
                }
            }
        }
        .listStyle(.sidebar)
        .frame(minWidth: 220)
        .toolbar {
            ToolbarItem {
                Button(action: { projectManager.showAddProject = true }) {
                    Label("Add Project", systemImage: "plus")
                }
            }
        }
        .navigationTitle("Agents Dashboard")
    }
}

struct ProjectRow: View {
    @EnvironmentObject var projectManager: ProjectManager
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

            Button("Remove Project", role: .destructive) {
                projectManager.removeProject(project)
            }
        }
    }

    @ViewBuilder
    private var statusIndicator: some View {
        if let dashboard = dashboard {
            switch dashboard.status {
            case .running:
                Button(action: {
                    projectManager.selectedTab = dashboard.id
                }) {
                    Image(systemName: "play.circle.fill")
                        .foregroundColor(.green)
                        .font(.title2)
                }
                .buttonStyle(.plain)
                .help("Dashboard running on port \(dashboard.port ?? 0)")

            case .starting:
                ProgressView()
                    .controlSize(.small)
                    .help("Starting...")

            case .stopping:
                ProgressView()
                    .controlSize(.small)
                    .help("Stopping...")

            case .error:
                Image(systemName: "exclamationmark.circle.fill")
                    .foregroundColor(.red)
                    .help(dashboard.errorMessage ?? "Error")

            case .stopped:
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
        } else {
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
