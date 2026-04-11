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
        .sheet(isPresented: $projectManager.showInstallSheet) {
            InstallSheet(serverManager: projectManager.serverManager)
        }
        .task {
            // Check both server installation and Claude CLI on launch
            if !projectManager.serverManager.installationExists() {
                projectManager.showInstallSheet = true
            } else {
                let status = await projectManager.serverManager.checkClaudeCLI(userPATH: projectManager.resolvedUserPATH)
                if !status.isReady {
                    projectManager.showInstallSheet = true
                }
            }
        }
    }
}
