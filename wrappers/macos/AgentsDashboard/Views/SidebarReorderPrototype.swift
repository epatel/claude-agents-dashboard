import SwiftUI
import UniformTypeIdentifiers
import AppKit

/// Sidebar with a richer drag-and-drop reorder experience:
///   • Whole row is the hit area.
///   • A **long-press (~0.35s)** on a row is required before drag-to-reorder
///     activates — a quick click still selects the dashboard, so reorder
///     never triggers by accident.
///   • Once armed, the row lifts (scale + shadow) as the OS drag image, the
///     original row collapses to an empty placeholder, and other rows
///     animate aside to "make room" as the pointer moves.
///   • Persistence happens through `ProjectManager.persistAfterReorder`.
struct SidebarReorderPrototype: View {
    @EnvironmentObject var projectManager: ProjectManager
    @State private var draggingID: UUID? = nil
    /// Set by a `LongPressGesture` on a row — until armed, `.onDrag`
    /// refuses to start a real drag, so a single click just selects.
    @State private var armedID: UUID? = nil

    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 2) {
                sectionHeader

                ForEach(projectManager.projects) { project in
                    ReorderableRow(
                        project: project,
                        isDragging: draggingID == project.id,
                        isArmed: armedID == project.id
                    )
                    .contentShape(Rectangle())
                    // Long-press arms this row for drag. Quick clicks still
                    // fall through to ProjectRow's onTapGesture (select
                    // dashboard) because LongPressGesture only fires after
                    // the duration has elapsed without release.
                    .simultaneousGesture(
                        LongPressGesture(minimumDuration: 0.35)
                            .onEnded { _ in
                                armRow(project.id)
                            }
                    )
                    .onDrag {
                        // Only initiate a real drag once the row was armed
                        // by a long-press. An empty NSItemProvider keeps
                        // accidental drags from doing anything visible.
                        guard armedID == project.id else {
                            return NSItemProvider()
                        }
                        draggingID = project.id
                        return NSItemProvider(object: project.id.uuidString as NSString)
                    } preview: {
                        // OS-rendered drag preview — slightly scaled with shadow.
                        ProjectRow(project: project)
                            .padding(.horizontal, 10)
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
                            armedID: $armedID,
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

    private func armRow(_ id: UUID) {
        withAnimation(.spring(response: 0.2, dampingFraction: 0.8)) {
            armedID = id
        }
        // Subtle haptic + cursor cue so the user knows the row is now
        // grabbable. Closed-hand cursor mirrors macOS Finder convention.
        NSHapticFeedbackManager.defaultPerformer.perform(.alignment, performanceTime: .now)
        NSCursor.closedHand.set()
        // Auto-disarm if the user holds-then-releases without ever dragging,
        // so the highlight + cursor don't linger.
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            if armedID == id && draggingID == nil {
                withAnimation(.easeInOut(duration: 0.2)) {
                    armedID = nil
                }
                NSCursor.arrow.set()
            }
        }
    }
}

// MARK: - Row

/// Wraps the full-featured `ProjectRow` (play/stop/terminal/remove buttons,
/// context menu, status indicator) and adds the reorder visual states:
/// dragging → invisible placeholder; armed → faint highlight so the user
/// can see the long-press registered before they start moving the pointer.
private struct ReorderableRow: View {
    let project: Project
    let isDragging: Bool
    let isArmed: Bool

    var body: some View {
        ProjectRow(project: project)
            .padding(.horizontal, 6)
            .background(
                RoundedRectangle(cornerRadius: 6)
                    .fill(Color.accentColor.opacity(isArmed && !isDragging ? 0.12 : 0))
            )
            // While dragging, keep the row's footprint (so siblings still
            // animate to "make room") but hide its content — the OS-rendered
            // drag image is the only thing the user sees move.
            .opacity(isDragging ? 0 : 1.0)
            .animation(.spring(response: 0.25, dampingFraction: 0.85), value: isDragging)
            .animation(.easeInOut(duration: 0.15), value: isArmed)
    }
}

// MARK: - Drop Delegate

private struct ReorderDropDelegate: DropDelegate {
    let target: Project
    @Binding var projects: [Project]
    @Binding var draggingID: UUID?
    @Binding var armedID: UUID?
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
            armedID = nil
        }
        NSCursor.arrow.set()
        onCommit()
        return true
    }

    func dropExited(info: DropInfo) {
        // No-op — `dropEntered` on a sibling will re-shuffle, and a true
        // cancel is handled by `performDrop` (or by the next interaction
        // resetting `armedID`/`draggingID`).
    }
}
