import SwiftUI

// MARK: - Keyboard dismissal

extension UIApplication {
    /// Dismisses the first responder (keyboard) app-wide.
    func dismissKeyboard() {
        sendAction(#selector(UIResponder.resignFirstResponder),
                   to: nil, from: nil, for: nil)
    }
}

extension View {
    /// Dismisses the keyboard when the user taps anywhere outside a text field.
    /// Uses simultaneousGesture so child view taps (buttons, list rows) still fire normally.
    /// Apply once at the root level (TabView) — do NOT repeat on individual text fields.
    func dismissKeyboardOnTap() -> some View {
        self.simultaneousGesture(
            TapGesture().onEnded {
                UIApplication.shared.dismissKeyboard()
            }
        )
    }
}
