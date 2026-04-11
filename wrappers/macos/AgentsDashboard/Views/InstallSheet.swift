import SwiftUI
import AppKit

struct InstallSheet: View {
    @EnvironmentObject var projectManager: ProjectManager
    @ObservedObject var serverManager: ServerManager
    @State private var isInstalling = false
    @State private var claudeStatus: ClaudeCLIStatus?
    @State private var isCheckingClaude = true
    @State private var copiedCommand: String?

    private var needsInstallation: Bool {
        !serverManager.installationExists()
    }

    var body: some View {
        VStack(spacing: 24) {
            if isInstalling {
                progressContent
            } else if let error = serverManager.installError {
                errorContent(error)
            } else if needsInstallation {
                installPromptContent
            } else {
                claudeOnlyContent
            }
        }
        .padding(32)
        .frame(width: 540)
        .task {
            isCheckingClaude = true
            claudeStatus = await serverManager.checkClaudeCLI(userPATH: projectManager.resolvedUserPATH)
            isCheckingClaude = false
        }
    }

    // MARK: - Command Row with Copy Button

    private func commandRow(_ command: String) -> some View {
        HStack(spacing: 0) {
            Text(command)
                .font(.system(.callout, design: .monospaced))
                .foregroundColor(.primary)
                .lineLimit(1)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)

            Spacer()

            Button {
                NSPasteboard.general.clearContents()
                NSPasteboard.general.setString(command, forType: .string)
                copiedCommand = command
                DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
                    if copiedCommand == command { copiedCommand = nil }
                }
            } label: {
                Image(systemName: copiedCommand == command ? "checkmark" : "doc.on.doc")
                    .font(.callout)
                    .foregroundColor(copiedCommand == command ? .green : .secondary)
                    .frame(width: 32, height: 32)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .help(copiedCommand == command ? "Copied!" : "Copy to clipboard")
            .padding(.trailing, 8)
        }
        .background(Color(nsColor: .controlBackgroundColor))
        .cornerRadius(8)
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(Color(nsColor: .separatorColor), lineWidth: 1)
        )
    }

    // MARK: - Claude-Only Content (server installed, Claude not ready)

    private var claudeOnlyContent: some View {
        VStack(spacing: 20) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 40))
                .foregroundColor(.orange)

            Text("Claude CLI Setup Required")
                .font(.title2)
                .fontWeight(.semibold)

            Text("The dashboard server is installed, but Claude CLI needs to be set up before you can start.")
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)

            claudeStatusSection

            Divider()

            HStack {
                Button("Cancel") {
                    projectManager.showInstallSheet = false
                    projectManager.pendingProject = nil
                }
                .keyboardShortcut(.cancelAction)

                Spacer()

                Button("Recheck") {
                    Task {
                        isCheckingClaude = true
                        claudeStatus = await serverManager.checkClaudeCLI(userPATH: projectManager.resolvedUserPATH)
                        isCheckingClaude = false

                        if claudeStatus?.isReady == true {
                            projectManager.showInstallSheet = false
                            if let project = projectManager.pendingProject {
                                projectManager.pendingProject = nil
                                projectManager.startDashboard(for: project)
                            }
                        }
                    }
                }
                .buttonStyle(.borderedProminent)
            }
        }
    }

    // MARK: - Install Prompt Content

    private var installPromptContent: some View {
        VStack(spacing: 20) {
            Image(systemName: "arrow.down.circle")
                .font(.system(size: 40))
                .foregroundColor(.accentColor)

            Text("Agents Dashboard Server Required")
                .font(.title2)
                .fontWeight(.semibold)

            Text("The dashboard server needs to be installed before you can start managing projects. This is a one-time setup.")
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)

            claudeStatusSection

            Divider()

            VStack(alignment: .leading, spacing: 10) {
                Text("Installation steps")
                    .font(.callout)
                    .fontWeight(.medium)

                Label("Clone the dashboard repository into ~/.agents-dashboard/", systemImage: "1.circle")
                Label("Create a Python virtual environment", systemImage: "2.circle")
                Label("Install Python dependencies (FastAPI, aiosqlite, etc.)", systemImage: "3.circle")
            }
            .font(.callout)
            .foregroundColor(.secondary)

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
                .disabled(!canInstall)
            }
        }
    }

    // MARK: - Claude Status Section

    private var claudeStatusSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Prerequisites")
                .font(.callout)
                .fontWeight(.medium)

            if isCheckingClaude {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("Checking Claude CLI...")
                        .font(.callout)
                        .foregroundColor(.secondary)
                }
            } else if let status = claudeStatus {
                switch status {
                case .installed(let version, let loggedIn):
                    HStack(spacing: 8) {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundColor(.green)
                        Text("Claude CLI \(version)")
                            .font(.callout)
                            .foregroundColor(.secondary)
                    }
                    if loggedIn {
                        HStack(spacing: 8) {
                            Image(systemName: "checkmark.circle.fill")
                                .foregroundColor(.green)
                            Text("Logged in")
                                .font(.callout)
                                .foregroundColor(.secondary)
                        }
                    } else {
                        VStack(alignment: .leading, spacing: 8) {
                            HStack(spacing: 8) {
                                Image(systemName: "xmark.circle.fill")
                                    .foregroundColor(.red)
                                Text("Not logged in — run this in Terminal:")
                                    .font(.callout)
                                    .foregroundColor(.red)
                                Spacer()
                                retryButton
                            }
                            commandRow("claude auth login")
                        }
                    }
                case .notInstalled:
                    VStack(alignment: .leading, spacing: 8) {
                        HStack(spacing: 8) {
                            Image(systemName: "xmark.circle.fill")
                                .foregroundColor(.red)
                            Text("Claude CLI not found — install it:")
                                .font(.callout)
                                .foregroundColor(.red)
                            Spacer()
                            retryButton
                        }
                        commandRow("curl -fsSL https://claude.ai/install.sh | bash")
                    }
                case .error(let msg):
                    HStack(spacing: 8) {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundColor(.orange)
                        Text(msg)
                            .font(.callout)
                            .foregroundColor(.orange)
                    }
                }
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(nsColor: .controlBackgroundColor))
        .cornerRadius(10)
    }

    private var retryButton: some View {
        Button {
            Task {
                isCheckingClaude = true
                claudeStatus = await serverManager.checkClaudeCLI(userPATH: projectManager.resolvedUserPATH)
                isCheckingClaude = false

                if claudeStatus?.isReady == true {
                    projectManager.showInstallSheet = false
                    if let project = projectManager.pendingProject {
                        projectManager.pendingProject = nil
                        projectManager.startDashboard(for: project)
                    }
                }
            }
        } label: {
            HStack(spacing: 4) {
                Image(systemName: "arrow.clockwise")
                Text("Retry")
            }
            .font(.callout)
        }
        .buttonStyle(.bordered)
        .controlSize(.small)
    }

    private var canInstall: Bool {
        guard let status = claudeStatus else { return false }
        return status.isReady
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
                .font(.system(size: 40))
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
