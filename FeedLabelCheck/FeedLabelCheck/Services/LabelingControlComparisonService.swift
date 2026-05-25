import Foundation

// MARK: - LabelingControlComparisonService

/// Compares labeling requirement suggestions (from a basis document) against
/// the packaging check result and the raw packaging OCR text.
///
/// **Offline-only — no network calls.**
///
/// Value normalization:
/// - `1.000 mg/kg` == `1000 mg/kg`   (dot as thousands separator)
/// - `12,5 %`      == `12.5 %`       (comma as decimal)
/// - `Taurin`      == `Taurine`      (EN→DE synonym)
/// - `LOT`  == `Charge` == `Partie`  (field aliases)
/// - `MHD`  == `EXP` == `Best before` (field aliases)
struct LabelingControlComparisonService {

    // MARK: - Tolerances

    /// Relative tolerance for numeric comparisons (1 %).
    static let relativeTolerance = 0.01
    /// Absolute tolerance for values near zero.
    static let absoluteTolerance = 0.001

    // MARK: - Public API

    /// Compare all requirement suggestions against a packaging check result.
    static func compare(
        suggestions: [LabelingRequirementSuggestion],
        packagingCheckResult: LabelingCheckResult,
        packagingOCRText: String
    ) -> LabelingComparisonResult {
        let entries = suggestions.map {
            compare(
                suggestion: $0,
                checkResult: packagingCheckResult,
                packagingText: packagingOCRText
            )
        }
        return LabelingComparisonResult(entries: entries, generatedAt: Date())
    }

    // MARK: - Per-suggestion comparison

    /// Compare one requirement suggestion against the packaging check result.
    static func compare(
        suggestion: LabelingRequirementSuggestion,
        checkResult: LabelingCheckResult,
        packagingText: String
    ) -> ComparisonEntry {
        // Not-label-relevant → notRequired (no packaging check needed)
        if suggestion.status == .notLabelRelevant
            || suggestion.category == .internalProductionInfo {
            return ComparisonEntry(
                suggestion: suggestion,
                packagingStatus: .notRequired,
                note: "Interne Angabe – keine Kennzeichnungspflicht."
            )
        }

        // shouldReview → unclear (automatic comparison not possible)
        if suggestion.status == .shouldReview {
            return ComparisonEntry(
                suggestion: suggestion,
                packagingStatus: .unclear,
                note: "Manuelle Prüfung erforderlich."
            )
        }

        // Route to category-specific comparison
        switch suggestion.category {
        case .additives:
            return compareAdditive(suggestion, packagingText: packagingText)
        case .analyticalConstituents:
            return compareAnalytical(suggestion, packagingText: packagingText)
        case .lotNumber:
            return compareLotNumber(
                suggestion, checkResult: checkResult, packagingText: packagingText
            )
        case .bestBefore:
            return compareBestBefore(
                suggestion, checkResult: checkResult, packagingText: packagingText
            )
        case .composition:
            return compareByRule(
                suggestion, checkResult: checkResult, requirementType: "composition"
            )
        case .feedType:
            return compareByRule(
                suggestion, checkResult: checkResult, requirementType: "feed_type"
            )
        case .animalSpecies:
            return compareByRule(
                suggestion, checkResult: checkResult, requirementType: "animal_species"
            )
        case .operator:
            return compareByRule(
                suggestion, checkResult: checkResult, requirementType: "operator"
            )
        case .netQuantity:
            return compareByRule(
                suggestion, checkResult: checkResult, requirementType: "net_quantity"
            )
        case .feedingInstructions, .storageInstructions:
            return ComparisonEntry(
                suggestion: suggestion,
                packagingStatus: .notCheckable,
                note: "Automatischer Abgleich für Fütterungs-/Lagerhinweise nicht verfügbar."
            )
        case .internalProductionInfo:
            return ComparisonEntry(
                suggestion: suggestion,
                packagingStatus: .notRequired
            )
        }
    }

    // MARK: - Additive comparison

