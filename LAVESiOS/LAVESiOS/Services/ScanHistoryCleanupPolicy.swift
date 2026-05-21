import Foundation

struct ScanHistoryCleanupPolicy {
    struct Result: Equatable {
        var entries: [ScanEntry]
        var removedEntries = 0
        var removedImages = 0
        var imageFileNamesToRemove: [String] = []
    }

    static func apply(
        entries input: [ScanEntry],
        settings: ScanHistorySettings,
        now: Date = Date()
    ) -> Result {
        var result = Result(entries: input.sorted { $0.timestamp > $1.timestamp })
        removeDuplicateAndEmptyEntries(from: &result)
        removeEntriesPastAgeLimit(from: &result, settings: settings, now: now)
        enforceEntryLimit(on: &result, settings: settings)
        return result
    }

    static func duplicateKey(for entry: ScanEntry) -> String {
        entry.ocrText
            .lowercased()
            .replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func removeImagesToFitStorage(
        entries input: [ScanEntry],
        imageSizesByFileName: [String: Int64],
        byteLimit: Int64,
        keepOCRText: Bool
    ) -> Result {
        var result = Result(entries: input)

        func entryImageBytes(_ entry: ScanEntry) -> Int64 {
            entry.allThumbnailFileNames.reduce(Int64(0)) { $0 + (imageSizesByFileName[$1] ?? 0) }
        }

        func currentBytes() -> Int64 {
            result.entries.reduce(Int64(0)) { $0 + entryImageBytes($1) }
        }

        while currentBytes() > byteLimit {
            guard let candidate = result.entries
                .filter({ !$0.isPinned && !$0.allThumbnailFileNames.isEmpty })
                .sorted(by: { entryImageBytes($0) > entryImageBytes($1) })
                .first else {
                break
            }

            let fileNames = candidate.allThumbnailFileNames
            result.imageFileNamesToRemove.append(contentsOf: fileNames)
            result.removedImages += fileNames.count
            result.entries = result.entries.map {
                guard $0.id == candidate.id else { return $0 }
                let clearedItems = $0.imageItems?.map { item in
                    OCRImageItem(
                        id: item.id,
                        imageType: item.imageType,
                        thumbnailFileName: nil,
                        ocrText: keepOCRText ? item.ocrText : "",
                        capturedAt: item.capturedAt
                    )
                }
                return ScanEntry(
                    id: $0.id,
                    timestamp: $0.timestamp,
                    ocrText: keepOCRText ? $0.ocrText : "",
                    thumbnailFileName: nil,
                    isPinned: $0.isPinned,
                    note: $0.note,
                    imageItems: clearedItems
                )
            }
        }

        return result
    }

    private static func removeDuplicateAndEmptyEntries(from result: inout Result) {
        var seen = Set(
            result.entries
                .filter(\.isPinned)
                .map(duplicateKey(for:))
                .filter { !$0.isEmpty }
        )
        var kept: [ScanEntry] = []

        for entry in result.entries {
            let key = duplicateKey(for: entry)
            guard !entry.isPinned else {
                kept.append(entry)
                continue
            }
            if key.isEmpty || seen.contains(key) {
                markRemoved(entry, in: &result)
                continue
            }
            seen.insert(key)
            kept.append(entry)
        }
        result.entries = kept
    }

    private static func removeEntriesPastAgeLimit(
        from result: inout Result,
        settings: ScanHistorySettings,
        now: Date
    ) {
        guard let maxAge = settings.maxAge.interval else { return }
        let cutoff = now.addingTimeInterval(-maxAge)
        var kept: [ScanEntry] = []

        for entry in result.entries {
            guard !entry.isPinned, entry.timestamp < cutoff else {
                kept.append(entry)
                continue
            }
            markRemoved(entry, in: &result)
        }
        result.entries = kept
    }

    private static func enforceEntryLimit(on result: inout Result, settings: ScanHistorySettings) {
        guard let limit = settings.maxEntries.count else { return }
        let protected = result.entries.filter(\.isPinned)
        let regular = result.entries.filter { !$0.isPinned }
        guard regular.count > limit else { return }

        let keep = Array(regular.prefix(limit))
        let drop = regular.dropFirst(limit)
        for entry in drop {
            markRemoved(entry, in: &result)
        }
        result.entries = (protected + keep).sorted { $0.timestamp > $1.timestamp }
    }

    private static func markRemoved(_ entry: ScanEntry, in result: inout Result) {
        result.removedEntries += 1
        let fileNames = entry.allThumbnailFileNames
        result.removedImages += fileNames.count
        result.imageFileNamesToRemove.append(contentsOf: fileNames)
    }
}
