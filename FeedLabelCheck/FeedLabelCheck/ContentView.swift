import SwiftUI

enum AppTab: Hashable {
    case batch
    case additives
    case scan
    case labeling
    case data
}

struct ContentView: View {
    @StateObject private var store: AdditiveStore
    @StateObject private var labelingStore: LabelingRuleStore
    @StateObject private var updateCoordinator: AppUpdateCoordinator
    @StateObject private var scanHistory: ScanHistoryService
    @State private var selectedTab: AppTab = .scan
    @State private var selectedAdditiveScan: ScanEntry?
    @State private var selectedLabelingScan: ScanEntry?
    @State private var isInitializing = true
    @State private var initializationProgress = 0.0
    @State private var initializationDetail = "App wird vorbereitet"
    @State private var didInitialize = false

    init() {
        let s = AdditiveStore()
        let ls = LabelingRuleStore()
        _store = StateObject(wrappedValue: s)
        _labelingStore = StateObject(wrappedValue: ls)
        _updateCoordinator = StateObject(wrappedValue: AppUpdateCoordinator(additiveStore: s, labelingStore: ls))
        _scanHistory = StateObject(wrappedValue: ScanHistoryService())
    }

    var body: some View {
        Group {
            if isInitializing {
                AppInitializationView(
                    progress: initializationProgress,
                    detail: initializationDetail
                )
            } else {
                mainTabs
            }
        }
        .task {
            await initializeAppIfNeeded()
        }
    }

    private var mainTabs: some View {
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
                labelingStore: labelingStore,
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
                selectedScanEntry: $selectedLabelingScan,
                additiveStore: store
            )
                .tabItem {
                    Label("Kennzeichnung", systemImage: "tag.circle")
                }
                .badge(labelingStore.updateAvailable ? 1 : 0)
                .tag(AppTab.labeling)

            DataStatusView(store: store, labelingStore: labelingStore, coordinator: updateCoordinator)
                .tabItem {
                    Label("Daten", systemImage: "arrow.down.circle")
                }
                .badge(updateCoordinator.updateAvailable ? 1 : 0)
                .tag(AppTab.data)
        }
    }

    private func initializeAppIfNeeded() async {
        guard !didInitialize else { return }
        didInitialize = true

        initializationProgress = 0.08
        initializationDetail = "Lokalen Speicher vorbereiten"
        await Task.yield()

        initializationProgress = 0.25
        initializationDetail = "Zusatzstoff-Daten laden"
        await store.load()

        initializationProgress = 0.65
        initializationDetail = "Kennzeichnungsregeln laden"
        await labelingStore.load()

        initializationProgress = 0.85
        initializationDetail = "Auf Aktualisierungen prüfen"
        Task { await updateCoordinator.checkForUpdates() }  // fire-and-forget; badge updates when done

        initializationProgress = 0.95
        initializationDetail = "Bereit"

        try? await Task.sleep(for: .milliseconds(180))
        isInitializing = false
    }
}

private struct AppInitializationView: View {
    let progress: Double
    let detail: String

    var body: some View {
        ZStack {
            Color(.systemGroupedBackground)
                .ignoresSafeArea()

            VStack(spacing: 28) {
                Spacer()

                VStack(spacing: 14) {
                    Image(systemName: "checkmark.shield.fill")
                        .font(.system(size: 54, weight: .semibold))
                        .foregroundStyle(.blue)

                    Text("FeedLabelCheck")
                        .font(.largeTitle.bold())

                    Text("Daten werden geladen")
                        .font(.headline)
                        .foregroundStyle(.secondary)
                }

                VStack(alignment: .leading, spacing: 10) {
                    ProgressView(value: progress)
                        .progressViewStyle(.linear)

                    HStack {
                        Text(detail)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text("\(Int(progress * 100)) %")
                            .font(.footnote.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(20)
                .background(Color(.secondarySystemGroupedBackground))
                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
                .padding(.horizontal, 32)

                Text("Beim ersten Start kann das Laden der lokalen Datenbank einen Moment dauern.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 40)

                Spacer()
            }
        }
    }
}