    private static func compareAdditive(
        _ suggestion: LabelingRequirementSuggestion,
        packagingText: String
    ) -> ComparisonEntry {
        let substanceName = extractSubstanceName(from: suggestion.extractedText)
        guard !substanceName.isEmpty else {
            return ComparisonEntry(
                suggestion: suggestion, packagingStatus: .unclear,
                note: "Stoffname konnte nicht extrahiert werden."
            )
        }

        guard textContainsSubstance(substanceName, in: packagingText) else {
            return ComparisonEntry(
                suggestion: suggestion,
                packagingStatus: .missingOnPackaging,
                note: "\"\(substanceName)\" nicht auf Verpackung erkannt."
            )
        }

        // Substance found — compare numeric value if available
        if let basisVal = suggestion.normalizedValue?.numericValue,
           let basisUnit = suggestion.normalizedValue?.unit {
            if let pkgVal = extractNumericValue(
                forKeyword: substanceName, unit: basisUnit, in: packagingText
            ) {
                if valuesMatch(pkgVal, basisVal) {
                    return ComparisonEntry(
                        suggestion: suggestion,
                        packagingStatus: .matched,
                        packagingText: "\(substanceName) \(formatValue(pkgVal)) \(basisUnit)"
                    )
                } else {
                    return ComparisonEntry(
                        suggestion: suggestion,
                        packagingStatus: .mismatch,
                        packagingText: "\(substanceName) \(formatValue(pkgVal)) \(basisUnit)",
                        note: "Grundlage: \(formatValue(basisVal)) \(basisUnit) · Verpackung: \(formatValue(pkgVal)) \(basisUnit)"
                    )
                }
            } else {
                return ComparisonEntry(
                    suggestion: suggestion,
                    packagingStatus: .unclear,
                    packagingText: substanceName,
                    note: "Stoff erkannt, Menge konnte nicht extrahiert werden."
                )
            }
        }

        // No numeric value to compare — name found is sufficient
        return ComparisonEntry(
            suggestion: suggestion,
            packagingStatus: .matched,
            packagingText: substanceName
        )
    }

    // MARK: - Analytical constituent comparison

    private static func compareAnalytical(
        _ suggestion: LabelingRequirementSuggestion,
        packagingText: String
    ) -> ComparisonEntry {
        let name = extractConstituentName(from: suggestion.extractedText)
        guard !name.isEmpty else {
            return ComparisonEntry(suggestion: suggestion, packagingStatus: .unclear)
        }

        guard textContainsKeyword(name, in: packagingText) else {
            return ComparisonEntry(
                suggestion: suggestion,
                packagingStatus: .missingOnPackaging,
                note: "\"\(name)\" nicht auf Verpackung erkannt."
            )
        }

        if let basisVal = suggestion.normalizedValue?.numericValue {
            if let pkgVal = extractNumericValue(forKeyword: name, unit: "%", in: packagingText) {
                if valuesMatch(pkgVal, basisVal) {
                    return ComparisonEntry(
                        suggestion: suggestion,
                        packagingStatus: .matched,
                        packagingText: "\(name) \(formatValue(pkgVal)) %"
                    )
                } else {
                    return ComparisonEntry(
                        suggestion: suggestion,
                        packagingStatus: .mismatch,
                        packagingText: "\(name) \(formatValue(pkgVal)) %",
                        note: "Grundlage: \(formatValue(basisVal)) % · Verpackung: \(formatValue(pkgVal)) %"
                    )
                }
            } else {
                return ComparisonEntry(
                    suggestion: suggestion,
                    packagingStatus: .unclear,
                    packagingText: name,
                    note: "Bestandteil erkannt, Wert konnte nicht verglichen werden."
                )
            }
        }

        return ComparisonEntry(
            suggestion: suggestion,
            packagingStatus: .matched,
            packagingText: name
        )
    }

    // MARK: - LOT comparison

    private static func compareLotNumber(
        _ suggestion: LabelingRequirementSuggestion,
        checkResult: LabelingCheckResult,
        packagingText: String
    ) -> ComparisonEntry {
        let lotResult = checkResult.ruleResults.first(where: { $0.rule.id == "art15_004" })

        guard let status = lotResult?.status else {
            return ComparisonEntry(
                suggestion: suggestion, packagingStatus: .notCheckable,
                note: "Keine Losnummer-Regel im Prüfergebnis enthalten."
            )
        }

        switch status {
        case .found, .probablyFound:
            // Check whether the specific code from the basis is visible on the packaging
            if let basisCode = extractLotCode(from: suggestion.extractedText),
               !basisCode.isEmpty {
                if textContainsKeyword(basisCode, in: packagingText) {
                    return ComparisonEntry(
                        suggestion: suggestion,
                        packagingStatus: .matched,
                        packagingText: lotResult?.matchedText,
                        note: "Code \"\(basisCode)\" auf Verpackung gefunden."
                    )
                } else {
                    // LOT detected on packaging but different code (e.g. printed-on)
                    return ComparisonEntry(
                        suggestion: suggestion,
                        packagingStatus: .notCheckable,
                        note: "Losnummer erkannt, aber Code \"\(basisCode)\" nicht sichtbar – möglicherweise aufgedruckt."
                    )
                }
            }
            return ComparisonEntry(
                suggestion: suggestion,
                packagingStatus: .matched,
                packagingText: lotResult?.matchedText
            )

        case .missing:
            let hasBodenOrDeckel = hasBottomOrLidImage(checkResult)
            if !hasBodenOrDeckel {
                return ComparisonEntry(
                    suggestion: suggestion,
                    packagingStatus: .notCheckable,
                    note: "Kein Boden- oder Deckel-Bild vorhanden – Losnummer möglicherweise dort aufgedruckt."
                )
            }
            return ComparisonEntry(
                suggestion: suggestion,
                packagingStatus: .missingOnPackaging,
                note: "Losnummer / Charge nicht auf Verpackung erkannt."
            )

        case .notCheckable:
            return ComparisonEntry(
                suggestion: suggestion, packagingStatus: .notCheckable,
                note: "Verpackungs-OCR zu kurz für eine Prüfung."
            )

        case .unclear, .notApplicable:
            return ComparisonEntry(suggestion: suggestion, packagingStatus: .unclear)
        }
    }

