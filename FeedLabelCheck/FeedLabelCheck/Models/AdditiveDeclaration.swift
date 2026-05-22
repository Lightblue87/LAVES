import Foundation

// MARK: - Confidence

/// Confidence level for a parsed additive declaration matched against the additives database.
enum AdditiveDeclarationConfidence {
    /// Exact name match (or recognised synonym / E-number) with a parsed amount.
    /// Sufficient to upgrade art15_006 to `.found`.
    case exactMatch
    /// Name found in DB but no numeric amount could be parsed from the OCR text.
    case exactNoAmount
    /// High-threshold fuzzy match — requires manual confirmation before acting on it.
    case fuzzyMatch
    /// Substance not found in DB — manual lookup required.
    case noDBMatch

    /// True when the user should be asked to confirm the match before relying on it.
    var requiresConfirmation: Bool {
        self == .fuzzyMatch || self == .noDBMatch
    }

    var label: String {
        switch self {
        case .exactMatch:    return "Erkannt"
        case .exactNoAmount: return "Stoff erkannt"
        case .fuzzyMatch:    return "Ähnlicher Treffer – bitte bestätigen"
        case .noDBMatch:     return "Nicht in Datenbank – manuelle Prüfung"
        }
    }

    var icon: String {
        switch self {
        case .exactMatch:    return "checkmark.circle.fill"
        case .exactNoAmount: return "checkmark.circle"
        case .fuzzyMatch:    return "questionmark.circle.fill"
        case .noDBMatch:     return "exclamationmark.circle"
        }
    }
}

// MARK: - Parsed amount

struct ParsedAdditiveAmount {
    let value: Double
    let unit: String
    let rawText: String

    /// Human-readable representation, e.g. "1000 mg/kg" or "15.5 mg/kg".
    var displayString: String {
        if value == value.rounded(.towardZero) && value < 1_000_000 {
            return "\(Int(value)) \(unit)"
        }
        return String(format: "%.2f", value) + " \(unit)"
    }
}

// MARK: - Declaration

struct AdditiveDeclaration: Identifiable {
    let id: UUID
    let substanceName: String
    let amount: ParsedAdditiveAmount?
    let rawText: String
    let confidence: AdditiveDeclarationConfidence
    /// The best matching `Additive` from the database, if any.
    let matchedAdditive: Additive?

    init(
        id: UUID = UUID(),
        substanceName: String,
        amount: ParsedAdditiveAmount?,
        rawText: String,
        confidence: AdditiveDeclarationConfidence,
        matchedAdditive: Additive?
    ) {
        self.id = id
        self.substanceName = substanceName
        self.amount = amount
        self.rawText = rawText
        self.confidence = confidence
        self.matchedAdditive = matchedAdditive
    }

    /// True when this declaration provides sufficient evidence to upgrade art15_006 to `.found`.
    /// Requires an exact (or synonym) DB match AND a successfully parsed amount.
    var countsAsFound: Bool {
        (confidence == .exactMatch || confidence == .exactNoAmount) && amount != nil
    }
}
