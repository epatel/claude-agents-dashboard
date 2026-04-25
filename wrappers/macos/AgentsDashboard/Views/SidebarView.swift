import SwiftUI

/// PreferenceKey used to surface measured row heights so we can convert a
/// drag-translation in pixels into a row-index delta.
private struct ProjectRowHeightKey: PreferenceKey {
    static var defaultValue: CGFloat = 52
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = max(value, nextValue())
    }
}

struct SidebarView: View {
    @EnvironmentObject var projectManager: ProjectManager

    /// The project currently being long-press-dragged, if any.
    @State private var draggingProjectID: UUID?
    /// Vertical translation (px) applied to the dragging row for visual feedback.
    @State private var dragOffset: CGFloat = 0
    /// Measured row height — falls back to 52pt until the first measurement lands.
    @State private var rowHeight: CGFloat = 52

    var body: some View {
        List {
            Section("Projects") {
                ForEach(projectManager.projects) { project in
                    ProjectRow(project: project)
                        .background(
                            GeometryReader { geo in
                                Color.clear.preference(
                                    key: ProjectRowHeightKey.self,
                                    value: geo.size.height
                                )
                            }
                        )
                        .opacity(draggingProjectID == project.id ? 0.5 : 1.0)
                        .offset(y: draggingProjectID == project.id ? dragOffset : 0)
                        .zIndex(draggingProjectID == project.id ? 1 : 0)
                        .animation(.easeInOut(duration: 0.15), value: draggingProjectID)
                        .simultaneousGesture(longPressDragGesture(for: project))
                }
            }
        }
        .listStyle(.sidebar)
        .frame(minWidth: 220)
        .onPreferenceChange(ProjectRowHeightKey.self) { height in
            if height > 0 { rowHeight = height }
        }
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

    /// A LongPress-then-Drag sequence: the row only becomes draggable after a
    /// ~0.35s hold; once the long-press recognizes, the user can drag the row
    /// up/down to reorder without releasing. On release we snap to the closest
    /// row slot and persist via `ProjectManager.moveProjects`.
    private func longPressDragGesture(for project: Project) -> some Gesture {
        LongPressGesture(minimumDuration: 0.35)
            .sequenced(before: DragGesture(minimumDistance: 0, coordinateSpace: .local))
            .onChanged { value in
                switch value {
                case .first(true):
                    if draggingProjectID == nil {
                        draggingProjectID = project.id
                        dragOffset = 0
                    }
                case .second(true, let drag?):
                    if draggingProjectID == nil {
                        draggingProjectID = project.id
                    }
                    dragOffset = drag.translation.height
                default:
                    break
                }
            }
            .onEnded { _ in
                defer {
                    draggingProjectID = nil
                    dragOffset = 0
                }
                guard let id = draggingProjectID,
                      let from = projectManager.projects.firstIndex(where: { $0.id == id })
                else { return }

                let count = projectManager.projects.count
                guard count > 1, rowHeight > 0 else { return }

                let movedRows = Int((dragOffset / rowHeight).rounded())
                let newIndex = max(0, min(from + movedRows, count - 1))
                guard newIndex != from else { return }

                // `Array.move(fromOffsets:toOffset:)` expects an "insert-before"
                // offset, so a forward move needs +1 to land *after* the target.
                let toOffset = newIndex > from ? newIndex + 1 : newIndex
                projectManager.moveProjects(from: IndexSet(integer: from), to: toOffset)
            }
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
