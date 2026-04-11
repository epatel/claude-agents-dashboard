import SwiftUI
import AppKit

@main
struct AgentsDashboardApp: App {
    @StateObject private var projectManager = ProjectManager()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(projectManager)
                .frame(minWidth: 900, minHeight: 600)
                .onReceive(NotificationCenter.default.publisher(for: NSApplication.willTerminateNotification)) { _ in
                    // Stop all dashboards gracefully when the app quits.
                    // This calls the /api/shutdown endpoint on each server
                    // to clean up Claude agent processes before termination.
                    projectManager.stopAllDashboards()
                }
        }
        .windowStyle(.titleBar)
        .commands {
            CommandGroup(after: .newItem) {
                Button("Add Project...") {
                    projectManager.showAddProject = true
                }
                .keyboardShortcut("o", modifiers: [.command])
            }
        }
    }
}
