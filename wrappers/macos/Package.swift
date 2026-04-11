// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "AgentsDashboard",
    platforms: [
        .macOS(.v14)
    ],
    targets: [
        .executableTarget(
            name: "AgentsDashboard",
            path: "AgentsDashboard",
            exclude: ["Info.plist", "AgentsDashboard.entitlements"]
        )
    ]
)
