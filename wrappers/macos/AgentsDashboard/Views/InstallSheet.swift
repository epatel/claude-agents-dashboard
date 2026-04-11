import SwiftUI

struct InstallSheet: View {
    @EnvironmentObject var projectManager: ProjectManager
    @ObservedObject var serverManager: ServerManager
    @State private var isInstalling = false

    var body: some View {
        VStack(spacing: 20) {
            if isInstalling {
                progressContent
            } else if let error = serverManager.installError {
                errorContent(error)
            } else {
                promptContent
            }
        }
        .padding(24)
        .frame(width: 460)
    }

    // MARK: - Prompt

    private var promptContent: some View {
        VStack(spacing: 16) {
            Image(systemName: "arrow.down.circle")
                .font(.system(size: 36))
                .foregroundColor(.accentColor)

            Text("Agents Dashboard Server Required")
                .font(.title2)
                .fontWeight(.semibold)

            Text("The dashboard server is not installed. This will clone the repository into ~/.agents-dashboard/ and set up a Python virtual environment.")
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)

            HStack {
                Button("Cancel") {
                    projectManager.showInstallSheet = false
                    projectManager.pendingProject = nil
                }
                .keyboardShortcut(.cancelAction)

                Spacer()

                Button("Install") {
                    install()
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
            }
        }
    }

    // MARK: - Progress

    private var progressContent: some View {
        VStack(spacing: 16) {
            ProgressView()
                .controlSize(.large)

            Text(stageText)
                .font(.title3)
                .foregroundColor(.secondary)
        }
    }

    private var stageText: String {
        switch serverManager.installStage {
        case .cloning: return "Cloning repository..."
        case .creatingVenv: return "Setting up Python environment..."
        case .installingDeps: return "Installing dependencies..."
        case .done: return "Done!"
        case nil: return "Preparing..."
        }
    }

    // MARK: - Error

    private func errorContent(_ error: String) -> some View {
        VStack(spacing: 16) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 36))
                .foregroundColor(.red)

            Text("Installation Failed")
                .font(.title2)
                .fontWeight(.semibold)

            Text(error)
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)

            HStack {
                Button("Cancel") {
                    projectManager.showInstallSheet = false
                    projectManager.pendingProject = nil
                }
                .keyboardShortcut(.cancelAction)

                Spacer()

                Button("Retry") {
                    install()
                }
                .buttonStyle(.borderedProminent)
            }
        }
    }

    // MARK: - Actions

    private func install() {
        isInstalling = true
        Task {
            do {
                try await serverManager.clone()
                await MainActor.run {
                    isInstalling = false
                    projectManager.showInstallSheet = false
                    // Resume the pending dashboard start
                    if let project = projectManager.pendingProject {
                        projectManager.pendingProject = nil
                        projectManager.startDashboard(for: project)
                    }
                }
            } catch {
                await MainActor.run {
                    isInstalling = false
                    serverManager.installError = error.localizedDescription
                }
            }
        }
    }
}
