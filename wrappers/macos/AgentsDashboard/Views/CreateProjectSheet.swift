import SwiftUI

struct CreateProjectSheet: View {
    @EnvironmentObject var projectManager: ProjectManager
    @State private var projectName: String = ""
    @State private var parentPath: String = ""
    @State private var errorMessage: String?

    var body: some View {
        VStack(spacing: 20) {
            SheetHeader(
                systemImage: "plus.rectangle.on.folder",
                title: "Create New Project",
                message: "Create a new git repository to manage with Agents Dashboard"
            )

            // Project name
            SheetField(title: "Project Name") {
                TextField("my-project", text: $projectName)
                    .textFieldStyle(.roundedBorder)
            }

            // Parent directory
            SheetField(title: "Location") {
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

            SheetActions(
                onCancel: { projectManager.showCreateProject = false },
                confirmTitle: "Create Project",
                confirmDisabled: projectName.isEmpty || parentPath.isEmpty,
                onConfirm: createProject
            )
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
        let projectURL = URL(fileURLWithPath: parent).appendingPathComponent(name)
        let projectPath = projectURL.path

        if let problem = validationError(name: name, parent: parent, projectPath: projectPath) {
            errorMessage = problem
            return
        }

        // Create directory
        do {
            try FileManager.default.createDirectory(at: projectURL, withIntermediateDirectories: true)
        } catch {
            errorMessage = "Failed to create directory: \(error.localizedDescription)"
            return
        }

        if let problem = CreateProjectSheet.initRepository(at: projectURL) {
            errorMessage = problem
            return
        }

        // Add to project manager
        projectManager.addProject(path: projectPath)
        projectManager.showCreateProject = false
    }

    /// Why a project named ``name`` cannot be created under ``parent`` (nil when it can).
    private func validationError(name: String, parent: String, projectPath: String) -> String? {
        guard !name.isEmpty else {
            return "Project name cannot be empty"
        }

        // Validate no path-unsafe characters
        let invalidChars = CharacterSet(charactersIn: "/\\:")
        if name.unicodeScalars.contains(where: { invalidChars.contains($0) }) {
            return "Project name contains invalid characters"
        }

        // Validate parent exists
        var isDir: ObjCBool = false
        guard FileManager.default.fileExists(atPath: parent, isDirectory: &isDir), isDir.boolValue else {
            return "Parent directory does not exist"
        }

        // Check it doesn't already exist
        if FileManager.default.fileExists(atPath: projectPath) {
            return "A file or directory named \"\(name)\" already exists at this location"
        }

        // Check if already in project list
        if projectManager.projects.contains(where: { $0.path == projectPath }) {
            return "This project is already added"
        }
        return nil
    }

    /// `git init -b main` in ``projectURL`` plus an initial commit of an empty README and a
    /// .gitignore for agents-lab/. Returns an error message when git init fails.
    static func initRepository(at projectURL: URL) -> String? {
        let process = gitProcess(["init", "-b", "main"], in: projectURL)
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            return "Failed to initialize git repository: \(error.localizedDescription)"
        }

        guard process.terminationStatus == 0 else {
            return "git init failed with exit code \(process.terminationStatus)"
        }

        // Create an initial commit with an empty README and .gitignore
        let readmeURL = projectURL.appendingPathComponent("README.md")
        FileManager.default.createFile(atPath: readmeURL.path, contents: Data())

        let gitignoreURL = projectURL.appendingPathComponent(".gitignore")
        try? "agents-lab/\n".data(using: .utf8)?.write(to: gitignoreURL)

        for arguments in [["add", "README.md", ".gitignore"], ["commit", "-m", "Initial commit"]] {
            let step = gitProcess(arguments, in: projectURL)
            try? step.run()
            step.waitUntilExit()
        }
        return nil
    }

    /// A /usr/bin/git process in ``directory`` with its output discarded.
    private static func gitProcess(_ arguments: [String], in directory: URL) -> Process {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/git")
        process.arguments = arguments
        process.currentDirectoryURL = directory
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        return process
    }
}
