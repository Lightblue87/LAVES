import SwiftUI
import UIKit

// MARK: - Keyboard dismissal

extension UIApplication {
    func dismissKeyboard() {
        sendAction(#selector(UIResponder.resignFirstResponder),
                   to: nil, from: nil, for: nil)
    }
}

// MARK: - Window-level keyboard dismiss installer

/// Installs a UITapGestureRecognizer with cancelsTouchesInView = false on the UIWindow.
/// Because it sits in UIKit — not SwiftUI's gesture system — it never interferes with
/// Pickers, Buttons, Lists, or any other SwiftUI / UIKit control.
/// Embed once as `.background(KeyboardDismissInstaller())` on the root view.
struct KeyboardDismissInstaller: UIViewRepresentable {

    func makeUIView(context: Context) -> InstallerView {
        InstallerView()
    }

    func updateUIView(_ uiView: InstallerView, context: Context) {}

    // MARK: - UIView subclass that hooks into window lifecycle

    final class InstallerView: UIView {

        private weak var installedWindow: UIWindow?
        private var tapGR: UITapGestureRecognizer?

        override func didMoveToWindow() {
            super.didMoveToWindow()
            guard let window, tapGR == nil else { return }
            let gr = UITapGestureRecognizer(target: self, action: #selector(handleTap))
            gr.cancelsTouchesInView = false   // ← touches still reach all targets
            window.addGestureRecognizer(gr)
            tapGR = gr
            installedWindow = window
        }

        override func willMove(toWindow newWindow: UIWindow?) {
            super.willMove(toWindow: newWindow)
            if newWindow == nil, let win = installedWindow, let gr = tapGR {
                win.removeGestureRecognizer(gr)
                tapGR = nil
                installedWindow = nil
            }
        }

        @objc private func handleTap() {
            UIApplication.shared.dismissKeyboard()
        }
    }
}

extension View {
    /// Installs app-wide tap-to-dismiss-keyboard once on the root view.
    /// Do NOT use this on individual TextFields or inner views — only on the top-level container.
    func installKeyboardDismissOnTap() -> some View {
        self.background(KeyboardDismissInstaller())
    }
}
