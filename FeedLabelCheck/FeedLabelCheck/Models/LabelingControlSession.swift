import Foundation

// MARK: - Basis Document Type

/// The type of document used as the labeling control basis.
enum BasisDocumentType: String, Codable, CaseIterable, Identifiable {
    case partieprotokoll
    case rezepturblatt
    case analysebericht
    case mischprotokoll
    case deklarationsentwurf

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .partieprotokoll:    return "Partieprotokoll"
        case .rezepturblatt:      return "Rezepturblatt"
        case .analysebericht:     return "Analysebericht"
        case .mischprotokoll:     return "Mischprotokoll"
        case .deklarationsentwurf: return "Deklarationsentwurf"
        }
    }

    var systemImage: String {
        switch self {
        case .partieprotokoll:    return "doc.text"
        case .rezepturblatt:      return "list.bullet.rectangle"
        case .analysebericht:     return "chart.bar.xaxis"
        case .mischprotokoll:     return "doc.on.doc"
        case .deklarationsentwurf: return "doc.plaintext"
        }
    }
}

// MARK: - Requirement Status

/// How labeling-relevant a basis-document finding is.
enum LabelingRequirementStatus: String, Codable {
    /// Must appear on the label per VO 767/2009.
    case mustDeclare
    /// May be relevant but requires manual confirmation.
    case shouldReview
    /// Internal / production info — no labeling obligation.
    case notLabelRelevant
    /// Relevance cannot be determined from OCR text alone.
    case unclear

    var displayName: String {
        switch self {
        case .mustDeclare:      return "Kennzeichnungspflichtig"
        case .shouldReview:     return "Bitte prüfen"
        case .notLabelRelevant: return "Nicht kennzeichnungsrelevant"
        case .unclear:          return "Unklar"
        }
    }
}

// MARK: - Requirement Category

/// Which labeling field a suggestion refers to.
enum LabelingRequirementCategory: String, Codable, CaseIterable {
    case feedType
    case animalSpecies
    case composition
    case analyticalConstituents
    case additives
    case netQuantity
    case bestBefore
    case lotNumber
    case `operator`
    case feedingInstructions
    case storageInstructions
    case internalProductionInfo

    var displayName: String {
        switch self {
        case .feedType:               return "Futtermittelart"
        case .animalSpecies:          return "Tierart"
        case .composition:            return "Zusammensetzung"
        case .analyticalConstituents: return "Analytische Bestandteile"
        case .additives:              return "Zusatzstoffe"
        case .netQuantity:            return "Nettomenge"
        case .bestBefore:             return "Mindesthaltbarkeit"
        case .lotNumber:              return "Partie-/Losnummer"
        case .operator:               return "Verantwortlicher Unternehmer"
        case .feedingInstructions:    return "Fütterungshinweis"
        case .storageInstructions:    return "Lagerhinweis"
        case .internalProductionInfo: return "Interne Produktionsangabe"
        }
    }
}

// MARK: - Normalized Value

/// A parsed/normalized value extracted from OCR text (numeric or textual).
struct LabelingNormalizedValue: Codable, Equatable {
    /// Numeric representation after parsing thousands separators, decimals, etc.
    let numericValue: Double?
    /// Physical unit (e.g. "mg/kg", "%", "g").
    let unit: String?
    /// Original text fragment as extracted from OCR.
    let textValue: String?

    var displayString: String {
        if let v = numericValue, let u = unit {
            let formatted = v == v.rounded(.towardZero) && v < 1_000_000
                ? "\(Int(v))" : String(format: "%.4g", v)
            return "\(formatted) \(u)"
        }
        return textValue ?? ""
    }
}

// MARK: - Requirement Suggestion

/// A single labeling requirement detected from a basis document.
struct LabelingRequirementSuggestion: Identifiable, Codable {
    let id: UUID
    let category: LabelingRequirementCategory
    let status: LabelingRequirementStatus
    /// The raw OCR fragment that triggered this suggestion.
    let extractedText: String
    /// Normalized/parsed value when a numeric amount was detected.
    let normalizedValue: LabelingNormalizedValue?
    let note: String?

    init(
        id: UUID = UUID(),
        category: LabelingRequirementCategory,
        status: LabelingRequirementStatus,
        extractedText: String,
        normalizedValue: LabelingNormalizedValue? = nil,
        note: String? = nil
    ) {
        self.id = id
        self.category = category
        self.status = status
        self.extractedText = extractedText
        self.normalizedValue = normalizedValue
        self.note = note
    }
}

// MARK: - Comparison Status

