import Foundation

@MainActor
final class AdditiveStore: ObservableObject {
    @Published private(set) var additives: [Additive] = [] {
        didSet { rebuildDerivedCollections() }
    }
    @Published private(set) var eNumbers: [String] = []
    @Published private(set) var substances: [String] = []
    @Published private(set) var animalCategories: [String] = ["Alle Kategorien"]
    private var speciesByCategory: [String: [String]] = [:]
    @Published private(set) var loadError: String?
    @Published private(set) var dataStatus = "Noch nicht geladen"
    @Published private(set) var isUpdating = false
    @Published private(set) var updateProgress: Double?
    @Published private(set) var updateDetail: String?
    @Published private(set) var updateAvailable = false

    private let downloader = DataDownloadService()
    private let sqliteRepository = SQLiteAdditiveRepository()
    private let defaults = UserDefaults.standard
    private let manifestSHAKey = "feedlabelcheck.data.sqlite.sha256"
    private let manifestDateKey = "feedlabelcheck.data.generatedAt"

    private func rebuildDerivedCollections() {
        eNumbers = Array(Set(additives.map(\.eNumber).filter { !$0.isEmpty })).sorted()
        substances = Array(Set(additives.map(\.name).filter { !$0.isEmpty })).sorted()
        let categories = Set(additives.compactMap(\.animalCategory).filter { !$0.isEmpty })
        animalCategories = ["Alle Kategorien"] + categories.sorted()

        var dict: [String: Set<String>] = [:]
        var allSpeciesSet = Set<String>()
        for additive in additives {
            let cat = additive.animalCategory ?? ""
            let extracted = EvaluationService.extractIndividualSpecies(
                from: additive.normalizedSpecies,
                category: cat.isEmpty ? nil : cat
            )
            if !cat.isEmpty { dict[cat, default: []].formUnion(extracted) }
            allSpeciesSet.formUnion(extracted)
        }
        var result = dict.mapValues { ["Alle Tierarten"] + $0.sorted() }
        result["Alle Kategorien"] = ["Alle Tierarten"] + allSpeciesSet.sorted()
        speciesByCategory = result
    }

    func species(for category: String) -> [String] {
        speciesByCategory[category] ?? ["Alle Tierarten"]
    }

    func load() async {
        guard additives.isEmpty else { return }

        if FileManager.default.fileExists(atPath: localDatabaseURL.path) {
            do {
                additives = try sqliteRepository.loadAdditives(from: localDatabaseURL)
                loadError = nil
                dataStatus = localDataStatus(prefix: "Lokale SQLite-Datenbank")
                Task { await checkForUpdates() }
                return
            } catch {
                loadError = "Lokale Datenbank konnte nicht gelesen werden: \(error.localizedDescription)"
            }
        }

        guard let url = Bundle.main.url(forResource: "zusatzstoffe", withExtension: "json") else {
            loadError = "zusatzstoffe.json wurde im App-Bundle nicht gefunden."
            return
        }

        do {
            let data = try Data(contentsOf: url)
            additives = try JSONDecoder().decode([Additive].self, from: data)
            loadError = nil
            dataStatus = "Bundle-Daten geladen (\(additives.count) Datensätze)"
            Task { await checkForUpdates() }
        } catch {
            loadError = "Daten konnten nicht geladen werden: \(error.localizedDescription)"
        }
    }

    func checkForUpdates() async {
        guard !isUpdating else { return }
        do {
            let manifest = try await downloader.fetchManifest()
            let isNew = defaults.string(forKey: manifestSHAKey) != manifest.files.sqlite.sha256
                || !FileManager.default.fileExists(atPath: localDatabaseURL.path)
            updateAvailable = isNew
        } catch {
            // Stille Hintergrundprüfung — Fehler werden ignoriert
        }
    }

