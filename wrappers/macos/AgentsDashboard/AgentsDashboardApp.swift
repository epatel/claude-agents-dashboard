import SwiftUI

@main
struct AgentsDashboardApp: App {
    @StateObject private var projectManager = ProjectManager()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(projectManager)
                .frame(minWidth: 900, minHeight: 600)
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
