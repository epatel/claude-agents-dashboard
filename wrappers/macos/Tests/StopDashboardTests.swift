import XCTest
@testable import AgentsDashboard

/// Stops a real server process (a fake `run.sh`) through `stopDashboard`.
final class StopDashboardTests: XCTestCase {
    private var serverDir: URL!

    override func setUpWithError() throws {
        serverDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("stop-dashboard-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: serverDir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: serverDir)
    }

    /// A fake run.sh: prints "ready", then runs until signalled as the script says.
    private func writeRunSh(_ signalHandling: String) throws {
        let script = """
        #!/bin/bash
        \(signalHandling)
        echo ready
        while true; do sleep 0.1; done
        """
        try script.write(to: serverDir.appendingPathComponent("run.sh"), atomically: true, encoding: .utf8)
    }

    /// Spin the main run loop until `condition` holds or `timeout` seconds pass.
    private func waitUntil(timeout: TimeInterval, _ condition: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while !condition() && Date() < deadline {
            RunLoop.main.run(until: Date().addingTimeInterval(0.05))
        }
        return condition()
    }

    /// Launch the fake server through the real launch path; returns the manager and tab id.
    private func launchFakeServer() throws -> (ProjectManager, UUID) {
        let manager = ProjectManager()
        manager.serverManager._serverURLOverride = serverDir
        let project = Project(name: "fake", path: serverDir.path)
        let instance = DashboardInstance(id: UUID(), project: project, status: .running)
        manager.dashboards.append(instance)
        manager.launchProcess(for: instance)
        let started = waitUntil(timeout: 10) {
            manager.dashboards.first?.outputLog.contains("ready") == true
        }
        XCTAssertTrue(started, "fake server did not start")
        return (manager, instance.id)
    }

    private func assertStoppedCleanly(_ manager: ProjectManager, file: StaticString = #filePath, line: UInt = #line) {
        let dashboard = manager.dashboards.first
        XCTAssertEqual(dashboard?.status, .stopped, file: file, line: line)
        XCTAssertNil(dashboard?.errorMessage, file: file, line: line)
        XCTAssertNil(dashboard?.process, file: file, line: line)
    }

    /// Launch a fake server with `signalHandling`, stop it, wait for it to exit within
    /// `exitTimeout`, then let pending callbacks run for `settle` seconds.
    private func stopFakeServer(_ signalHandling: String, exitTimeout: TimeInterval, settle: TimeInterval) throws -> ProjectManager {
        try writeRunSh(signalHandling)
        let (manager, id) = try launchFakeServer()
        let process = try XCTUnwrap(manager.dashboards.first?.process)

        manager.stopDashboard(id: id)
        XCTAssertTrue(waitUntil(timeout: exitTimeout) { !process.isRunning }, "server did not exit")
        _ = waitUntil(timeout: settle) { false }
        return manager
    }

    func testStopEndsStoppedWhenServerExitsOnSIGTERM() throws {
        // Settle past the 5 s cleanup, so the termination handler and the cleanup both run.
        assertStoppedCleanly(try stopFakeServer("trap 'exit 143' TERM", exitTimeout: 3, settle: 6.5))
    }

    /// The server ignores SIGTERM, so the 5 s fallback sends SIGINT; the server then takes a
    /// moment to exit, after the cleanup has already marked the tab stopped.
    func testStopEndsStoppedWhenServerIgnoresSIGTERM() throws {
        let manager = try stopFakeServer("trap '' TERM\ntrap 'sleep 0.5; exit 0' INT", exitTimeout: 9, settle: 1)
        assertStoppedCleanly(manager)
    }

    func testUnexpectedExitIsAnError() throws {
        try writeRunSh("")
        let (manager, _) = try launchFakeServer()
        let process = try XCTUnwrap(manager.dashboards.first?.process)

        kill(process.processIdentifier, SIGKILL)
        XCTAssertTrue(waitUntil(timeout: 3) { manager.dashboards.first?.status == .error })
        XCTAssertNotNil(manager.dashboards.first?.errorMessage)
    }
}
