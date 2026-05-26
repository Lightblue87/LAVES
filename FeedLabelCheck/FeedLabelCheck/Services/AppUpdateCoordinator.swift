import Combine
import Foundation

/// Koordiniert das atomare Update beider Datenbanken (Zusatzstoffe + Kennzeichnungsregeln).
/// Lädt das Manifest einmal, lädt ggf. beide Dateien herunter und installiert sie erst,
/// nachdem beide Downloads erfolgreich abgeschlossen sind.
@MainActor
final class AppUpdateCoordinator: ObservableObject {
    @Published private(set) var updateAvailable = false
    @Published private(set) var isUpdating = false
    @Published private(set) var progress: Double?
    @Published private(set) var detail: String?
    @Published private(set) var updateError: String?

    let additiveStore: AdditiveStore
    let labelingStore: LabelingRuleStore

    private let downloader = DataDownloadService()
    private let labelingDownloader = LabelingDownloadService()
    private var cancellables = Set<AnyCancellable>()

    init(additiveStore: AdditiveStore, labelingStore: LabelingRuleStore) {
        self.additiveStore = additiveStore
        self.labelingStore = labelingStore

        // Leite updateAvailable aus beiden Stores ab
        Publishers.CombineLatest(additiveStore.$updateAvailable, labelingStore.$updateAvailable)
            .receive(on: RunLoop.main)
            .map { a, b in a || b }
            .assign(to: \.updateAvailable, on: self)
            .store(in: &cancellables)
    }

    // MARK: - Update

    func performUpdate() async {
        guard !isUpdating else { return }
        isUpdating = true
        updateError = nil
        progress = 0
        detail = "Manifest wird geprüft…"
        defer {
            isUpdating = false
            progress = nil
            detail = nil
        }

        do {
            let manifest = try await downloader.fetchManifest()
            let needsAdditive = additiveStore.needsUpdate(manifest: manifest)
            let needsLabeling = manifest.labelingDb.map { labelingStore.needsUpdate(entry: $0) } ?? false

            guard needsAdditive || needsLabeling else {
                updateAvailable = false
                detail = "Alle Datenbanken sind aktuell"
                return
            }

            // ── Phase 1: Downloads ──────────────────────────────────────────
            var additiveURL: URL?
            var labelingURL: URL?

            if needsAdditive {
                let scale = needsLabeling ? 0.5 : 1.0
                detail = "Zusatzstoffe werden heruntergeladen…"
                let sqlite = manifest.files.sqlite
                additiveURL = try await downloader.downloadDatabase(
                    fileName: sqlite.name,
                    expectedSHA256: sqlite.sha256,
                    expectedBytes: sqlite.bytes,
                    progress: { [weak self] v in
                        self?.progress = v * scale
                        self?.detail = "Zusatzstoffe: \(Int(v * 100)) %"
                    }
                )
            }

            if needsLabeling, let ldb = manifest.labelingDb {
                let offset = needsAdditive ? 0.5 : 0.0
                let scale = needsAdditive ? 0.5 : 1.0
                detail = "Kennzeichnungsregeln werden heruntergeladen…"
                labelingURL = try await labelingDownloader.downloadLabelingDatabase(
                    fileName: ldb.file,
                    expectedSHA256: ldb.sha256,
                    expectedBytes: ldb.bytes,
                    progress: { [weak self] v in
                        self?.progress = offset + v * scale
                        self?.detail = "Kennzeichnungsregeln: \(Int(v * 100)) %"
                    }
                )
            }

            // ── Phase 2: Atomare Installation ───────────────────────────────
            // Erst wenn BEIDE Downloads erfolgreich sind, wird installiert.
            progress = 0.98
            detail = "Datenbanken werden installiert…"

            if let url = additiveURL {
                try await additiveStore.installDatabase(from: url, manifest: manifest)
            }
            if let url = labelingURL, let entry = manifest.labelingDb {
                try await labelingStore.installDatabase(from: url, entry: entry)
            }

            progress = 1.0
            detail = "Aktualisierung abgeschlossen"

        } catch {
            updateError = "Aktualisierung fehlgeschlagen: \(error.localizedDescription)"
            detail = "Aktualisierung fehlgeschlagen"
        }
    }
}
