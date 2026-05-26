import CryptoKit
import Foundation

@MainActor
final class LabelingRuleStore: ObservableObject {
    @Published private(set) var feedTypes: [LabelingFeedType] = []
    @Published private(set) var feedMaterials: [FeedMaterial] = []
    @Published private(set) var dlgFeedMaterials: [DlgFeedMaterial] = []
    @Published private(set) var additiveParserConfig: AdditiveParserConfig?
    @Published private(set) var isLoaded = false
    @Published private(set) var loadError: String?
    @Published private(set) var dbInfo: LabelingDatabaseInfo?
    @Published private(set) var isUpdating = false
    @Published private(set) var updateProgress: Double?
    @Published private(set) var updateDetail: String?
    @Published private(set) var updateAvailable = false

    private let repository: LabelingRuleRepository = SQLiteLabelingRuleRepository()
    private let downloader = LabelingDownloadService()
    private let defaults = UserDefaults.standard
    private let shaKey = "feedlabelcheck.labeling.sqlite.sha256"
    private var didCheckForUpdates = false
    private var isCheckingForUpdates = false

    // MARK: - Database URL

    private var localDatabaseURL: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("FeedLabelCheck/labeling.sqlite")
    }

    var activeDatabaseURL: URL? {
        if FileManager.default.fileExists(atPath: localDatabaseURL.path) {
            return localDatabaseURL
        }
        return Bundle.main.url(forResource: "labeling", withExtension: "sqlite")
    }

    // MARK: - Loading

    func load() async {
        guard !isLoaded else { return }

        guard let url = activeDatabaseURL else {
            loadError = "Kennzeichnungs-Datenbank nicht gefunden."
            return
        }

        do {
            feedTypes = try repository.loadFeedTypes(from: url)
            feedMaterials = try repository.loadFeedMaterials(from: url)
            dlgFeedMaterials = try repository.loadDlgFeedMaterials(from: url)
            additiveParserConfig = try? repository.loadAdditiveParserConfig(from: url)
            dbInfo = try repository.loadDatabaseInfo(from: url)
            loadError = nil
            isLoaded = true
            Task { await checkForUpdates() }
        } catch {
            loadError = "Kennzeichnungsregeln konnten nicht geladen werden: \(error.localizedDescription)"
        }
    }

    func rules(forFeedType feedTypeId: String) async -> [LabelingRule] {
        guard let url = activeDatabaseURL else { return [] }
        return (try? repository.loadRules(from: url, forFeedType: feedTypeId)) ?? []
    }

    // MARK: - Updates

    func checkForUpdates() async {
        guard !isUpdating, !isCheckingForUpdates, !didCheckForUpdates else { return }
        isCheckingForUpdates = true
        defer {
            isCheckingForUpdates = false
            didCheckForUpdates = true
        }
        do {
            let manifest = try await downloader.fetchLabelingManifest()
            let stored = defaults.string(forKey: shaKey)
            let activeSHA = activeDatabaseURL.flatMap { try? fileSHA256($0) }
            if activeSHA == manifest.sha256 {
                defaults.set(manifest.sha256, forKey: shaKey)
                updateAvailable = false
            } else {
                updateAvailable = stored != manifest.sha256
                    || !FileManager.default.fileExists(atPath: localDatabaseURL.path)
            }
        } catch {
            // Silent background check
        }
    }

    func updateFromRemote() async {
        guard !isUpdating else { return }
        isUpdating = true
        updateAvailable = false
        updateProgress = 0
        updateDetail = "Manifest wird geladen"
        defer { isUpdating = false; updateProgress = nil; updateDetail = nil }

        do {
            let manifest = try await downloader.fetchLabelingManifest()
            if defaults.string(forKey: shaKey) == manifest.sha256,
               FileManager.default.fileExists(atPath: localDatabaseURL.path) {
                updateDetail = "Kennzeichnungs-Datenbank aktuell"
                return
            }

            updateDetail = "Herunterladen"
            let downloaded = try await downloader.downloadLabelingDatabase(
                fileName: manifest.file,
                expectedSHA256: manifest.sha256,
                expectedBytes: manifest.bytes,
                progress: { [weak self] v in
                    self?.updateProgress = v
                    self?.updateDetail = "Herunterladen (\(Int(v * 100)) %)"
                }
            )

            updateDetail = "Datenbank wird installiert"
            let dir = localDatabaseURL.deletingLastPathComponent()
            try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            if FileManager.default.fileExists(atPath: localDatabaseURL.path) {
                try FileManager.default.removeItem(at: localDatabaseURL)
            }
            try FileManager.default.moveItem(at: downloaded, to: localDatabaseURL)

            feedTypes = try repository.loadFeedTypes(from: localDatabaseURL)
            feedMaterials = try repository.loadFeedMaterials(from: localDatabaseURL)
            dlgFeedMaterials = try repository.loadDlgFeedMaterials(from: localDatabaseURL)
            additiveParserConfig = try? repository.loadAdditiveParserConfig(from: localDatabaseURL)
            dbInfo = try repository.loadDatabaseInfo(from: localDatabaseURL)
            defaults.set(manifest.sha256, forKey: shaKey)
            updateAvailable = false
            isLoaded = true
            loadError = nil
        } catch {
            loadError = "Aktualisierung fehlgeschlagen: \(error.localizedDescription)"
        }
    }

    private func fileSHA256(_ url: URL) throws -> String {
        let data = try Data(contentsOf: url)
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}

