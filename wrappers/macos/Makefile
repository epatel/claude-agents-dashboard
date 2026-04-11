APP_NAME = AgentsDashboard
BUNDLE_NAME = Agents Dashboard.app
BUILD_DIR = .build
RELEASE_DIR = $(BUILD_DIR)/release
BIN_DIR = $(shell swift build -c release --show-bin-path 2>/dev/null || echo "$(BUILD_DIR)/arm64-apple-macosx/release")
DEBUG_DIR = $(BUILD_DIR)/arm64-apple-macosx/debug
INSTALL_DIR = /Applications

.PHONY: all build release run clean install uninstall

all: build

# Debug build
build:
	swift build

# Release build + .app bundle
release:
	swift build -c release
	@mkdir -p "$(RELEASE_DIR)/$(BUNDLE_NAME)/Contents/MacOS"
	@mkdir -p "$(RELEASE_DIR)/$(BUNDLE_NAME)/Contents/Resources"
	@cp $(BIN_DIR)/$(APP_NAME) "$(RELEASE_DIR)/$(BUNDLE_NAME)/Contents/MacOS/$(APP_NAME)"
	@cp $(APP_NAME)/Info.plist "$(RELEASE_DIR)/$(BUNDLE_NAME)/Contents/Info.plist"
	@cp $(APP_NAME)/AppIcon.icns "$(RELEASE_DIR)/$(BUNDLE_NAME)/Contents/Resources/"
	@cp $(APP_NAME)/$(APP_NAME).entitlements "$(RELEASE_DIR)/$(BUNDLE_NAME)/Contents/Resources/"
	@codesign --force --sign - --entitlements $(APP_NAME)/$(APP_NAME).entitlements "$(RELEASE_DIR)/$(BUNDLE_NAME)"
	@echo "Built: $(RELEASE_DIR)/$(BUNDLE_NAME)"

# Run debug build
run:
	swift run

# Remove build artifacts
clean:
	swift package clean
	rm -rf "$(RELEASE_DIR)/$(BUNDLE_NAME)"

# Copy .app to /Applications
install: release
	@cp -R "$(RELEASE_DIR)/$(BUNDLE_NAME)" "$(INSTALL_DIR)/$(BUNDLE_NAME)"
	@echo "Installed: $(INSTALL_DIR)/$(BUNDLE_NAME)"

# Remove from /Applications
uninstall:
	@rm -rf "$(INSTALL_DIR)/$(BUNDLE_NAME)"
	@echo "Removed: $(INSTALL_DIR)/$(BUNDLE_NAME)"
