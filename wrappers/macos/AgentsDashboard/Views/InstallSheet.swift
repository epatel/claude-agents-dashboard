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

            SheetActions(onCancel: cancel, confirmTitle: "Recheck", isDefaultAction: false, onConfirm: recheckClaude)
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
                Label("On first launch, create a Python 3.12+ environment and install dependencies (shown in the startup log)", systemImage: "2.circle")
            }
            .font(.callout)
            .foregroundColor(.secondary)

            SheetActions(onCancel: cancel, confirmTitle: "Install", confirmDisabled: !canInstall, onConfirm: install)
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
                statusRows(for: status)
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(nsColor: .controlBackgroundColor))
        .cornerRadius(10)
    }

    @ViewBuilder
    private func statusRows(for status: ClaudeCLIStatus) -> some View {
        switch status {
        case .installed(let version, let loggedIn, let outdated):
            statusLine(outdated ? "exclamationmark.triangle.fill" : "checkmark.circle.fill",
                       iconColor: outdated ? .orange : .green, text: "Claude CLI \(version)", textColor: .secondary)
            if outdated {
                fixRow("arrow.up.circle.fill", color: .orange,
                       message: "Requires \(ServerManager.minimumClaudeCLIVersion)+ — upgrade with:",
                       command: "claude update")
            }
            if loggedIn {
                statusLine("checkmark.circle.fill", iconColor: .green, text: "Logged in", textColor: .secondary)
            } else {
                fixRow("xmark.circle.fill", color: .red,
                       message: "Not logged in — run this in Terminal:", command: "claude auth login")
            }
        case .notInstalled:
            fixRow("xmark.circle.fill", color: .red, message: "Claude CLI not found — install it:",
                   command: "curl -fsSL https://claude.ai/install.sh | bash")
        case .error(let msg):
            statusLine("exclamationmark.triangle.fill", iconColor: .orange, text: msg, textColor: .orange)
        }
    }

    /// An icon and a line of text.
    private func statusLine(_ systemImage: String, iconColor: Color, text: String, textColor: Color) -> some View {
        HStack(spacing: 8) {
            Image(systemName: systemImage)
                .foregroundColor(iconColor)
            Text(text)
                .font(.callout)
                .foregroundColor(textColor)
        }
    }

    /// A problem line with a Retry button, and the command that fixes it.
    private func fixRow(_ systemImage: String, color: Color, message: String, command: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: systemImage)
                    .foregroundColor(color)
                Text(message)
                    .font(.callout)
                    .foregroundColor(color)
                Spacer()
                retryButton
            }
            commandRow(command)
        }
    }

    private var retryButton: some View {
        Button {
            recheckClaude()
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

            SheetActions(onCancel: cancel, confirmTitle: "Retry", isDefaultAction: false, onConfirm: install)
        }
    }

    // MARK: - Actions

    private func cancel() {
        projectManager.showInstallSheet = false
        projectManager.pendingProject = nil
    }

    /// Check the Claude CLI again; once it is ready, close the sheet and start the waiting project.
    private func recheckClaude() {
        Task {
            isCheckingClaude = true
            claudeStatus = await serverManager.checkClaudeCLI(userPATH: projectManager.resolvedUserPATH)
            isCheckingClaude = false

            if claudeStatus?.isReady == true {
                projectManager.showInstallSheet = false
                startPendingProject()
            }
        }
    }

    private func startPendingProject() {
        if let project = projectManager.pendingProject {
            projectManager.pendingProject = nil
            projectManager.startDashboard(for: project)
        }
    }

    private func install() {
        isInstalling = true
        Task {
            do {
                try await serverManager.clone()
                await MainActor.run {
                    isInstalling = false
                    projectManager.showInstallSheet = false
                    startPendingProject()
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
