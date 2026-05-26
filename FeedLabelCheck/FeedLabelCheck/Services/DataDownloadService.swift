import CryptoKit
import Foundation

struct DataManifest: Decodable {
    let generatedAt: String
    let recordCount: Int
    let files: Files
    let labelingDb: LabelingManifestEntry?

    struct Files: Decodable {
        let sqlite: File
    }

    struct File: Decodable {
        let name: String
        let sha256: String
        let bytes: Int
    }

    enum CodingKeys: String, CodingKey {
        case generatedAt = "generated_at"
        case recordCount = "record_count"
        case files
        case labelingDb = "labeling_db"
    }
}

struct DataDownloadService {
    private let rawBaseURL = URL(string: "https://raw.githubusercontent.com/Lightblue87/FeedLabelCheck-Data/main/")!
    private let defaultDatabaseFileName = "feedlabelcheck.sqlite"

    var manifestURL: URL {
        rawBaseURL.appendingPathComponent("manifest-v2.json")
    }

    func fetchManifest() async throws -> DataManifest {
        debugLog("Manifest URL: \(manifestURL.absoluteString)")
        let (data, response) = try await URLSession.shared.data(from: manifestURL)
        try validateHTTP(response, url: manifestURL)
        return try JSONDecoder().decode(DataManifest.self, from: data)
    }

    func downloadDatabase(
        fileName: String? = nil,
        expectedSHA256: String,
        expectedBytes: Int,
        progress: @escaping @MainActor @Sendable (Double) -> Void = { _ in }
    ) async throws -> URL {
        let databaseURL = rawURL(fileName: fileName ?? defaultDatabaseFileName)
        debugLog("SQLite URL: \(databaseURL.absoluteString)")
        let request = URLRequest(url: databaseURL)
        let delegate = DownloadProgressDelegate(progress: progress)
        let session = URLSession(configuration: .default, delegate: delegate, delegateQueue: nil)
        let (downloadedURL, response) = try await session.download(for: request)
        session.finishTasksAndInvalidate()
        try validateHTTP(response, url: databaseURL)

        let data = try Data(contentsOf: downloadedURL)
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

    private func validateHTTP(_ response: URLResponse, url: URL) throws {
        guard let httpResponse = response as? HTTPURLResponse else { return }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw DataDownloadError.httpStatus(httpResponse.statusCode, url: url)
        }
    }

    private func debugLog(_ message: String) {
        #if DEBUG
        print("[DataDownloadService] \(message)")
        #endif
    }
}

private final class DownloadProgressDelegate: NSObject, URLSessionDownloadDelegate {
    private let progress: @MainActor @Sendable (Double) -> Void

    init(progress: @escaping @MainActor @Sendable (Double) -> Void) {
        self.progress = progress
    }

    func urlSession(
        _ session: URLSession,
        downloadTask: URLSessionDownloadTask,
        didFinishDownloadingTo location: URL
    ) {}

    func urlSession(
        _ session: URLSession,
        downloadTask: URLSessionDownloadTask,
        didWriteData bytesWritten: Int64,
        totalBytesWritten: Int64,
        totalBytesExpectedToWrite: Int64
    ) {
        guard totalBytesExpectedToWrite > 0 else { return }
        let value = Double(totalBytesWritten) / Double(totalBytesExpectedToWrite)
        Task { @MainActor [progress] in
            progress(min(max(value, 0), 1))
        }
    }
}

enum DataDownloadError: LocalizedError {
    case httpStatus(Int, url: URL)
    case invalidSize(expected: Int, actual: Int)
    case invalidChecksum

    var errorDescription: String? {
        switch self {
        case .httpStatus(let status, let url):
            if status == 404 {
                return "Download fehlgeschlagen: Datei nicht gefunden (HTTP 404). URL: \(url.absoluteString)"
            }
            return "Download fehlgeschlagen: HTTP \(status). URL: \(url.absoluteString)"
        case .invalidSize(let expected, let actual):
            return "Download unvollständig: erwartet \(expected) Bytes, erhalten \(actual) Bytes."
        case .invalidChecksum:
            return "Download-Prüfsumme stimmt nicht mit dem Manifest überein."
        }
    }
}
