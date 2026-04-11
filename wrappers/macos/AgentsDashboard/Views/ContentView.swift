import SwiftUI

struct ContentView: View {
    @EnvironmentObject var projectManager: ProjectManager

    var body: some View {
        NavigationSplitView {
            SidebarView()
        } detail: {
            DashboardTabsView()
        }
        .sheet(isPresented: $projectManager.showAddProject) {
            AddProjectSheet()
        }
    }
}
