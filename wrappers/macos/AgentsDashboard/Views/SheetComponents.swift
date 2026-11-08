import SwiftUI

/// Icon, title and explanation at the top of a sheet.
struct SheetHeader: View {
    let systemImage: String
    let title: String
    let message: String

    var body: some View {
        VStack(spacing: 4) {
            Image(systemName: systemImage)
                .font(.system(size: 36))
                .foregroundColor(.accentColor)

            Text(title)
                .font(.title2)
                .fontWeight(.semibold)

            Text(message)
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
        }
    }
}

/// A labelled group of form controls ("Project Path", "Location", ...).
struct SheetField<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.headline)

            content
        }
    }
}

/// Cancel on the left, the sheet's prominent action on the right.
struct SheetActions: View {
    let onCancel: () -> Void
    let confirmTitle: String
    /// Whether Return triggers the confirm button.
    var isDefaultAction = true
    var confirmDisabled = false
    let onConfirm: () -> Void

    var body: some View {
        HStack {
            Button("Cancel", action: onCancel)
                .keyboardShortcut(.cancelAction)

            Spacer()

            Button(confirmTitle, action: onConfirm)
                .keyboardShortcut(isDefaultAction ? .defaultAction : nil)
                .buttonStyle(.borderedProminent)
                .disabled(confirmDisabled)
        }
    }
}
