import Foundation

struct Project: Identifiable, Codable, Hashable {
    let id: UUID
    var name: String
    var path: String

    init(id: UUID = UUID(), name: String, path: String) {
        self.id = id
        self.name = name
        self.path = path
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

    var url: URL? {
        guard let port = port else { return nil }
        return URL(string: "http://127.0.0.1:\(port)")
    }
}
