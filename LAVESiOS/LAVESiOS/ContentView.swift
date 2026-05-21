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
        ZStack(alignment: .bottom) {
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
                        Label("Scan", systemImage: "camera.viewfinder")
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

            ScanTabBump()
                .allowsHitTesting(false)
        }
        .task {
            await store.load()
            await labelingStore.load()
        }
    }
}

private struct ScanTabBump: View {
    var body: some View {
        RoundedRectangle(cornerRadius: 24, style: .continuous)
            .fill(.regularMaterial)
            .overlay(
                RoundedRectangle(cornerRadius: 24, style: .continuous)
                    .stroke(Color.accentColor.opacity(0.18), lineWidth: 1)
            )
            .frame(width: 86, height: 50)
            .shadow(color: .black.opacity(0.08), radius: 12, x: 0, y: -2)
            .offset(y: 14)
    }
}
