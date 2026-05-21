import Foundation

// MARK: - Feed Type

struct LabelingFeedType: Identifiable, Hashable {
    let id: String
    let nameDe: String
    let descriptionDe: String?
    let keywordsDe: [String]

    var displayName: String { nameDe }
}

// MARK: - Rule & Pattern

struct LabelingRulePattern: Identifiable, Hashable {
    let id: String
    let ruleId: String
    let patternType: String  // "keyword" or "regex"
    let patternValue: String
    let patternLanguage: String
    let confidenceWeight: Double
    let isNegativePattern: Bool
}

struct LabelingRule: Identifiable, Hashable {
    let id: String
    let regulationId: String
    let feedTypeId: String
    let titleDe: String
    let descriptionDe: String
    let legalBasis: String
    let requirementType: String
    let severity: LabelingRuleSeverity
    let isMandatory: Bool
    let displayOrder: Int
    let patterns: [LabelingRulePattern]
}

enum LabelingRuleSeverity: String, Hashable {
    case critical
    case warning
    case info

    var icon: String {
        switch self {
        case .critical: return "exclamationmark.triangle.fill"
        case .warning: return "exclamationmark.circle.fill"
        case .info: return "info.circle"
        }
    }
}

// MARK: - Check Results

enum RuleCheckStatus: String, Hashable {
    case found           // Strong match (weight ≥ 0.85)
    case probablyFound   // Indirect evidence (0.6 ≤ weight < 0.85)
    case missing         // No pattern matched
    case unclear         // Negative (exclusion) pattern hit
    case notApplicable   // Rule doesn't apply to this feed type
    case notCheckable    // OCR too uncertain or empty

    var title: String {
        switch self {
        case .found: return "Gefunden"
        case .probablyFound: return "Wahrscheinlich gefunden"
        case .missing: return "Nicht gefunden"
        case .unclear: return "Unklar"
        case .notApplicable: return "Nicht zutreffend"
        case .notCheckable: return "Nicht prüfbar"
        }
    }

    var icon: String {
        switch self {
        case .found: return "checkmark.circle.fill"
        case .probablyFound: return "checkmark.circle"
        case .missing: return "xmark.circle.fill"
        case .unclear: return "questionmark.circle.fill"
        case .notApplicable: return "minus.circle"
        case .notCheckable: return "eye.slash"
        }
    }
}

struct RuleCheckResult: Identifiable {
    let id = UUID()
    let rule: LabelingRule
    let status: RuleCheckStatus
    let matchedText: String?
    let matchedLanguage: String?
    let confidence: Double
    let note: String?
}

enum LabelingOverallStatus: String {
    case keineAuffaelligkeit = "Keine Auffälligkeit erkannt"
    case auffaellig = "Auffällig"
    case unklar = "Unklar"
    case nichtPruefbar = "Nicht prüfbar"

    var icon: String {
        switch self {
        case .keineAuffaelligkeit: return "checkmark.shield.fill"
        case .auffaellig: return "exclamationmark.shield.fill"
        case .unklar: return "questionmark.circle.fill"
        case .nichtPruefbar: return "eye.slash.fill"
        }
    }
}

struct LabelingCheckResult {
    let feedType: LabelingFeedType
    let feedTypeConfidence: Double
    let ruleResults: [RuleCheckResult]
    let overallStatus: LabelingOverallStatus
    let checkedAt: Date
    let dbVersion: String
    let databaseInfo: LabelingDatabaseInfo?
    let ocrText: String
}

// MARK: - Database Info

struct LabelingDatabaseInfo {
    let version: String
    let regulation: String
    let celex: String
    let versionDate: String
    let createdAt: String
    let totalRuleCount: Int
    let sha256: String
}