// MARK: - Labeling Download Service

struct LabelingManifestEntry: Decodable {
    let file: String
    let version: String
    let regulation: String
    let celex: String
    let sha256: String
    let ruleCount: Int
    let bytes: Int
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case file, version, regulation, celex, sha256, bytes
        case ruleCount = "rule_count"
        case createdAt = "created_at"
    }
}

struct LabelingDownloadService {
    private let rawBaseURL = URL(string: "https://raw.githubusercontent.com/Lightblue87/FeedLabelCheck-Data/main/")!
    private let defaultDatabaseFileName = "labeling.sqlite"

    var manifestURL: URL {
        rawBaseURL.appendingPathComponent("manifest-v2.json")
    }

    func fetchLabelingManifest() async throws -> LabelingManifestEntry {
        debugLog("Manifest URL: \(manifestURL.absoluteString)")
        let (data, response) = try await URLSession.shared.data(from: manifestURL)
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw DataDownloadError.httpStatus(http.statusCode, url: manifestURL)
        }
        // The manifest may or may not have labeling_db yet; decode leniently
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let labelingRaw = json["labeling_db"],
              let labelingData = try? JSONSerialization.data(withJSONObject: labelingRaw) else {
            throw LabelingDownloadError.noLabelingEntry
        }
        return try JSONDecoder().decode(LabelingManifestEntry.self, from: labelingData)
    }

    func downloadLabelingDatabase(
        fileName: String? = nil,
        expectedSHA256: String,
        expectedBytes: Int,
        progress: @escaping @MainActor @Sendable (Double) -> Void = { _ in }
    ) async throws -> URL {
        let databaseURL = rawURL(fileName: fileName ?? defaultDatabaseFileName)
        debugLog("SQLite URL: \(databaseURL.absoluteString)")
        let delegate = LabelingDownloadProgressDelegate(progress: progress)
        let session = URLSession(configuration: .default, delegate: delegate, delegateQueue: nil)
        let (url, response) = try await session.download(for: URLRequest(url: databaseURL))
        session.finishTasksAndInvalidate()
        if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
            throw DataDownloadError.httpStatus(http.statusCode, url: databaseURL)
        }

        let data = try Data(contentsOf: url)
        guard data.count == expectedBytes else {
            throw DataDownloadError.invalidSize(expected: expectedBytes, actual: data.count)
        }
        let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        guard digest == expectedSHA256.lowercased() else {
            throw DataDownloadError.invalidChecksum
        }

        let verifiedURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(UUID().uuidString)-\(databaseURL.lastPathComponent)")
        try data.write(to: verifiedURL, options: .atomic)
        return verifiedURL
    }

    func rawURL(fileName: String) -> URL {
        rawBaseURL.appendingPathComponent(fileName)
    }

    private func debugLog(_ message: String) {
        #if DEBUG
        print("[LabelingDownloadService] \(message)")
        #endif
    }
}

enum LabelingDownloadError: LocalizedError {
    case noLabelingEntry
    var errorDescription: String? { "Manifest enthält keinen Eintrag für die Kennzeichnungs-Datenbank." }
}

private final class LabelingDownloadProgressDelegate: NSObject, URLSessionDownloadDelegate {
    private let progress: @MainActor @Sendable (Double) -> Void
    init(progress: @escaping @MainActor @Sendable (Double) -> Void) { self.progress = progress }
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {}
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask,
                    didWriteData: Int64, totalBytesWritten: Int64, totalBytesExpectedToWrite: Int64) {
        guard totalBytesExpectedToWrite > 0 else { return }
        let v = Double(totalBytesWritten) / Double(totalBytesExpectedToWrite)
        Task { @MainActor [progress] in
            progress(min(max(v, 0), 1))
        }
    }
}
