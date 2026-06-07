import Foundation

struct Project: Identifiable, Codable, Hashable {
    let id: UUID
    var name: String
    var path: String
    /// When true, this project's dashboard is launched with `--experimental`,
    /// which unlocks experimental features (e.g. the Ollama provider UI).
    /// Configured per-entry from the sidebar context menu.
    var experimental: Bool

    init(id: UUID = UUID(), name: String, path: String, experimental: Bool = false) {
        self.id = id
        self.name = name
        self.path = path
        self.experimental = experimental
    }

    // Custom decoding so projects persisted before `experimental` existed
    // (no key in the stored JSON) still decode, defaulting to false.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .id)
        name = try c.decode(String.self, forKey: .name)
        path = try c.decode(String.self, forKey: .path)
        experimental = try c.decodeIfPresent(Bool.self, forKey: .experimental) ?? false
    }
}

enum DashboardStatus: String, Codable {
    case stopped
    case starting
    case running
    case stopping
    case error
}

struct DashboardInstance: Identifiable {
    let id: UUID
    let project: Project
    var status: DashboardStatus
    var port: Int?
    var process: Process?
    var outputLog: String = ""
    var errorMessage: String?
    /// Number of items currently in the "questions" column (awaiting user input).
    /// Polled from /api/items while the dashboard is running.
    var questionsCount: Int = 0
    /// Number of items currently in the "review" column (awaiting approval).
    var reviewsCount: Int = 0

    var url: URL? {
        guard let port = port else { return nil }
        return URL(string: "http://127.0.0.1:\(port)")
    }
}
