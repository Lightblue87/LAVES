import Foundation

struct ScanHistoryStats: Equatable {
    var entryCount = 0
    var imageCount = 0
    var totalBytes: Int64 = 0
    var orphanImageCount = 0
    var missingImageCount = 0

    var formattedBytes: String {
        ByteCountFormatter.string(fromByteCount: totalBytes, countStyle: .file)
    }
}

struct ScanCleanupReport: Equatable {
    var removedEntries = 0
    var removedImages = 0
    var removedOrphans = 0
    var lastRun: Date

    var summary: String {
        "\(removedEntries) Einträge, \(removedImages) Bilder, \(removedOrphans) verwaiste Dateien entfernt"
    }
}
