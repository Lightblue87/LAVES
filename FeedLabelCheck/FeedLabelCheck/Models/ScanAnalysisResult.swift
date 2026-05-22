import Foundation

// MARK: - Labeling area detection

/// Keyword-based detection of which labeling areas are present in the OCR text.
/// No database access required — uses hardcoded keywords mirroring the labeling DB.
struct DetectedLabelingAreas: Codable, Equatable, Hashable {
    let hasComposition: Bool
    let hasAnalyticalConstituents: Bool
    let hasAdditives: Bool
    let hasBestBefore: Bool
    let hasLotNumber: Bool
    let hasNetQuantity: Bool
    let hasOperator: Bool

    /// Human-readable list of detected area names.
    var detectedNames: [String] {
        var names: [String] = []
        if hasComposition            { names.append("Zusammensetzung") }
        if hasAnalyticalConstituents { names.append("Analytische Bestandteile") }
        if hasAdditives              { names.append("Zusatzstoffe") }
        if hasBestBefore             { names.append("Mindesthaltbarkeit") }
        if hasLotNumber              { names.append("Losnummer") }
        if hasNetQuantity            { names.append("Nettomenge") }
        if hasOperator               { names.append("Hersteller/Vertrieb") }
        return names
    }

    /// Number of areas detected.
    var detectedCount: Int { detectedNames.count }
}

// MARK: - Additive hints

/// Quick additive-related signals extracted without a full DB lookup.
struct AdditiveHints: Codable, Equatable, Hashable {
    /// True when a Zusatzstoffe section header is present.
    let hasAdditiveSection: Bool
    /// True when "mg/kg" or similar amount patterns appear.
    let hasAmountPatterns: Bool
    /// True when E-numbers (e.g. "E 306") appear.
    let hasENumbers: Bool
    /// True when at least one structured declaration (name + amount + unit) was found.
    let hasStructuredDeclarations: Bool
    /// Substance names extracted from structured declarations (no DB match, raw names).
    let detectedSubstanceNames: [String]
}

// MARK: - Image coverage

/// Which packaging areas are covered by the captured images.
struct ImageCoverage: Codable, Equatable, Hashable {
    let imageCount: Int
    let coveredTypes: [OCRImageType]
    /// True when ≥2 images were captured but neither Boden nor Deckel was included.
    let missingBodenOrDeckel: Bool
    /// Rule-ID prefixes that should be forced to `.notCheckable` in the labeling check.
    let forcedNotCheckableRulePrefixes: [String]

    var coveredTypeSet: Set<OCRImageType> { Set(coveredTypes) }
}

// MARK: - ScanAnalysisResult

/// Central analysis result produced by `ScanAnalysisService` from the merged OCR text.
///
/// Stored inside `ScanEntry` (Codable). Produced once by the Scan tab; consumed
/// read-only by the Zusatzstoffe and Kennzeichnung modules — no re-analysis needed.
struct ScanAnalysisResult: Codable, Equatable, Hashable {
    /// ID of the detected feed type ("complete_feed", "pet_feed", …). Nil when not detected.
    let detectedFeedTypeId: String?
    /// Confidence of the feed type detection (0…1).
    let feedTypeConfidence: Double
    /// Human-readable labels of animal species mentioned on the label.
    let detectedSpeciesHints: [String]
    /// Which labeling areas were detected via keyword matching.
    let labelingAreas: DetectedLabelingAreas
    /// Additive-related signals.
    let additiveHints: AdditiveHints
    /// Image coverage for the multi-image session.
    let imageCoverage: ImageCoverage
    /// Quality warnings shown in the Scan tab (e.g. short OCR, missing areas).
    let qualityWarnings: [String]
    /// Timestamp of the analysis.
    let analyzedAt: Date
}
