import XCTest
import UIKit
@testable import LAVESiOS

final class ScanHistoryCleanupPolicyTests: XCTestCase {
    func testAgeLimitRemovesOldUnpinnedEntries() {
        var settings = ScanHistorySettings()
        settings.maxAge = .sevenDays
        settings.maxEntries = .unlimited
        settings.storageLimit = .unlimited
        let now = Date(timeIntervalSince1970: 1_000_000)
        let old = entry(daysAgo: 8, now: now, text: "old")
        let current = entry(daysAgo: 1, now: now, text: "current")

        let result = ScanHistoryCleanupPolicy.apply(entries: [old, current], settings: settings, now: now)

        XCTAssertEqual(result.entries.map(\.ocrText), ["current"])
        XCTAssertEqual(result.removedEntries, 1)
        XCTAssertEqual(result.imageFileNamesToRemove, ["old.jpg"])
    }

    func testAgeLimitKeepsPinnedEntries() {
        var settings = ScanHistorySettings()
        settings.maxAge = .sevenDays
        settings.maxEntries = .unlimited
        settings.storageLimit = .unlimited
        let now = Date(timeIntervalSince1970: 1_000_000)
        let oldPinned = entry(daysAgo: 30, now: now, text: "old pinned", fileName: "pinned.jpg", isPinned: true)

        let result = ScanHistoryCleanupPolicy.apply(entries: [oldPinned], settings: settings, now: now)

        XCTAssertEqual(result.entries, [oldPinned])
        XCTAssertEqual(result.removedEntries, 0)
        XCTAssertTrue(result.imageFileNamesToRemove.isEmpty)
    }

    func testEntryLimitRemovesOldestUnpinnedEntries() {
        var settings = ScanHistorySettings()
        settings.maxAge = .unlimited
        settings.maxEntries = .fifty
        settings.storageLimit = .unlimited
        let now = Date(timeIntervalSince1970: 1_000_000)
        let entries = (0..<55).map { index in
            entry(daysAgo: index, now: now, text: "scan \(index)", fileName: "\(index).jpg")
        }

        let result = ScanHistoryCleanupPolicy.apply(entries: entries, settings: settings, now: now)

        XCTAssertEqual(result.entries.count, 50)
        XCTAssertEqual(result.removedEntries, 5)
        XCTAssertEqual(Set(result.imageFileNamesToRemove), Set(["50.jpg", "51.jpg", "52.jpg", "53.jpg", "54.jpg"]))
    }

    func testEntryLimitDoesNotRemovePinnedEntries() {
        var settings = ScanHistorySettings()
        settings.maxAge = .unlimited
        settings.maxEntries = .fifty
        settings.storageLimit = .unlimited
        let now = Date(timeIntervalSince1970: 1_000_000)
        var entries = (0..<55).map { index in
            entry(daysAgo: index, now: now, text: "scan \(index)", fileName: "\(index).jpg")
        }
        entries[54].isPinned = true

        let result = ScanHistoryCleanupPolicy.apply(entries: entries, settings: settings, now: now)

        XCTAssertTrue(result.entries.contains { $0.isPinned && $0.ocrText == "scan 54" })
        XCTAssertEqual(result.entries.count, 51)
    }

    func testDuplicateScansAreRemoved() {
        var settings = ScanHistorySettings()
        settings.maxAge = .unlimited
        settings.maxEntries = .unlimited
        settings.storageLimit = .unlimited
        let now = Date(timeIntervalSince1970: 1_000_000)
        let newest = entry(daysAgo: 0, now: now, text: "Zusatzstoffe E 300", fileName: "new.jpg")
        let duplicate = entry(daysAgo: 1, now: now, text: "zusatzstoffe   e 300", fileName: "old.jpg")

        let result = ScanHistoryCleanupPolicy.apply(entries: [duplicate, newest], settings: settings, now: now)

        XCTAssertEqual(result.entries, [newest])
        XCTAssertEqual(result.imageFileNamesToRemove, ["old.jpg"])
    }

    func testDuplicateScansKeepPinnedEntryAndRemoveUnpinnedCopy() {
        var settings = ScanHistorySettings()
        settings.maxAge = .unlimited
        settings.maxEntries = .unlimited
        settings.storageLimit = .unlimited
        let now = Date(timeIntervalSince1970: 1_000_000)
        let pinned = entry(daysAgo: 1, now: now, text: "Zusatzstoffe E 300", fileName: "pinned.jpg", isPinned: true)
        let duplicate = entry(daysAgo: 0, now: now, text: "zusatzstoffe   e 300", fileName: "new.jpg")

        let result = ScanHistoryCleanupPolicy.apply(entries: [duplicate, pinned], settings: settings, now: now)

        XCTAssertEqual(result.entries, [pinned])
        XCTAssertEqual(result.imageFileNamesToRemove, ["new.jpg"])
    }

    func testEmptyOCRScansAreRemoved() {
        var settings = ScanHistorySettings()
        settings.maxAge = .unlimited
        settings.maxEntries = .unlimited
        settings.storageLimit = .unlimited
        let now = Date(timeIntervalSince1970: 1_000_000)

        let result = ScanHistoryCleanupPolicy.apply(
            entries: [entry(daysAgo: 0, now: now, text: "   ", fileName: "empty.jpg")],
            settings: settings,
            now: now
        )

        XCTAssertTrue(result.entries.isEmpty)
        XCTAssertEqual(result.imageFileNamesToRemove, ["empty.jpg"])
    }

