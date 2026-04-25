import SwiftUI
import AppKit

/// Sidebar with long-press-armed drag-to-reorder. The gesture is a
/// `LongPressGesture(0.35s) → DragGesture(minDistance: 0)` chain — until the
/// press has been held long enough, the chain is inert, so quick clicks fall
/// through to `ProjectRow`'s tap (select dashboard). Crossing the
/// LongPressGesture's default ~10-pt slop before 0.35s fails the chain too,
/// killing accidental drag-from-quick-click.
///
/// Why not `.onDrag`? AppKit's drag system and SwiftUI's `LongPressGesture`
/// share an event channel poorly: the long-press recognizer consumes the
/// mouseDown, and a subsequent gated `.onDrag` either never fires or sees a
/// stale armed state. Hand-rolling the reorder via a single `SequenceGesture`
/// keeps the entire interaction in one recognizer.
struct SidebarReorderPrototype: View {
    @EnvironmentObject var projectManager: ProjectManager

    @State private var draggingID: UUID? = nil
    /// Vertical offset of the dragged row relative to its current LazyVStack
    /// slot. We always set it so the row's *center* sits exactly under the
    /// cursor — i.e., the row recenters on the pointer when picked up
    /// (iOS-style lift), then tracks it.
    @State private var dragOffset: CGFloat = 0
    /// Index of the dragged row when the drag began. Slot-target math is
    /// reckoned from this fixed origin so it stays stable as the array shuffles.
    @State private var dragStartIndex: Int? = nil

    /// Slot pitch (row frame + LazyVStack spacing). We *pin* the row to a
    /// known height in `ReorderableRow` so this number is exact — otherwise
    /// the swap thresholds land mid-row and siblings shuffle when the cursor
    /// hasn't actually moved that far.
    private let rowFrameHeight: CGFloat = 40
    private let rowSpacing: CGFloat = 2
    private var rowHeight: CGFloat { rowFrameHeight + rowSpacing }

    var body: some View {
        ScrollView {
            // VStack (not LazyVStack): we need `zIndex` to be honored so the
            // dragged card always paints on top of *all* siblings, not just
            // ones with a lower array index. LazyVStack doesn't reliably
            // respect zIndex — that produced the "card disappears behind
            // rows below it when dragging down" symptom.
            VStack(alignment: .leading, spacing: rowSpacing) {
                sectionHeader

                ForEach(projectManager.projects) { project in
                    ReorderableRow(
                        project: project,
                        isDragging: draggingID == project.id,
                        offset: draggingID == project.id ? dragOffset : 0,
                        height: rowFrameHeight
                    )
                    .contentShape(Rectangle())
                    .simultaneousGesture(rowGesture(for: project))
                    .zIndex(draggingID == project.id ? 1000 : 0)
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

    private func rowGesture(for project: Project) -> some Gesture {
        // `coordinateSpace: .global` is critical. With the default `.local`,
        // the gesture is anchored to the row's frame — and since we move that
        // frame with `.offset(y:)` to follow the cursor, `translation` ends
        // up cancelling out the offset and reporting ~0. The row never moves,
        // no swap threshold is ever crossed, no reorder happens. Global gives
        // us real screen-pixel motion that's independent of view shifting.
        LongPressGesture(minimumDuration: 0.35)
            .sequenced(before: DragGesture(minimumDistance: 0, coordinateSpace: .global))
            .onChanged { value in
                switch value {
                case .first:
                    break
                case .second(let pressed, let drag):
                    guard pressed, let drag = drag else { return }
                    if draggingID != project.id {
                        beginDrag(for: project)
                    }
                    updateDrag(translation: drag.translation.height)
                }
            }
            .onEnded { _ in
                endDrag()
            }
    }

    private func beginDrag(for project: Project) {
        guard let idx = projectManager.projects.firstIndex(where: { $0.id == project.id }) else { return }
        dragStartIndex = idx
        dragOffset = 0
        withAnimation(.spring(response: 0.2, dampingFraction: 0.8)) {
            draggingID = project.id
        }
        NSHapticFeedbackManager.defaultPerformer.perform(.alignment, performanceTime: .now)
        NSCursor.closedHand.set()
    }

    private func updateDrag(translation: CGFloat) {
        guard let start = dragStartIndex,
              let currentID = draggingID,
              let currentIdx = projectManager.projects.firstIndex(where: { $0.id == currentID })
        else { return }

        // `lookahead` = cursor's vertical distance from the dragged row's
        // CURRENT slot center, in screen pixels. Equivalent to the dragOffset
        // we want with no further swap.
        var lookahead = CGFloat(start - currentIdx) * rowHeight + translation

        // Hysteresis: swap one slot at a time, but only when the cursor has
        // travelled a full rowHeight past the dragged row's current center.
        // Each swap moves the slot under the cursor, so `lookahead` drops
        // back near zero — the next swap requires another full row of travel.
        var newIdx = currentIdx
        while lookahead > rowHeight && newIdx < projectManager.projects.count - 1 {
            newIdx += 1
            lookahead -= rowHeight
        }
        while lookahead < -rowHeight && newIdx > 0 {
            newIdx -= 1
            lookahead += rowHeight
        }

        if newIdx != currentIdx {
            // Snap the reorder — no `withAnimation`. Animating it caused the
            // dragged row to drift off-cursor for the 300 ms spring duration
            // before settling: "position fighting".
            let item = projectManager.projects.remove(at: currentIdx)
            projectManager.projects.insert(item, at: newIdx)
        }

        dragOffset = lookahead
    }

    private func endDrag() {
        guard draggingID != nil else { return }
        let didMove: Bool = {
            guard let start = dragStartIndex,
                  let currentID = draggingID,
                  let endIdx = projectManager.projects.firstIndex(where: { $0.id == currentID })
            else { return false }
            return start != endIdx
        }()
        withAnimation(.spring(response: 0.3, dampingFraction: 0.85)) {
            dragOffset = 0
            draggingID = nil
        }
        dragStartIndex = nil
        NSCursor.arrow.set()
        if didMove {
            projectManager.persistAfterReorder()
        }
    }
}

/// Wraps `ProjectRow` (with all its built-in actions/buttons) and adds the
/// reorder visual: a "card lift" while dragging, plus a y-offset that the
/// parent drives directly. Pinned height makes slot math deterministic.
private struct ReorderableRow: View {
    let project: Project
    let isDragging: Bool
    let offset: CGFloat
    let height: CGFloat

    var body: some View {
        ProjectRow(project: project)
            .padding(.horizontal, 6)
            .frame(height: height, alignment: .center)
            .background(
                // Layered: opaque window-background base hides the row(s)
                // the card flies over, with an accent tint on top so the
                // card still reads as "the active one being dragged".
                // `.regularMaterial` was translucent and let underlying
                // rows' text bleed through.
                ZStack {
                    RoundedRectangle(cornerRadius: 6)
                        .fill(Color(NSColor.windowBackgroundColor))
                    RoundedRectangle(cornerRadius: 6)
                        .fill(Color.accentColor.opacity(0.18))
                }
                .opacity(isDragging ? 1 : 0)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 6)
                    .strokeBorder(Color.accentColor.opacity(isDragging ? 0.7 : 0), lineWidth: 1.5)
            )
            .scaleEffect(isDragging ? 1.03 : 1.0)
            .shadow(color: .black.opacity(isDragging ? 0.35 : 0), radius: 12, x: 0, y: 6)
            .offset(y: offset)
    }
}
