import Foundation
import SwiftUI
import UIKit

@MainActor
final class ScanHistoryService: ObservableObject {
    @Published private(set) var entries: [ScanEntry] = []
    @Published var settings: ScanHistorySettings {
        didSet {
            saveSettings()
            cleanup(reason: .settingsChanged)
        }
    }
    @Published private(set) var stats = ScanHistoryStats()
    @Published private(set) var lastCleanup: ScanCleanupReport?

    private enum CleanupReason {
        case addedEntry
        case manual
        case settingsChanged
    }

    private let historyURL: URL
    private let settingsURL: URL
    private let imageStore: ScanHistoryImageStore

    init(baseURL: URL? = nil) {
        let base = baseURL ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("LAVES")
        historyURL = base.appendingPathComponent("scan_history.json")
        settingsURL = base.appendingPathComponent("scan_history_settings.json")
        imageStore = ScanHistoryImageStore(thumbnailDir: base.appendingPathComponent("thumbnails"))
        settings = Self.loadSettings(from: settingsURL)
        load()
        cleanup(reason: .settingsChanged)
    }

    @discardableResult
    func add(ocrText: String, thumbnail: UIImage?) -> ScanEntry {
        guard settings.isHistoryEnabled else {
            return ScanEntry(ocrText: ocrText, thumbnailFileName: nil)
        }

        let thumbnailFileName = thumbnail.flatMap { imageStore.store(thumbnail: $0, settings: settings) }
        let entry = ScanEntry(
            id: UUID(),
            timestamp: Date(),
            ocrText: ocrText,
            thumbnailFileName: thumbnailFileName
        )
        entries.insert(entry, at: 0)
        cleanup(reason: .addedEntry)
        save()
        return entry
    }

    func delete(at offsets: IndexSet) {
        for idx in offsets {
            imageStore.remove(fileName: entries[idx].thumbnailFileName)
        }
        entries.remove(atOffsets: offsets)
        save()
    }

    func delete(_ entry: ScanEntry) {
        guard let idx = entries.firstIndex(where: { $0.id == entry.id }) else { return }
        imageStore.remove(fileName: entries[idx].thumbnailFileName)
        entries.remove(at: idx)
        save()
    }

    func deleteEntries(withIDs ids: Set<UUID>) {
        for entry in entries where ids.contains(entry.id) {
            imageStore.remove(fileName: entry.thumbnailFileName)
        }
        entries.removeAll { ids.contains($0.id) }
        save()
    }

    func togglePinned(_ entry: ScanEntry) {
        guard let idx = entries.firstIndex(where: { $0.id == entry.id }) else { return }
        entries[idx].isPinned.toggle()
        save()
    }

    func thumbnail(for entry: ScanEntry) -> UIImage? {
        imageStore.image(fileName: entry.thumbnailFileName)
    }

    func cleanupNow() {
        cleanup(reason: .manual)
        save()
    }

    func deleteAllImages(keepOCRText: Bool = true) {
        for entry in entries where !entry.isPinned {
            imageStore.remove(fileName: entry.thumbnailFileName)
        }
        if keepOCRText {
            entries = entries.map {
                guard !$0.isPinned else { return $0 }
                return ScanEntry(
                    id: $0.id,
                    timestamp: $0.timestamp,
                    ocrText: $0.ocrText,
                    thumbnailFileName: nil,
                    isPinned: $0.isPinned,
                    note: $0.note
                )
            }
        } else {
            entries.removeAll { !$0.isPinned }
        }
        save()
    }

    func deleteAll() {
        for entry in entries where !entry.isPinned {
            imageStore.remove(fileName: entry.thumbnailFileName)
        }
        entries.removeAll { !$0.isPinned }
        save()
    }

    private func load() {
        guard let data = try? Data(contentsOf: historyURL),
              let decoded = try? JSONDecoder().decode([ScanEntry].self, from: data) else { return }
        entries = decoded
    }

    private func save() {
        let dir = historyURL.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try? JSONEncoder().encode(entries).write(to: historyURL)
        refreshStats()
    }

    private static func loadSettings(from url: URL) -> ScanHistorySettings {
        guard let data = try? Data(contentsOf: url),
              let decoded = try? JSONDecoder().decode(ScanHistorySettings.self, from: data) else {
            return ScanHistorySettings()
        }
        return decoded
    }

    private func saveSettings() {
        let dir = settingsURL.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try? JSONEncoder().encode(settings).write(to: settingsURL)
    }

    private func cleanup(reason: CleanupReason) {
        let referenced = Set(entries.compactMap(\.thumbnailFileName))
        let removedOrphans = imageStore.removeOrphans(referencedFileNames: referenced)
        var policyResult = ScanHistoryCleanupPolicy.apply(entries: entries, settings: settings)
        imageStore.remove(fileNames: policyResult.imageFileNamesToRemove)
        entries = policyResult.entries

        if let byteLimit = settings.storageLimit.bytes {
            let imageSizes = Dictionary(
                uniqueKeysWithValues: entries.compactMap { entry -> (String, Int64)? in
                    guard let fileName = entry.thumbnailFileName else { return nil }
                    return (fileName, imageStore.imageSize(fileName: fileName))
                }
            )
            let storageResult = ScanHistoryCleanupPolicy.removeImagesToFitStorage(
                entries: entries,
                imageSizesByFileName: imageSizes,
                byteLimit: byteLimit,
                keepOCRText: settings.keepOCRTextWhenDeletingImages
            )
            imageStore.remove(fileNames: storageResult.imageFileNamesToRemove)
            entries = storageResult.entries
            policyResult.removedImages += storageResult.removedImages

            while imageStore.totalImageBytes() > byteLimit,
                  let candidate = entries.last(where: { !$0.isPinned && $0.thumbnailFileName != nil }) {
                imageStore.remove(fileName: candidate.thumbnailFileName)
                entries.removeAll { $0.id == candidate.id }
                policyResult.removedEntries += 1
            }
        }

        if reason == .manual || policyResult.removedEntries > 0 || policyResult.removedImages > 0 || removedOrphans > 0 {
            lastCleanup = ScanCleanupReport(
                removedEntries: policyResult.removedEntries,
                removedImages: policyResult.removedImages,
                removedOrphans: removedOrphans,
                lastRun: Date()
            )
        }
        refreshStats()
    }

    private func refreshStats() {
        stats = imageStore.stats(for: entries)
    }
}