/// Result of comparing one basis-document requirement against the packaging check.
enum PackagingComparisonStatus: String, Codable {
    /// Field found on packaging; value consistent with basis.
    case matched
    /// Not detected on packaging scan.
    case missingOnPackaging
    /// Found but value differs from basis.
    case mismatch
    /// Cannot verify (no image, OCR too short, missing packaging area).
    case notCheckable
    /// Ambiguous — manual check required.
    case unclear
    /// Not a labeling requirement (internal production info).
    case notRequired

    var displayName: String {
        switch self {
        case .matched:            return "Gefunden"
        case .missingOnPackaging: return "Fehlt auf Verpackung"
        case .mismatch:           return "Abweichend"
        case .notCheckable:       return "Nicht prüfbar"
        case .unclear:            return "Unklar"
        case .notRequired:        return "Nicht kennzeichnungsrelevant"
        }
    }

    var icon: String {
        switch self {
        case .matched:            return "checkmark.circle.fill"
        case .missingOnPackaging: return "xmark.circle.fill"
        case .mismatch:           return "exclamationmark.triangle.fill"
        case .notCheckable:       return "eye.slash"
        case .unclear:            return "questionmark.circle.fill"
        case .notRequired:        return "info.circle"
        }
    }
}

// MARK: - Comparison Entry

/// Comparison outcome for a single basis-document requirement.
struct ComparisonEntry: Identifiable, Codable {
    let id: UUID
    let suggestion: LabelingRequirementSuggestion
    let packagingStatus: PackagingComparisonStatus
    /// Text snippet from the packaging that matched (or nil when not found).
    let packagingText: String?
    let note: String?

    init(
        id: UUID = UUID(),
        suggestion: LabelingRequirementSuggestion,
        packagingStatus: PackagingComparisonStatus,
        packagingText: String? = nil,
        note: String? = nil
    ) {
        self.id = id
        self.suggestion = suggestion
        self.packagingStatus = packagingStatus
        self.packagingText = packagingText
        self.note = note
    }
}

// MARK: - Comparison Result

/// Aggregated comparison result for all requirements of one control session.
struct LabelingComparisonResult: Codable {
    let entries: [ComparisonEntry]
    let generatedAt: Date

    var matchedCount:      Int { entries.filter { $0.packagingStatus == .matched }.count }
    var missingCount:      Int { entries.filter { $0.packagingStatus == .missingOnPackaging }.count }
    var mismatchCount:     Int { entries.filter { $0.packagingStatus == .mismatch }.count }
    var notCheckableCount: Int { entries.filter { $0.packagingStatus == .notCheckable }.count }
    var notRequiredCount:  Int { entries.filter { $0.packagingStatus == .notRequired }.count }

    var hasIssues: Bool { missingCount > 0 || mismatchCount > 0 }

    /// Mandatory suggestions only (excludes `notRequired` and `unclear`).
    var mandatoryEntries: [ComparisonEntry] {
        entries.filter { $0.suggestion.status == .mustDeclare }
    }
}

// MARK: - Control Session (ViewModel)

/// In-memory session linking a basis-document scan with a packaging scan.
///
/// - **Not** persisted in `ScanHistoryService`.  Lifetime matches the
///   `LabelingCheckView` that owns it (`@StateObject`).
/// - The existing `ScanEntry` / `LabelingCheckResult` structures are reused
///   unchanged; no new storage path is introduced.
@MainActor
final class LabelingControlSession: ObservableObject {
    let id = UUID()

    // MARK: Basis
    @Published var basisScan: ScanEntry?
    @Published var basisDocumentType: BasisDocumentType = .partieprotokoll
    @Published var requirementSuggestions: [LabelingRequirementSuggestion] = []
    @Published var isAnalyzingBasis = false

    // MARK: Packaging (mirrors existing LabelingCheckView state)
    @Published var comparisonResult: LabelingComparisonResult?

    // MARK: Computed
    var hasBasis: Bool { basisScan != nil }
    var hasSuggestions: Bool { !requirementSuggestions.isEmpty }
    var canCompare: Bool { hasBasis && comparisonResult == nil }

    // MARK: Actions

    func setBasisScan(_ entry: ScanEntry) {
        basisScan = entry
        isAnalyzingBasis = true
        requirementSuggestions = LabelingRequirementSuggestionService.analyze(
            ocrText: entry.ocrText
        )
        isAnalyzingBasis = false
        comparisonResult = nil
    }

    func runComparison(packagingCheckResult: LabelingCheckResult, packagingOCRText: String) {
        guard hasBasis else { return }
        comparisonResult = LabelingControlComparisonService.compare(
            suggestions: requirementSuggestions,
            packagingCheckResult: packagingCheckResult,
            packagingOCRText: packagingOCRText
        )
    }

    func resetBasis() {
        basisScan = nil
        requirementSuggestions = []
        comparisonResult = nil
    }

    func resetAll() {
        resetBasis()
    }
}
