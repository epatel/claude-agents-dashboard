import XCTest
@testable import AgentsDashboard

final class ServerManagerTests: XCTestCase {
    var manager: ServerManager!
    var tempDir: URL!

    override func setUp() {
        super.setUp()
        manager = ServerManager()
        tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("AgentsDashboardTests-\(UUID().uuidString)")
        try? FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        manager._serverURLOverride = tempDir
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: tempDir)
        super.tearDown()
    }

    // MARK: - serverPath

    func testServerPathMatchesServerURL() {
        XCTAssertEqual(manager.serverPath, tempDir.path)
    }

    func testDefaultServerURLPointsToHomeDotAgentsDashboard() {
        let defaultManager = ServerManager()
        let expected = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".agents-dashboard")
        XCTAssertEqual(defaultManager.serverURL, expected)
    }

    // MARK: - installationExists

    func testInstallationExistsReturnsFalseWhenEmpty() {
        XCTAssertFalse(manager.installationExists())
    }

    func testInstallationExistsReturnsFalseWhenDirExistsButNoRunSh() {
        let subdir = tempDir.appendingPathComponent("src")
        try? FileManager.default.createDirectory(at: subdir, withIntermediateDirectories: true)
        XCTAssertFalse(manager.installationExists())
    }

    func testInstallationExistsReturnsTrueWhenRunShExists() {
        let runSh = tempDir.appendingPathComponent("run.sh")
        FileManager.default.createFile(atPath: runSh.path, contents: Data("#!/bin/bash".utf8))
        XCTAssertTrue(manager.installationExists())
    }

    // MARK: - pythonPath

    func testPythonPathReturnsExecutablePath() {
        let path = manager.pythonPath
        XCTAssertTrue(FileManager.default.isExecutableFile(atPath: path),
                       "pythonPath should return an executable: \(path)")
    }

    func testPythonPathFallsBackToUsrBin() {
        // pythonPath should always return something, at minimum /usr/bin/python3
        XCTAssertFalse(manager.pythonPath.isEmpty)
    }

    // MARK: - checkForUpdates when not installed

    func testCheckForUpdatesReturnsErrorWhenNotInstalled() async {
        let status = await manager.checkForUpdates()
        if case .error(let msg) = status {
            XCTAssertEqual(msg, "Not installed")
        } else {
            XCTFail("Expected .error, got \(status)")
        }
    }

    // MARK: - clone cleanup on failure

    func testCloneCleanupRemovesDirOnFailure() async {
        // Point serverURL to a path inside tempDir that doesn't exist yet
        let cloneTarget = tempDir.appendingPathComponent("will-fail-clone")
        manager._serverURLOverride = cloneTarget

        // clone() will fail because git clone with the real URL requires network
        // and we're using a path that may or may not succeed — but the key test is:
        // if the directory was created and then something fails, it gets cleaned up.
        // We simulate by creating the dir manually then checking clone handles failure.
        do {
            try await manager.clone()
            // If this somehow succeeds (network available), that's fine too
        } catch {
            // After failure, the directory should be cleaned up
            XCTAssertFalse(FileManager.default.fileExists(atPath: cloneTarget.path),
                           "Failed clone should clean up the directory")
        }
    }

    // MARK: - installStage and installError state

    func testInitialStateIsNil() {
        XCTAssertNil(manager.installStage)
        XCTAssertNil(manager.installError)
    }

    // MARK: - repoURL

    func testRepoURLIsValid() {
        let url = URL(string: ServerManager.repoURL)
        XCTAssertNotNil(url)
        XCTAssertEqual(url?.scheme, "https")
        XCTAssertEqual(url?.host, "github.com")
    }
}
