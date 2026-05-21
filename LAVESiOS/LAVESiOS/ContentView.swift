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
                    Label("Partie", systemImage: "scalemass")
                }

            IngredientScanView(store: store)
                .tabItem {
                    Label("Scan", systemImage: "camera.viewfinder")
                }

            DataStatusView(store: store)
                .tabItem {
                    Label("Daten", systemImage: "arrow.down.circle")
                }
                .badge(store.updateAvailable ? 1 : 0)
        }
        .task {
            await store.load()
        }
    }
}
