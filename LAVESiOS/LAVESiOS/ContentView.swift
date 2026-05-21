import SwiftUI

enum AppTab: Hashable {
    case batch
    case additives
    case scan
    case labeling
    case data
}

struct ContentView: View {
    @StateObject private var store = AdditiveStore()
    @StateObject private var labelingStore = LabelingRuleStore()
    @StateObject private var scanHistory = ScanHistoryService()
    @State private var selectedTab: AppTab = .scan
    @State private var selectedAdditiveScan: ScanEntry?
    @State private var selectedLabelingScan: ScanEntry?

    var body: some View {
        TabView(selection: $selectedTab) {
            BatchCheckView(store: store)
                .tabItem {
                    Label("Partie", systemImage: "scalemass")
                }
                .tag(AppTab.batch)

            SingleCheckView(
                store: store,
                scanHistory: scanHistory,
                selectedScanEntry: $selectedAdditiveScan
            )
                .tabItem {
                    Label("Zusatzstoffe", systemImage: "list.bullet.rectangle")
                }
                .tag(AppTab.additives)

            IngredientScanView(
                scanHistory: scanHistory,
                selectedTab: $selectedTab,
                selectedAdditiveScan: $selectedAdditiveScan,
                selectedLabelingScan: $selectedLabelingScan
                )
                .tabItem {
                    Label("Scan", systemImage: selectedTab == .scan ? "camera.fill" : "camera")
                }
                .tag(AppTab.scan)

            LabelingCheckView(
                labelingStore: labelingStore,
                scanHistory: scanHistory,
                selectedScanEntry: $selectedLabelingScan
            )
                .tabItem {
                    Label("Kennzeichnung", systemImage: "tag.circle")
                }
                .badge(labelingStore.updateAvailable ? 1 : 0)
                .tag(AppTab.labeling)

            DataStatusView(store: store)
                .tabItem {
                    Label("Daten", systemImage: "arrow.down.circle")
                }
                .badge(store.updateAvailable ? 1 : 0)
                .tag(AppTab.data)
        }
        .task {
            await store.load()
            await labelingStore.load()
        }
    }
}
