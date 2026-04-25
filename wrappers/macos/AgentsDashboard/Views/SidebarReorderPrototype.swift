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
    @State private var dropTargetID: UUID? = nil

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 2) {
                sectionHeader

                ForEach(projectManager.projects) { project in
                    PrototypeRow(
                        project: project,
                        isDragging: draggingID == project.id,
                        isDropTarget: dropTargetID == project.id && draggingID != project.id
                    )
                    .contentShape(Rectangle()) // entire row hit area
                    .onDrag {
                        // Record drag source. The transferable payload is the
                        // project id so we can locate it on drop.
                        draggingID = project.id
                        return NSItemProvider(object: project.id.uuidString as NSString)
                    } preview: {
                        // Lifted preview — slightly scaled up with a shadow.
                        PrototypeRow(project: project, isDragging: false, isDropTarget: false)
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
                            dropTargetID: $dropTargetID,
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
    let isDropTarget: Bool

    private var isAvailable: Bool { projectManager.isProjectAvailable(project) }
    private var dashboard: DashboardInstance? { projectManager.dashboardFor(project: project) }

    var body: some View {
        VStack(spacing: 0) {
            // Insertion gap appears above the targeted row.
            if isDropTarget {
                Capsule()
                    .fill(Color.accentColor)
                    .frame(height: 3)
                    .padding(.horizontal, 10)
                    .transition(.opacity.combined(with: .move(edge: .top)))
            }

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
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .fill(isDragging ? Color.accentColor.opacity(0.12) : Color.clear)
            )
            .scaleEffect(isDragging ? 1.02 : 1.0)
            .opacity(isDragging ? 0.6 : 1.0)
            .shadow(color: isDragging ? .black.opacity(0.15) : .clear, radius: 6, y: 2)
            .animation(.spring(response: 0.25, dampingFraction: 0.85), value: isDragging)
            .animation(.spring(response: 0.25, dampingFraction: 0.85), value: isDropTarget)
            .onTapGesture {
                if let d = dashboard { projectManager.selectedTab = d.id }
            }
        }
    }
}

// MARK: - Drop Delegate

private struct ReorderDropDelegate: DropDelegate {
    let target: Project
    @Binding var projects: [Project]
    @Binding var draggingID: UUID?
    @Binding var dropTargetID: UUID?
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
                dropTargetID = target.id
            }
        }
    }

    func dropUpdated(info: DropInfo) -> DropProposal? {
        DropProposal(operation: .move)
    }

    func performDrop(info: DropInfo) -> Bool {
        withAnimation(.spring(response: 0.25, dampingFraction: 0.85)) {
            draggingID = nil
            dropTargetID = nil
        }
        onCommit()
        return true
    }
}
