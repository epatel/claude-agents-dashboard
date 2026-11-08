import XCTest
@testable import AgentsDashboard

final class ProjectManagerTests: XCTestCase {

    // MARK: - badgeCounts

    func testBadgeCountsCountsQuestionsAndReviews() {
        let items: [[String: Any]] = [
            ["column_name": "questions"], ["column_name": "questions"],
            ["column_name": "review"], ["column_name": "todo"],
        ]
        let counts = ProjectManager.badgeCounts(in: items)
        XCTAssertEqual(counts.questions, 2)
        XCTAssertEqual(counts.reviews, 1)
    }

    func testBadgeCountsSkipsItemsWithoutAStringColumn() {
        let counts = ProjectManager.badgeCounts(in: [["column_name": 5], ["title": "x"], [:]])
        XCTAssertEqual(counts.questions, 0)
        XCTAssertEqual(counts.reviews, 0)
    }

    // MARK: - serverPort

    func testServerPortFromStartupLine() {
        XCTAssertEqual(ProjectManager.serverPort(in: "Agents Dashboard running on http://127.0.0.1:8003\n"), 8003)
    }

    func testServerPortTakesTheFirstURL() {
        XCTAssertEqual(ProjectManager.serverPort(in: "at http://0.0.0.0:8000 and http://127.0.0.1:9000"), 8000)
    }

    func testServerPortIsNilWithoutAURL() {
        XCTAssertNil(ProjectManager.serverPort(in: "Installing dependencies…"))
        XCTAssertNil(ProjectManager.serverPort(in: "see https://example.com:443/docs"))
    }
}