    // MARK: - MHD comparison

    private static func compareBestBefore(
        _ suggestion: LabelingRequirementSuggestion,
        checkResult: LabelingCheckResult,
        packagingText: String
    ) -> ComparisonEntry {
        // art16_002 (single_feed) or art17_002_* (compound feeds)
        let mhdResult = checkResult.ruleResults.first(where: {
            $0.rule.id == "art16_002" || $0.rule.id.hasPrefix("art17_002")
        })

        guard let status = mhdResult?.status else {
            return ComparisonEntry(
                suggestion: suggestion, packagingStatus: .notCheckable,
                note: "Keine MHD-Regel im Prüfergebnis enthalten."
            )
        }

        switch status {
        case .found, .probablyFound:
            // If the basis document contains a concrete date, verify the packaging carries
            // the same date.  Comparison is done on parsed (day, month, year) integers so
            // separator style (`.` vs `-` vs `/`) and leading-zero differences don't produce
            // false mismatches.
            if let basisComponents = extractDateComponents(from: suggestion.extractedText) {
                if packagingContainsDateComponents(basisComponents, in: packagingText) {
                    return ComparisonEntry(
                        suggestion: suggestion,
                        packagingStatus: .matched,
                        packagingText: mhdResult?.matchedText
                    )
                } else {
                    let basisStr = String(
                        format: "%02d.%02d.%04d",
                        basisComponents.day, basisComponents.month, basisComponents.year
                    )
                    return ComparisonEntry(
                        suggestion: suggestion,
                        packagingStatus: .mismatch,
                        packagingText: mhdResult?.matchedText,
                        note: "Grundlage-Datum \(basisStr) auf Verpackungs-OCR nicht bestätigt – möglicherweise aufgedruckt."
                    )
                }
            }
            // No concrete date in basis suggestion — MHD indicator found, accept.
            return ComparisonEntry(
                suggestion: suggestion,
                packagingStatus: .matched,
                packagingText: mhdResult?.matchedText
            )

        case .missing:
            if !hasBottomOrLidImage(checkResult) {
                return ComparisonEntry(
                    suggestion: suggestion,
                    packagingStatus: .notCheckable,
                    note: "Kein Boden- oder Deckel-Bild – MHD möglicherweise aufgedruckt."
                )
            }
            return ComparisonEntry(
                suggestion: suggestion,
                packagingStatus: .missingOnPackaging
            )

        case .notCheckable:
            return ComparisonEntry(suggestion: suggestion, packagingStatus: .notCheckable)

        case .unclear, .notApplicable:
            return ComparisonEntry(suggestion: suggestion, packagingStatus: .unclear)
        }
    }

    // MARK: - Generic rule-based comparison

    private static func compareByRule(
        _ suggestion: LabelingRequirementSuggestion,
        checkResult: LabelingCheckResult,
        requirementType: String
    ) -> ComparisonEntry {
        let matchingResult = checkResult.ruleResults.first(where: {
            $0.rule.requirementType == requirementType
        })

        guard let status = matchingResult?.status else {
            return ComparisonEntry(
                suggestion: suggestion, packagingStatus: .unclear,
                note: "Keine passende Regel im Prüfergebnis."
            )
        }

        switch status {
        case .found, .probablyFound:
            return ComparisonEntry(
                suggestion: suggestion,
                packagingStatus: .matched,
                packagingText: matchingResult?.matchedText
            )
        case .missing:
            return ComparisonEntry(suggestion: suggestion, packagingStatus: .missingOnPackaging)
        case .notCheckable:
            return ComparisonEntry(suggestion: suggestion, packagingStatus: .notCheckable)
        case .unclear, .notApplicable:
            return ComparisonEntry(suggestion: suggestion, packagingStatus: .unclear)
        }
    }

