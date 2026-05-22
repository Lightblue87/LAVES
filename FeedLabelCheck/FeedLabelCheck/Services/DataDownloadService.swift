import CryptoKit
import Foundation

struct DataManifest: Decodable {
    let generatedAt: String
    let recordCount: Int
    let files: Files

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
    }
}

struct DataDownloadService {
    private let manifestURL = URL(string: "https://raw.githubusercontent.com/Lightblue87/FeedLabelCheck-Data/main/manifest.json")!
    private let databaseURL = URL(string: "https://raw.githubusercontent.com/Lightblue87/FeedLabelCheck-Data/main/feedlabelcheck.sqlite")!

    func fetchManifest() async throws -> DataManifest {
        let (data, response) = try await URLSession.shared.data(from: manifestURL)
        try validateHTTP(response)
        return try JSONDecoder().decode(DataManifest.self, from: data)
    }

    func downloadDatabase(
        expectedSHA256: String,
        expectedBytes: Int,
        progress: @escaping @Sendable (Double) async -> Void = { _ in }
    ) async throws -> URL {
        let request = URLRequest(url: databaseURL)
        let delegate = DownloadProgressDelegate(progress: progress)
        let session = URLSession(configuration: .default, delegate: delegate, delegateQueue: nil)
        let (downloadedURL, response) = try await session.download(for: request)
        session.finishTasksAndInvalidate()
        try validateHTTP(response)

        let data = try Data(contentsOf: downloadedURL)
        guard data.count == expectedBytes else {
            throw DataDownloadError.invalidSize(expected: expectedBytes, actual: data.count)
        }

        let digest = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        guard digest == expectedSHA256.lowercased() else {
            throw DataDownloadError.invalidChecksum
        }

        return downloadedURL
    }

    private func validateHTTP(_ response: URLResponse) throws {
        guard let httpResponse = response as? HTTPURLResponse else { return }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw DataDownloadError.httpStatus(httpResponse.statusCode)
        }
    }
}

private final class DownloadProgressDelegate: NSObject, URLSessionDownloadDelegate {
    private let progress: @Sendable (Double) async -> Void

    init(progress: @escaping @Sendable (Double) async -> Void) {
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
        Task {
            await progress(min(max(value, 0), 1))
        }
    }
}

enum DataDownloadError: LocalizedError {
    case httpStatus(Int)
    case invalidSize(expected: Int, actual: Int)
    case invalidChecksum

    var errorDescription: String? {
        switch self {
        case .httpStatus(let status):
            return "Download fehlgeschlagen: HTTP \(status)."
        case .invalidSize(let expected, let actual):
            return "Download unvollständig: erwartet \(expected) Bytes, erhalten \(actual) Bytes."
        case .invalidChecksum:
            return "Download-Prüfsumme stimmt nicht mit dem Manifest überein."
        }
    }
}