    func updateFromRemote() async {
        guard !isUpdating else { return }
        isUpdating = true
        updateAvailable = false
        updateProgress = 0
        updateDetail = "Manifest wird geladen"
        loadError = nil
        defer {
            isUpdating = false
            updateProgress = nil
            updateDetail = nil
        }

        do {
            let manifest = try await downloader.fetchManifest()
            updateDetail = "Manifest geprüft"
            if defaults.string(forKey: manifestSHAKey) == manifest.files.sqlite.sha256,
               FileManager.default.fileExists(atPath: localDatabaseURL.path) {
                // Datum immer mit dem frischen Manifest-Stand aktualisieren
                defaults.set(manifest.generatedAt, forKey: manifestDateKey)
                let formattedDate = formattedDataDate(manifest.generatedAt)
                dataStatus = "Datenbank aktuell (\(additives.count) Datensätze, Stand \(formattedDate))"
                return
            }

            updateDetail = "Datenbank wird heruntergeladen"
            let downloadedURL = try await downloader.downloadDatabase(
                expectedSHA256: manifest.files.sqlite.sha256,
                expectedBytes: manifest.files.sqlite.bytes,
                progress: { [weak self] value in
                    await MainActor.run {
                        self?.updateProgress = value
                        self?.updateDetail = "Datenbank wird heruntergeladen (\(Int(value * 100)) %)"
                    }
                }
            )

            updateProgress = 1
            updateDetail = "Datenbank wird gespeichert"
            try prepareDataDirectory()
            if FileManager.default.fileExists(atPath: localDatabaseURL.path) {
                try FileManager.default.removeItem(at: localDatabaseURL)
            }
            try FileManager.default.moveItem(at: downloadedURL, to: localDatabaseURL)

            updateDetail = "Datenbank wird geladen"
            let loaded = try sqliteRepository.loadAdditives(from: localDatabaseURL)
            additives = loaded
            defaults.set(manifest.files.sqlite.sha256, forKey: manifestSHAKey)
            defaults.set(manifest.generatedAt, forKey: manifestDateKey)
            loadError = nil
            let formattedDate = formattedDataDate(manifest.generatedAt)
            dataStatus = "SQLite aktualisiert (\(manifest.recordCount) Datensätze, Stand \(formattedDate))"
            updateDetail = "Datenbank aktualisiert (Stand \(formattedDate))"
        } catch {
            loadError = "Aktualisierung fehlgeschlagen: \(error.localizedDescription)"
            updateDetail = "Aktualisierung fehlgeschlagen"
        }
    }

    private var localDatabaseURL: URL {
        dataDirectory.appendingPathComponent("feedlabelcheck.sqlite")
    }

    private var dataDirectory: URL {
        let baseURL = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let dir = baseURL.appendingPathComponent("FeedLabelCheck", isDirectory: true)
        StorageMigration.migrateIfNeeded(base: baseURL)
        return dir
    }

    private func prepareDataDirectory() throws {
        try FileManager.default.createDirectory(at: dataDirectory, withIntermediateDirectories: true)
    }

    private func localDataStatus(prefix: String) -> String {
        if let generatedAt = defaults.string(forKey: manifestDateKey), !generatedAt.isEmpty {
            return "\(prefix) geladen (\(additives.count) Datensätze, Stand \(formattedDataDate(generatedAt)))"
        }
        return "\(prefix) geladen (\(additives.count) Datensätze)"
    }

    private func formattedDataDate(_ value: String) -> String {
        if let date = isoDateFormatterWithFractionalSeconds.date(from: value)
            ?? isoDateFormatter.date(from: value) {
            return dataDateFormatter.string(from: date)
        }
        return value
    }

    var dataStatusBrief: String {
        guard !additives.isEmpty else { return "Keine Daten geladen" }
        if let generatedAt = defaults.string(forKey: manifestDateKey), !generatedAt.isEmpty {
            return "Stand \(formattedDataDate(generatedAt)) · \(additives.count) Einträge"
        }
        return "\(additives.count) Einträge geladen"
    }

    var currentSHA256: String {
        defaults.string(forKey: manifestSHAKey) ?? ""
    }

    private let isoDateFormatterWithFractionalSeconds: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private let isoDateFormatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private let dataDateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "de_DE")
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        return formatter
    }()
}
