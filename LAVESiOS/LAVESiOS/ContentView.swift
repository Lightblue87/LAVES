import SwiftUI

struct ContentView: View {
    @StateObject private var store = AdditiveStore()

    var body: some View {
        TabView {
            SingleCheckView(store: store)
                .tabItem {
                    Label("Einzelprüfung", systemImage: "checkmark.seal")
                }

            BatchCheckView(store: store)
                .tabItem {
                    Label("Zusatzstoffe", systemImage: "list.bullet.rectangle")
                }
        }
        .task {
            store.load()
        }
    }
}
