import SwiftUI

struct CreateProjectSheet: View {
    @EnvironmentObject var projectManager: ProjectManager
    @State private var projectName: String = ""
    @State private var parentPath: String = ""
    @State private var errorMessage: String?

    var body: some View {
        VStack(spacing: 20) {
            // Header
            VStack(spacing: 4) {
                Image(systemName: "plus.rectangle.on.folder")
                    .font(.system(size: 36))
                    .foregroundColor(.accentColor)

                Text("Create New Project")
                    .font(.title2)
                    .fontWeight(.semibold)

                Text("Create a new git repository to manage with Agents Dashboard")
                    .font(.body)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
            }

            // Project name
            VStack(alignment: .leading, spacing: 8) {
                Text("Project Name")
                    .font(.headline)

                TextField("my-project", text: $projectName)
                    .textFieldStyle(.roundedBorder)
            }

            // Parent directory
            VStack(alignment: .leading, spacing: 8) {
                Text("Location")
                    .font(.headline)

                HStack {
                    TextField("~/Development", text: $parentPath)
                        .textFieldStyle(.roundedBorder)

                    Button("Browse...") {
                        browseForLocation()
                    }
                }

                if !projectName.isEmpty && !parentPath.isEmpty {
                    Text("Will create: \(fullProjectPath)")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }

            if let error = errorMessage {
                Text(error)
                    .font(.caption)
                    .foregroundColor(.red)
            }

            // Actions
            HStack {
                Button("Cancel") {
                    projectManager.showCreateProject = false
                }
                .keyboardShortcut(.cancelAction)

                Spacer()

                Button("Create Project") {
                    createProject()
                }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(projectName.isEmpty || parentPath.isEmpty)
            }
        }
        .padding(24)
        .frame(width: 500)
        .onAppear {
            setDefaultLocation()
        }
    }

    private var fullProjectPath: String {
        URL(fileURLWithPath: parentPath).appendingPathComponent(projectName).path
    }

    private func setDefaultLocation() {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let candidates = ["Development", "Developer", "Projects", "Code", "src"]
        for dir in candidates {
            let path = home.appendingPathComponent(dir)
            var isDir: ObjCBool = false
            if FileManager.default.fileExists(atPath: path.path, isDirectory: &isDir), isDir.boolValue {
                parentPath = path.path
                return
            }
        }
        parentPath = home.path
    }

    private func browseForLocation() {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.message = "Select parent directory for the new project"
        panel.prompt = "Select"

        if !parentPath.isEmpty {
            panel.directoryURL = URL(fileURLWithPath: parentPath)
        }

        if panel.runModal() == .OK, let url = panel.url {
            parentPath = url.path
        }
    }

    private func createProject() {
        let name = projectName.trimmingCharacters(in: .whitespacesAndNewlines)
        let parent = parentPath.trimmingCharacters(in: .whitespacesAndNewlines)

        guard !name.isEmpty else {
            errorMessage = "Project name cannot be empty"
            return
        }

        // Validate no path-unsafe characters
        let invalidChars = CharacterSet(charactersIn: "/\\:")
        if name.unicodeScalars.contains(where: { invalidChars.contains($0) }) {
            errorMessage = "Project name contains invalid characters"
            return
        }

        // Validate parent exists
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: parent, isDirectory: &isDir), isDir.boolValue else {
            errorMessage = "Parent directory does not exist"
            return
        }

        let projectURL = URL(fileURLWithPath: parent).appendingPathComponent(name)
        let projectPath = projectURL.path

        // Check it doesn't already exist
        if FileManager.default.fileExists(atPath: projectPath) {
            errorMessage = "A file or directory named \"\(name)\" already exists at this location"
            return
        }

        // Check if already in project list
        if projectManager.projects.contains(where: { $0.path == projectPath }) {
            errorMessage = "This project is already added"
            return
        }

        // Create directory
        do {
            try FileManager.default.createDirectory(at: projectURL, withIntermediateDirectories: true)
        } catch {
            errorMessage = "Failed to create directory: \(error.localizedDescription)"
            return
        }

        // git init
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/git")
        process.arguments = ["init", "-b", "main"]
        process.currentDirectoryURL = projectURL
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice

        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            errorMessage = "Failed to initialize git repository: \(error.localizedDescription)"
            return
        }

        guard process.terminationStatus == 0 else {
            errorMessage = "git init failed with exit code \(process.terminationStatus)"
            return
        }

        // Create an initial commit with an empty README
        let readmeURL = projectURL.appendingPathComponent("README.md")
        FileManager.default.createFile(atPath: readmeURL.path, contents: Data())

        let addProcess = Process()
        addProcess.executableURL = URL(fileURLWithPath: "/usr/bin/git")
        addProcess.arguments = ["add", "README.md"]
        addProcess.currentDirectoryURL = projectURL
        addProcess.standardOutput = FileHandle.nullDevice
        addProcess.standardError = FileHandle.nullDevice
        try? addProcess.run()
        addProcess.waitUntilExit()

        let commitProcess = Process()
        commitProcess.executableURL = URL(fileURLWithPath: "/usr/bin/git")
        commitProcess.arguments = ["commit", "-m", "Initial commit"]
        commitProcess.currentDirectoryURL = projectURL
        commitProcess.standardOutput = FileHandle.nullDevice
        commitProcess.standardError = FileHandle.nullDevice
        try? commitProcess.run()
        commitProcess.waitUntilExit()

        // Add to project manager
        projectManager.addProject(path: projectPath)
        projectManager.showCreateProject = false
    }
}
