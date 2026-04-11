import SwiftUI

struct AddProjectSheet: View {
    @EnvironmentObject var projectManager: ProjectManager
    @State private var projectPath: String = ""
    @State private var errorMessage: String?
    @State private var recentPaths: [String] = []

    var body: some View {
        VStack(spacing: 20) {
            // Header
            VStack(spacing: 4) {
                Image(systemName: "folder.badge.plus")
                    .font(.system(size: 36))
                    .foregroundColor(.accentColor)

                Text("Add Project")
                    .font(.title2)
                    .fontWeight(.semibold)

                Text("Select a git repository to manage with Agents Dashboard")
                    .font(.body)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
            }

            // Path input
            VStack(alignment: .leading, spacing: 8) {
                Text("Project Path")
                    .font(.headline)

                HStack {
                    TextField("/path/to/your/project", text: $projectPath)
                        .textFieldStyle(.roundedBorder)

                    Button("Browse...") {
                        browseForProject()
                    }
                }

                if let error = errorMessage {
                    Text(error)
                        .font(.caption)
                        .foregroundColor(.red)
                }
            }

            // Quick add from recent
            if !existingProjectSuggestions.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Suggestions")
                        .font(.headline)

                    ForEach(existingProjectSuggestions, id: \.self) { path in
                        Button(action: {
                            projectPath = path
                        }) {
                            HStack {
                                Image(systemName: "folder")
                                    .foregroundColor(.secondary)
                                Text(URL(fileURLWithPath: path).lastPathComponent)
                                    .font(.body)
                                Spacer()
                                Text(path)
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                                    .lineLimit(1)
                                    .truncationMode(.head)
                            }
                            .padding(.vertical, 4)
                            .padding(.horizontal, 8)
                            .background(Color(nsColor: .controlBackgroundColor))
                            .cornerRadius(6)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }

            // Actions
            HStack {
                Button("Cancel") {
                    projectManager.showAddProject = false
                }
                .keyboardShortcut(.cancelAction)

                Spacer()

                Button("Add Project") {
                    addProject()
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(projectPath.isEmpty)
            }
        }
        .padding(24)
        .frame(width: 500)
        .onAppear {
            loadRecentPaths()
        }
    }

    private var existingProjectSuggestions: [String] {
        // Filter out already-added projects
        let existingPaths = Set(projectManager.projects.map(\.path))
        return recentPaths.filter { !existingPaths.contains($0) }
    }

    private func browseForProject() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.message = "Select a git repository"
        panel.prompt = "Select"

        if panel.runModal() == .OK, let url = panel.url {
            projectPath = url.path
        }
    }

    private func addProject() {
        let path = projectPath.trimmingCharacters(in: .whitespacesAndNewlines)

        // Validate path exists
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: path, isDirectory: &isDir), isDir.boolValue else {
            errorMessage = "Directory does not exist"
            return
        }

        // Validate it's a git repo
        let gitDir = URL(fileURLWithPath: path).appendingPathComponent(".git")
        guard FileManager.default.fileExists(atPath: gitDir.path) else {
            errorMessage = "Not a git repository (no .git directory found)"
            return
        }

        // Check if already added
        if projectManager.projects.contains(where: { $0.path == path }) {
            errorMessage = "This project is already added"
            return
        }

        projectManager.addProject(path: path)
        projectManager.showAddProject = false
    }

    private func loadRecentPaths() {
        // Try to find git repos in common locations
        let home = FileManager.default.homeDirectoryForCurrentUser
        let searchDirs = [
            home.appendingPathComponent("Developer"),
            home.appendingPathComponent("Development"),
            home.appendingPathComponent("Projects"),
            home.appendingPathComponent("Code"),
            home.appendingPathComponent("src"),
        ]

        var found: [String] = []
        for dir in searchDirs {
            guard let contents = try? FileManager.default.contentsOfDirectory(
                at: dir, includingPropertiesForKeys: [.isDirectoryKey],
                options: [.skipsHiddenFiles]
            ) else { continue }

            for item in contents.prefix(10) {
                let gitDir = item.appendingPathComponent(".git")
                if FileManager.default.fileExists(atPath: gitDir.path) {
                    found.append(item.path)
                }
            }
        }

        recentPaths = Array(found.prefix(5))
    }
}
