import Foundation

/// Merges per-image OCR results into a single deduplicated text document.
struct OCRDocumentAssembler {

    /// Merges a list of (imageType, ocrText) pairs into one OCR document.
    /// For a single image the text is returned as-is (trimmed).
    /// For multiple images the texts are concatenated and deduplicated.
    static func merge(_ items: [(type: OCRImageType, text: String)]) -> String {
        let trimmed = items.map { $0.text.trimmingCharacters(in: .whitespacesAndNewlines) }
        let nonEmpty = trimmed.filter { !$0.isEmpty }
        guard !nonEmpty.isEmpty else { return "" }
        if nonEmpty.count == 1 { return nonEmpty[0] }
        let joined = nonEmpty.joined(separator: "\n\n")
        return OCRDeduplicationService.deduplicate(joined)
    }
}

// MARK: - OCR Deduplication

/// Removes duplicate non-empty lines from merged OCR text.
/// Two lines are duplicates when they match case-insensitively after whitespace trimming.
struct OCRDeduplicationService {

    static func deduplicate(_ text: String) -> String {
        let lines = text.components(separatedBy: "\n")
        var seen = Set<String>()
        var result: [String] = []

        for line in lines {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.isEmpty {
                // Preserve at most one blank separator line between blocks
                if result.last?.trimmingCharacters(in: .whitespaces).isEmpty == false {
                    result.append("")
                }
                continue
            }
            let key = trimmed.lowercased()
            if !seen.contains(key) {
                seen.insert(key)
                result.append(trimmed)
            }
        }

        // Remove trailing blank lines
        while result.last?.isEmpty == true { result.removeLast() }
        return result.joined(separator: "\n")
    }
}