    // MARK: - Numeric comparison

    /// Returns `true` when `a` and `b` are within the configured tolerance.
    static func valuesMatch(_ a: Double, _ b: Double) -> Bool {
        if a == b { return true }
        let diff = abs(a - b)
        let larger = max(abs(a), abs(b))
        if larger > 0, (diff / larger) <= relativeTolerance { return true }
        return diff <= absoluteTolerance
    }

    // MARK: - Text matching helpers

    /// Case- and diacritics-insensitive keyword search.
    static func textContainsKeyword(_ keyword: String, in text: String) -> Bool {
        text.range(of: keyword, options: [.caseInsensitive, .diacriticInsensitive]) != nil
    }

    /// Searches for a substance name with EN↔DE synonym handling.
    /// "Taurine" matches "Taurin" and vice versa.
    static func textContainsSubstance(_ name: String, in text: String) -> Bool {
        if textContainsKeyword(name, in: text) { return true }
        let lower = name.lowercased()
        // EN → DE: strip trailing 'e'
        if lower.hasSuffix("e"), lower.count > 4 {
            if textContainsKeyword(String(lower.dropLast()), in: text) { return true }
        }
        // DE → EN: add 'e'
        if textContainsKeyword(lower + "e", in: text) { return true }
        return false
    }

    /// Extracts the numeric value for `keyword` followed by `unit` in `text`.
    /// E.g. `keyword="Taurin"`, `unit="mg/kg"` → 1000.0 from "Taurin 1.000 mg/kg".
    static func extractNumericValue(
        forKeyword keyword: String,
        unit: String,
        in text: String
    ) -> Double? {
        let escapedKeyword = NSRegularExpression.escapedPattern(for: keyword)
        let escapedUnit    = NSRegularExpression.escapedPattern(for: unit)
        // Allow up to 40 chars between keyword and value to handle OCR line breaks / padding
        let pattern = "(?i)\(escapedKeyword)[\\s\\S]{0,40}?(\\d[\\d.,\\s]{0,9})\\s*\(escapedUnit)"
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let match = regex.firstMatch(
                  in: text, range: NSRange(text.startIndex..., in: text)
              ),
              let numRange = Range(match.range(at: 1), in: text) else { return nil }
        let raw = String(text[numRange]).trimmingCharacters(in: .whitespaces)
        return AdditiveDeclarationParser.parseNumber(raw)
    }

    /// Extract the substance name from an additive text fragment.
    /// "Taurin 1000 mg/kg" → "Taurin".
    static func extractSubstanceName(from text: String) -> String {
        let pattern = #"^([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\-]{2,}(?:\s+[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9\-]*)?)"#
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let match = regex.firstMatch(
                  in: text, range: NSRange(text.startIndex..., in: text)
              ),
              let range = Range(match.range(at: 1), in: text) else { return text }
        return String(text[range]).trimmingCharacters(in: .whitespaces)
    }

    /// Extract the constituent name (keyword) from an analytical text fragment.
    /// "Rohprotein 12,5 %" → "Rohprotein".
    static func extractConstituentName(from text: String) -> String {
        let keywords = [
            "Rohprotein", "Rohfett", "Rohfaser", "Rohasche", "Feuchtigkeit",
            "Phosphor", "Natrium", "Kalzium", "Calcium", "Kalium", "Magnesium",
            "crude protein", "crude fat", "crude fibre", "crude ash", "moisture",
        ]
        let pattern = "(?i)\\b(" + keywords.map {
            NSRegularExpression.escapedPattern(for: $0)
        }.joined(separator: "|") + ")\\b"
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let match = regex.firstMatch(
                  in: text, range: NSRange(text.startIndex..., in: text)
              ),
              let range = Range(match.range(at: 1), in: text) else {
            return text.components(separatedBy: .whitespaces).first ?? text
        }
        return String(text[range])
    }

