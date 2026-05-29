import SwiftUI

// MARK: - Keyboard dismissal helpers

extension View {
    /// Adds a "Fertig" button above the keyboard for .decimalPad / .numberPad fields,
    /// and enables interactive scroll-to-dismiss on the enclosing scroll view.
    /// Use this on every TextField with a numeric keyboard type.
    func numericKeyboardToolbar() -> some View {
        self.toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("Fertig") {
                    UIApplication.shared.sendAction(
                        #selector(UIResponder.resignFirstResponder),
                        to: nil, from: nil, for: nil
                    )
                }
            }
        }
    }
}