    func testStorageLimitRemovesLargestUnpinnedImagesFirst() {
        let large = entry(daysAgo: 0, now: Date(), text: "large", fileName: "large.jpg")
        let small = entry(daysAgo: 1, now: Date(), text: "small", fileName: "small.jpg")

        let result = ScanHistoryCleanupPolicy.removeImagesToFitStorage(
            entries: [large, small],
            imageSizesByFileName: ["large.jpg": 90, "small.jpg": 20],
            byteLimit: 30,
            keepOCRText: true
        )

        XCTAssertEqual(result.removedImages, 1)
        XCTAssertEqual(result.imageFileNamesToRemove, ["large.jpg"])
        XCTAssertEqual(result.entries.first { $0.ocrText == "large" }?.thumbnailFileName, nil)
        XCTAssertEqual(result.entries.first { $0.ocrText == "large" }?.ocrText, "large")
        XCTAssertEqual(result.entries.first { $0.ocrText == "small" }?.thumbnailFileName, "small.jpg")
    }

    func testStorageLimitDoesNotRemovePinnedImages() {
        let pinned = entry(daysAgo: 0, now: Date(), text: "pinned", fileName: "pinned.jpg", isPinned: true)

        let result = ScanHistoryCleanupPolicy.removeImagesToFitStorage(
            entries: [pinned],
            imageSizesByFileName: ["pinned.jpg": 90],
            byteLimit: 30,
            keepOCRText: true
        )

        XCTAssertEqual(result.entries, [pinned])
        XCTAssertTrue(result.imageFileNamesToRemove.isEmpty)
    }

    private func entry(
        daysAgo: Int,
        now: Date,
        text: String,
        fileName: String? = nil,
        isPinned: Bool = false
    ) -> ScanEntry {
        ScanEntry(
            timestamp: now.addingTimeInterval(TimeInterval(-daysAgo * 24 * 60 * 60)),
            ocrText: text,
            thumbnailFileName: fileName ?? "\(text).jpg",
            isPinned: isPinned
        )
    }
}

final class ScanHistoryImageStoreTests: XCTestCase {
    private var tempDir: URL!

    override func setUpWithError() throws {
        tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("ScanHistoryImageStoreTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: tempDir)
    }

    func testOrphanCleanupRemovesUnreferencedFiles() throws {
        let store = ScanHistoryImageStore(thumbnailDir: tempDir)
        try Data("keep".utf8).write(to: tempDir.appendingPathComponent("keep.jpg"))
        try Data("orphan".utf8).write(to: tempDir.appendingPathComponent("orphan.jpg"))

        let removed = store.removeOrphans(referencedFileNames: ["keep.jpg"])

        XCTAssertEqual(removed, 1)
        XCTAssertTrue(FileManager.default.fileExists(atPath: tempDir.appendingPathComponent("keep.jpg").path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: tempDir.appendingPathComponent("orphan.jpg").path))
    }

    func testStorageStatsCountsBytesAndMissingImages() throws {
        let store = ScanHistoryImageStore(thumbnailDir: tempDir)
        try Data(repeating: 1, count: 12).write(to: tempDir.appendingPathComponent("existing.jpg"))
        let entries = [
            ScanEntry(ocrText: "existing", thumbnailFileName: "existing.jpg"),
            ScanEntry(ocrText: "missing", thumbnailFileName: "missing.jpg")
        ]

        let stats = store.stats(for: entries)

        XCTAssertEqual(stats.imageCount, 1)
        XCTAssertEqual(stats.totalBytes, 12)
        XCTAssertEqual(stats.missingImageCount, 1)
    }
}

final class ScanHistoryServiceTests: XCTestCase {
    private var tempDir: URL!

    override func setUpWithError() throws {
        tempDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("ScanHistoryServiceTests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
    }

    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: tempDir)
    }

    @MainActor
    func testDeleteAllImagesKeepsOCRTextWhenConfigured() {
        let service = ScanHistoryService(baseURL: tempDir)
        let entry = service.add(ocrText: "Zusatzstoffe E 300", thumbnail: testImage())

        XCTAssertNotNil(entry.thumbnailFileName)

        service.deleteAllImages(keepOCRText: true)

        XCTAssertEqual(service.entries.count, 1)
        XCTAssertEqual(service.entries[0].ocrText, "Zusatzstoffe E 300")
        XCTAssertNil(service.entries[0].thumbnailFileName)
    }

    @MainActor
    func testDeleteAllImagesKeepsPinnedImages() {
        let service = ScanHistoryService(baseURL: tempDir)
        let pinned = service.add(ocrText: "wichtig", thumbnail: testImage())
        _ = service.add(ocrText: "normal", thumbnail: testImage())
        service.togglePinned(pinned)

        service.deleteAllImages(keepOCRText: true)

        XCTAssertEqual(service.entries.count, 2)
        XCTAssertNotNil(service.entries.first { $0.ocrText == "wichtig" }?.thumbnailFileName)
        XCTAssertNil(service.entries.first { $0.ocrText == "normal" }?.thumbnailFileName)
    }

    @MainActor
    func testDeleteAllKeepsPinnedEntries() {
        let service = ScanHistoryService(baseURL: tempDir)
        let pinned = service.add(ocrText: "wichtig", thumbnail: testImage())
        _ = service.add(ocrText: "normal", thumbnail: testImage())
        service.togglePinned(pinned)

        service.deleteAll()

        XCTAssertEqual(service.entries.count, 1)
        XCTAssertEqual(service.entries[0].ocrText, "wichtig")
        XCTAssertTrue(service.entries[0].isPinned)
    }

    private func testImage() -> UIImage {
        let renderer = UIGraphicsImageRenderer(size: CGSize(width: 20, height: 20))
        return renderer.image { context in
            UIColor.red.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 20, height: 20))
        }
    }
}
