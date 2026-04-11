import SwiftUI

struct DashboardTabsView: View {
    @EnvironmentObject var projectManager: ProjectManager

    var body: some View {
        VStack(spacing: 0) {
            if projectManager.dashboards.isEmpty {
                emptyState
            } else {
                tabBar
                tabContent
            }
        }
    }

    // MARK: - Empty State

    private var emptyState: some View {
        VStack(spacing: 16) {
            Image(systemName: "rectangle.on.rectangle.slash")
                .font(.system(size: 48))
                .foregroundColor(.secondary)

            Text("No Dashboards Running")
                .font(.title2)
                .foregroundColor(.secondary)

            Text("Right-click a project in the sidebar to start a dashboard,\nor click the play button.")
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)

            if !projectManager.projects.isEmpty {
                Button("Start First Project") {
                    if let project = projectManager.projects.first {
                        projectManager.startDashboard(for: project)
                    }
                }
                .buttonStyle(.borderedProminent)
            } else {
                Button("Add a Project") {
                    projectManager.showAddProject = true
                }
                .buttonStyle(.borderedProminent)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    // MARK: - Tab Bar

    private var tabBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 0) {
                ForEach(projectManager.dashboards) { dashboard in
                    TabButton(dashboard: dashboard)
                }
            }
        }
        .frame(height: 36)
        .background(Color(nsColor: .controlBackgroundColor))
        .overlay(alignment: .bottom) {
            Divider()
        }
    }

    // MARK: - Tab Content

    @ViewBuilder
    private var tabContent: some View {
        if let selectedId = projectManager.selectedTab,
           let dashboard = projectManager.dashboards.first(where: { $0.id == selectedId }) {
            switch dashboard.status {
            case .running:
                if let url = dashboard.url {
                    DashboardWebView(url: url)
                } else {
                    loadingView(dashboard)
                }
            case .starting:
                loadingView(dashboard)
            case .error:
                errorView(dashboard)
            case .stopping, .stopped:
                stoppedView(dashboard)
            }
        } else if let first = projectManager.dashboards.first {
            Color.clear
                .onAppear {
                    projectManager.selectedTab = first.id
                }
        }
    }

    private func loadingView(_ dashboard: DashboardInstance) -> some View {
        VStack(spacing: 16) {
            ProgressView()
                .controlSize(.large)
            Text("Starting dashboard for \(dashboard.project.name)...")
                .font(.title3)
                .foregroundColor(.secondary)

            if !dashboard.outputLog.isEmpty {
                ScrollView {
                    Text(dashboard.outputLog)
                        .font(.system(.caption, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding()
                }
                .frame(maxWidth: 500, maxHeight: 200)
                .background(Color(nsColor: .textBackgroundColor))
                .cornerRadius(8)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func errorView(_ dashboard: DashboardInstance) -> some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 48))
                .foregroundColor(.red)

            Text("Dashboard Error")
                .font(.title2)

            if let error = dashboard.errorMessage {
                Text(error)
                    .font(.body)
                    .foregroundColor(.secondary)
            }

            if !dashboard.outputLog.isEmpty {
                ScrollView {
                    Text(dashboard.outputLog)
                        .font(.system(.caption, design: .monospaced))
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding()
                }
                .frame(maxWidth: 600, maxHeight: 300)
                .background(Color(nsColor: .textBackgroundColor))
                .cornerRadius(8)
            }

            HStack {
                Button("Restart") {
                    projectManager.removeDashboard(id: dashboard.id)
                    projectManager.startDashboard(for: dashboard.project)
                }
                .buttonStyle(.borderedProminent)

                Button("Remove") {
                    projectManager.removeDashboard(id: dashboard.id)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func stoppedView(_ dashboard: DashboardInstance) -> some View {
        VStack(spacing: 16) {
            Image(systemName: "stop.circle")
                .font(.system(size: 48))
                .foregroundColor(.secondary)

            Text("Dashboard Stopped")
                .font(.title2)
                .foregroundColor(.secondary)

            HStack {
                Button("Restart") {
                    projectManager.removeDashboard(id: dashboard.id)
                    projectManager.startDashboard(for: dashboard.project)
                }
                .buttonStyle(.borderedProminent)

                Button("Remove Tab") {
                    projectManager.removeDashboard(id: dashboard.id)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Tab Button

struct TabButton: View {
    @EnvironmentObject var projectManager: ProjectManager
    let dashboard: DashboardInstance

    private var isSelected: Bool {
        projectManager.selectedTab == dashboard.id
    }

    var body: some View {
        HStack(spacing: 6) {
            statusDot

            Text(dashboard.project.name)
                .font(.system(size: 12, weight: isSelected ? .semibold : .regular))
                .lineLimit(1)

            if dashboard.status == .running, let port = dashboard.port {
                Text(":\(port)")
                    .font(.system(size: 10, design: .monospaced))
                    .foregroundColor(.secondary)
            }

            Button(action: {
                projectManager.removeDashboard(id: dashboard.id)
            }) {
                Image(systemName: "xmark")
                    .font(.system(size: 9, weight: .bold))
                    .foregroundColor(.secondary)
            }
            .buttonStyle(.plain)
            .opacity(isSelected ? 1 : 0)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .background(isSelected ? Color(nsColor: .selectedControlColor).opacity(0.3) : Color.clear)
        .overlay(alignment: .bottom) {
            if isSelected {
                Rectangle()
                    .fill(Color.accentColor)
                    .frame(height: 2)
            }
        }
        .contentShape(Rectangle())
        .onTapGesture {
            projectManager.selectedTab = dashboard.id
        }
        .onHover { hovering in
            if hovering {
                NSCursor.pointingHand.push()
            } else {
                NSCursor.pop()
            }
        }
    }

    @ViewBuilder
    private var statusDot: some View {
        switch dashboard.status {
        case .running:
            Circle()
                .fill(.green)
                .frame(width: 8, height: 8)
        case .starting, .stopping:
            ProgressView()
                .controlSize(.mini)
        case .error:
            Circle()
                .fill(.red)
                .frame(width: 8, height: 8)
        case .stopped:
            Circle()
                .fill(.gray)
                .frame(width: 8, height: 8)
        }
    }
}
