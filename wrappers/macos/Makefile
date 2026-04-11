APP_NAME = AgentsDashboard
BUNDLE_NAME = Agents Dashboard.app
BUILD_DIR = .build
RELEASE_DIR = $(BUILD_DIR)/release
BIN_DIR = $(shell swift build -c release --show-bin-path 2>/dev/null || echo "$(BUILD_DIR)/arm64-apple-macosx/release")
DEBUG_DIR = $(BUILD_DIR)/arm64-apple-macosx/debug
INSTALL_DIR = /Applications

# Version from VERSION file
VERSION = $(shell cat VERSION | tr -d '[:space:]')
BUILD_NUMBER = $(shell git rev-list --count HEAD 2>/dev/null || echo 1)
ZIP_NAME = $(APP_NAME)_$(VERSION)+$(BUILD_NUMBER).zip

# Load .env if present (SIGNING_IDENTITY, APPLE_ID, TEAM_ID, APP_PASSWORD)
-include .env
export

SIGNING_IDENTITY ?= -
APPLE_ID ?=
TEAM_ID ?=
APP_PASSWORD ?=

.PHONY: all build test release sign notarize zip run clean install uninstall

all: build

# Debug build
build:
	swift build

# Run tests
test:
	swift test

# Release build + .app bundle
release:
	swift build -c release
	@mkdir -p "$(RELEASE_DIR)/$(BUNDLE_NAME)/Contents/MacOS"
	@mkdir -p "$(RELEASE_DIR)/$(BUNDLE_NAME)/Contents/Resources"
	@cp $(BIN_DIR)/$(APP_NAME) "$(RELEASE_DIR)/$(BUNDLE_NAME)/Contents/MacOS/$(APP_NAME)"
	@cp $(APP_NAME)/Info.plist "$(RELEASE_DIR)/$(BUNDLE_NAME)/Contents/Info.plist"
	@sed -i '' 's/__VERSION__/$(VERSION)/g' "$(RELEASE_DIR)/$(BUNDLE_NAME)/Contents/Info.plist"
	@sed -i '' 's/__BUILD_NUMBER__/$(BUILD_NUMBER)/g' "$(RELEASE_DIR)/$(BUNDLE_NAME)/Contents/Info.plist"
	@cp $(APP_NAME)/AppIcon.icns "$(RELEASE_DIR)/$(BUNDLE_NAME)/Contents/Resources/"
	@cp $(APP_NAME)/$(APP_NAME).entitlements "$(RELEASE_DIR)/$(BUNDLE_NAME)/Contents/Resources/"
	@codesign --force --sign - --entitlements $(APP_NAME)/$(APP_NAME).entitlements "$(RELEASE_DIR)/$(BUNDLE_NAME)"
	@echo "Built: $(RELEASE_DIR)/$(BUNDLE_NAME) ($(VERSION)+$(BUILD_NUMBER))"

# Sign release build with a Developer ID (or ad-hoc if SIGNING_IDENTITY is -)
# Usage: make sign SIGNING_IDENTITY="Developer ID Application: Your Name (TEAMID)"
sign: release
	@codesign --force --options runtime --sign "$(SIGNING_IDENTITY)" --entitlements $(APP_NAME)/$(APP_NAME).entitlements "$(RELEASE_DIR)/$(BUNDLE_NAME)"
	@echo "Signed: $(RELEASE_DIR)/$(BUNDLE_NAME) with '$(SIGNING_IDENTITY)'"
	@codesign -dv "$(RELEASE_DIR)/$(BUNDLE_NAME)" 2>&1 | head -5

# Notarize a signed release build with Apple
# Requires: Developer ID signing, Apple Developer account
# Usage: make notarize SIGNING_IDENTITY="Developer ID Application: ..." \
#                      APPLE_ID=you@email.com TEAM_ID=XXXXXXXXXX \
#                      APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
# Generate an app-specific password at https://appleid.apple.com/account/manage
notarize: sign
	@test "$(SIGNING_IDENTITY)" != "-" || (echo "Error: notarization requires a Developer ID signing identity" && exit 1)
	@test -n "$(APPLE_ID)" || (echo "Error: APPLE_ID is required" && exit 1)
	@test -n "$(TEAM_ID)" || (echo "Error: TEAM_ID is required" && exit 1)
	@test -n "$(APP_PASSWORD)" || (echo "Error: APP_PASSWORD is required (app-specific password)" && exit 1)
	@echo "Creating zip for notarization..."
	@cd "$(RELEASE_DIR)" && ditto -c -k --keepParent "$(BUNDLE_NAME)" "$(APP_NAME).zip"
	@echo "Submitting to Apple for notarization..."
	@xcrun notarytool submit "$(RELEASE_DIR)/$(APP_NAME).zip" \
		--apple-id "$(APPLE_ID)" \
		--team-id "$(TEAM_ID)" \
		--password "$(APP_PASSWORD)" \
		--wait
	@echo "Stapling notarization ticket..."
	@xcrun stapler staple "$(RELEASE_DIR)/$(BUNDLE_NAME)"
	@rm -f "$(RELEASE_DIR)/$(APP_NAME).zip"
	@cd "$(RELEASE_DIR)" && ditto -c -k --keepParent "$(BUNDLE_NAME)" "$(ZIP_NAME)"
	@echo "Notarized: $(RELEASE_DIR)/$(ZIP_NAME)"

# Create versioned zip of the release build
zip: release
	@cd "$(RELEASE_DIR)" && ditto -c -k --keepParent "$(BUNDLE_NAME)" "$(ZIP_NAME)"
	@echo "Created: $(RELEASE_DIR)/$(ZIP_NAME)"

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