    /// Extract the LOT code from a raw text fragment.
    /// "Charge A12345" → "A12345".  Returns nil when only a keyword (no code) is present.
    static func extractLotCode(from text: String) -> String? {
        let kwPart = #"(?:LOT|L|Charge|Chargen-Nr\.?|Los|Partie|Zulassungsnummer\s+der\s+Partie|Kennnummer\s+der\s+Partie)"#
        let pattern = "(?i)\\b\(kwPart)\\s*[:\\-]?\\s*([A-Z0-9][A-Z0-9\\s\\-\\/]{0,20}\\d[A-Z0-9]*)\\b"
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let match = regex.firstMatch(
                  in: text, range: NSRange(text.startIndex..., in: text)
              ),
              match.numberOfRanges > 1,
              let range = Range(match.range(at: 1), in: text) else { return nil }
        return String(text[range]).trimmingCharacters(in: .whitespaces)
    }

    // MARK: - Private helpers

    /// Extracts and normalizes the first recognized date in `text` to `DD.MM.YYYY`.
    /// Delegates to `extractDateComponents` so day-first, year-first, and all separator
    /// styles are handled uniformly. Returns `nil` when no date pattern is found.
    static func extractDate(from text: String) -> String? {
        guard let c = extractDateComponents(from: text) else { return nil }
        return String(format: "%02d.%02d.%04d", c.day, c.month, c.year)
    }

    /// Parses the first recognized date in `text` into a `(day, month, year)` tuple.
    ///
    /// Supported formats:
    /// - Day-first:  `DD[sep]MM[sep]YYYY` or `DD[sep]MM[sep]YY`  (e.g. `31.12.2026`)
    /// - Year-first: `YYYY[sep]MM[sep]DD`                         (e.g. `2026/12/31`)
    ///
    /// Separators: `.`, `/`, `-`.  Two-digit years are expanded to 2000+.
    /// Day 1–31 and month 1–12 are validated; invalid combinations return `nil`.
    private static func extractDateComponents(
        from text: String
    ) -> (day: Int, month: Int, year: Int)? {
        // Try year-first first to prevent "2026" being split as day=20, remainder=26/…
        let yearFirst = #"(\d{4})[.\/\-](\d{1,2})[.\/\-](\d{1,2})"#
        if let regex = try? NSRegularExpression(pattern: yearFirst),
           let m = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
           let y = intCapture(m, 1, text), let mo = intCapture(m, 2, text),
           let d = intCapture(m, 3, text),
           y > 1900, mo >= 1, mo <= 12, d >= 1, d <= 31 {
            return (d, mo, y)
        }
        // Day-first (DD[sep]MM[sep]YYYY or DD[sep]MM[sep]YY)
        let dayFirst = #"(\d{1,2})[.\/\-](\d{1,2})[.\/\-](\d{2,4})"#
        if let regex = try? NSRegularExpression(pattern: dayFirst),
           let m = regex.firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
           let d = intCapture(m, 1, text), let mo = intCapture(m, 2, text),
           var y = intCapture(m, 3, text),
           d >= 1, d <= 31, mo >= 1, mo <= 12 {
            if y < 100 { y += 2000 }
            return (d, mo, y)
        }
        return nil
    }

    /// Returns `true` if `packagingText` contains any date whose day/month/year components
    /// match `target`, regardless of separator style (`31.12.2026` == `31-12-2026`) or
    /// leading-zero differences (`01.02.2026` == `1.2.2026`).
    private static func packagingContainsDateComponents(
        _ target: (day: Int, month: Int, year: Int),
        in packagingText: String
    ) -> Bool {
        // Scan both year-first and day-first date patterns in the packaging text.
        let pattern = #"(?:\d{4}[.\/\-]\d{1,2}[.\/\-]\d{1,2}|\d{1,2}[.\/\-]\d{1,2}[.\/\-]\d{2,4})"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return false }
        let nsRange = NSRange(packagingText.startIndex..., in: packagingText)
        return regex.matches(in: packagingText, range: nsRange).contains { m in
            guard let r = Range(m.range, in: packagingText) else { return false }
            guard let c = extractDateComponents(from: String(packagingText[r])) else { return false }
            return c.day == target.day && c.month == target.month && c.year == target.year
        }
    }

    /// Extracts an integer value from a regex capture group.
    private static func intCapture(
        _ match: NSTextCheckingResult, _ index: Int, _ text: String
    ) -> Int? {
        guard index < match.numberOfRanges,
              let r = Range(match.range(at: index), in: text) else { return nil }
        return Int(text[r])
    }

    private static func hasBottomOrLidImage(_ checkResult: LabelingCheckResult) -> Bool {
        checkResult.imageItems?.contains(where: {
            $0.imageType == .boden || $0.imageType == .deckel
        }) ?? false
    }

    private static func formatValue(_ v: Double) -> String {
        v == v.rounded(.towardZero) && v < 1_000_000
            ? "\(Int(v))" : String(format: "%.4g", v)
    }
}
