import SwiftUI
import UniformTypeIdentifiers

/// Prototype sidebar with a richer drag-and-drop reorder experience:
///   • Entire row is draggable (no fragmented hit areas).
///   • Dragged row scales up slightly with a shadow ("lifted" feel).
///   • Other rows animate aside to "make room" as you drag.
///   • Persistence happens through `ProjectManager.moveProjects`.
///
/// Toggle live via the toolbar gear in `SidebarView`. Stored in
/// `UserDefaults` under `sidebar_reorder_prototype`.
struct SidebarReorderPrototype: View {
    @EnvironmentObject var projectManager: ProjectManager
    @State private var draggingID: UUID? = nil

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 2) {
                sectionHeader

                ForEach(projectManager.projects) { project in
                    PrototypeRow(
                        project: project,
                        isDragging: draggingID == project.id
                    )
                    .contentShape(Rectangle()) // entire row hit area
                    .onDrag {
                        // Record drag source. The transferable payload is the
                        // project id so we can locate it on drop.
                        draggingID = project.id
                        return NSItemProvider(object: project.id.uuidString as NSString)
                    } preview: {
                        // Lifted preview — slightly scaled up with a shadow.
                        PrototypeRow(project: project, isDragging: false)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 6)
                            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
                            .shadow(color: .black.opacity(0.25), radius: 8, x: 0, y: 4)
                            .frame(width: 260)
                    }
                    .onDrop(
                        of: [.text],
                        delegate: ReorderDropDelegate(
                            target: project,
                            projects: $projectManager.projects,
                            draggingID: $draggingID,
                            onCommit: { projectManager.persistAfterReorder() }
                        )
                    )
                }
            }
            .padding(.vertical, 4)
        }
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

    private var sectionHeader: some View {
        Text("PROJECTS")
            .font(.caption)
            .foregroundColor(.secondary)
            .padding(.horizontal, 12)
            .padding(.top, 6)
            .padding(.bottom, 2)
    }
}

// MARK: - Row

private struct PrototypeRow: View {
    @EnvironmentObject var projectManager: ProjectManager
    @State private var showRemoveConfirm = false
    let project: Project
    let isDragging: Bool

    private var isAvailable: Bool { projectManager.isProjectAvailable(project) }
    private var dashboard: DashboardInstance? { projectManager.dashboardFor(project: project) }

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 4) {
                    Text(project.name).font(.headline)
                    if !isAvailable {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundColor(.orange)
                            .font(.caption)
                    }
                }
                Text(project.path)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
            .opacity(isAvailable ? 1.0 : 0.5)

            Spacer()
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        // While dragging, keep the row's footprint (so siblings still "make
        // room" via the LazyVStack reorder) but hide its content — the row
        // becomes an empty placeholder showing where the drop will land.
        // The OS-rendered drag preview is the only thing the user sees move.
        .opacity(isDragging ? 0 : 1.0)
        .animation(.spring(response: 0.25, dampingFraction: 0.85), value: isDragging)
        .onTapGesture {
            if let d = dashboard { projectManager.selectedTab = d.id }
        }
    }
}

// MARK: - Drop Delegate

private struct ReorderDropDelegate: DropDelegate {
    let target: Project
    @Binding var projects: [Project]
    @Binding var draggingID: UUID?
    let onCommit: () -> Void

    func dropEntered(info: DropInfo) {
        guard let dragID = draggingID, dragID != target.id else { return }
        guard let from = projects.firstIndex(where: { $0.id == dragID }),
              let to = projects.firstIndex(where: { $0.id == target.id })
        else { return }
        if projects[to].id != projects[from].id {
            withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) {
                let item = projects.remove(at: from)
                projects.insert(item, at: to)
            }
        }
    }

    func dropUpdated(info: DropInfo) -> DropProposal? {
        DropProposal(operation: .move)
    }

    func performDrop(info: DropInfo) -> Bool {
        withAnimation(.spring(response: 0.25, dampingFraction: 0.85)) {
            draggingID = nil
        }
        onCommit()
        return true
    }
}
