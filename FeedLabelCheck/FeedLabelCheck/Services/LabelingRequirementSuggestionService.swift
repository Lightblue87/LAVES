import Foundation

// MARK: - LabelingRequirementSuggestionService

/// Analyzes OCR text from a **basis document** (Partieprotokoll, Rezepturblatt,
/// Analysebericht, etc.) and extracts labeling-relevant requirements.
///
/// **Offline-only — no network calls, no database access.**
///
/// Produces `LabelingRequirementSuggestion` items with these status values:
/// - `.mustDeclare`      — analytische Bestandteile, Zusatzstoffe, Losnummer, MHD, …
/// - `.shouldReview`     — Rezeptur-ID (may be a LOT basis but not automatically one)
/// - `.notLabelRelevant` — Produktionslinie, interne Freigabe, QC-Nummern, …
/// - `.unclear`          — anything that doesn't fit a known category
struct LabelingRequirementSuggestionService {

    // MARK: - Analytical constituent keywords

    private static let analyticalKeywordsDE = [
        "rohprotein", "rohfett", "rohfaser", "rohasche", "feuchtigkeit",
        "phosphor", "natrium", "kalzium", "calcium", "kalium", "magnesium",
        "chlorid", "stärke", "zucker",
    ]
    private static let analyticalKeywordsEN = [
        "crude protein", "crude fat", "crude fibre", "crude ash", "moisture",
    ]

    // MARK: - Compiled patterns (built lazily on first use)

    /// Analytical constituent with numeric % value:
    /// "Rohprotein 12,5 %"  "crude protein 18.0 %"
    private static let analyticalRegex: NSRegularExpression = {
        let kw = [
            "Rohprotein", "Rohfett", "Rohfaser", "Rohasche", "Feuchtigkeit",
            "Phosphor", "Natrium", "Kalzium", "Calcium", "Kalium", "Magnesium",
            "crude\\s+protein", "crude\\s+fat", "crude\\s+fibre", "crude\\s+ash",
            "moisture",
        ].joined(separator: "|")
        let pattern = "(?i)\\b(\(kw))[:\\s]*(\\d+[,.]?\\d*)\\s*(%|g\\/100g)"
        return try! NSRegularExpression(pattern: pattern)
    }()

    /// Additive with quantity + unit (mg/kg, IE/kg, IU/kg, µg/kg, g/kg):
    /// "Taurin 1000 mg/kg"  "Vitamin D3 200 IE/kg"
    private static let additiveRegex: NSRegularExpression = {
        let nameGroup  = #"([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\-]{2,}(?:\s+[A-Za-zÄÖÜäöüß0-9][A-Za-zÄÖÜäöüß0-9\-]*)?)"#
        let amountGroup = #"(\d[\d.,\s]{0,9})"#
        let unitGroup   = #"(mg\/kg|g\/kg|IE\/kg|IU\/kg|µg\/kg|KBE\/kg)"#
        let pattern = "(?i)\\b" + nameGroup + "\\s+" + amountGroup + "\\s*" + unitGroup + "\\b"
        return try! NSRegularExpression(pattern: pattern)
    }()

    /// Composition ingredient with %: "Huhn 70 %", "Mais (25 %)"
    private static let compositionRegex: NSRegularExpression = {
        let pattern = #"(?i)\b([A-ZÄÖÜ][a-zäöüÄÖÜß]+(?:\s+[A-Za-zÄÖÜäöüß]+)*)\s*\(?(\d+[,.]?\d*)\s*%\)?"#
        return try! NSRegularExpression(pattern: pattern)
    }()

    /// LOT/Charge with concrete alphanumeric code:
    private static let lotWithCodeRegexes: [NSRegularExpression] = [
        // Standard short-keyword + code
        try! NSRegularExpression(
            pattern: #"(?i)\b(LOT|L|Charge|Chargen-Nr\.?|Los|Partie)(?!\w)\s?[:\-]?\s?[A-Z0-9\-\/]*\d[A-Z0-9\-\/]*\b"#
        ),
        // Long-form: Zulassungsnummer / Kennnummer der Partie + space-sep code
        try! NSRegularExpression(
            pattern: #"(?i)\b(?:Zulassungsnummer|Kennnummer)\s+der\s+Partie\s*[:\-]?\s*[A-Z]{1,5}\s*\d{4,}[A-Z0-9]*\b"#
        ),
    ]

    /// LOT keywords (no code present):
    private static let lotKeywords = [
        "charge:", "los:", "partie:", "chargennr", "losnummer:", "chargennummer:",
        "kennnummer der partie", "zulassungsnummer der partie", "partienummer",
        "partie-nr.", "partie nr.", "losnummer", "los-nr.", "lot",
        "batch:", "batch no.", "lot number",
    ]

    /// MHD/EXP with concrete date:
    private static let mhdWithDateRegexes: [NSRegularExpression] = [
        try! NSRegularExpression(
            pattern: #"(?i)\b(MHD|BBD|mindestens haltbar bis|haltbar bis|verwendbar bis)[:\s]*\d{1,2}[.\/\-]\d{1,2}[.\/\-]\d{2,4}\b"#
        ),
        try! NSRegularExpression(
            pattern: #"(?i)\b(EXP|BBE|best before|use before|use by|expiry|expiration)[:\s.]*\d{1,2}[.\/\-]\d{1,2}[.\/\-]\d{2,4}\b"#
        ),
    ]

    /// MHD keywords (without a concrete date):
    private static let mhdKeywords = [
        "mindesthaltbarkeit", "mindestens haltbar bis", "mhd",
        "haltbar bis", "best before", "verwendbar bis", "exp:", "bbe", "use by",
    ]

    /// Patterns for text that is definitely NOT label-relevant:
    private static let notRelevantRegexes: [(NSRegularExpression, String)] = [
        (try! NSRegularExpression(pattern: #"(?i)\bProduktionslinie\s+\d+"#),
         "Interne Produktionslinie – keine Kennzeichnungspflicht."),
        (try! NSRegularExpression(pattern: #"(?i)\binterne\s+Freigabe\b"#),
         "Interne Freigabe – keine Kennzeichnungspflicht."),
        (try! NSRegularExpression(pattern: #"(?i)\bQC-\d+"#),
         "Interne QC-Nummer – keine Kennzeichnungspflicht."),
        (try! NSRegularExpression(pattern: #"(?i)\bQC\s+Freigabe\b"#),
         "Interne QC-Freigabe – keine Kennzeichnungspflicht."),
        (try! NSRegularExpression(pattern: #"(?i)\bMischauftrag-Nr\.?\b"#),
         "Interner Mischauftrag – keine Kennzeichnungspflicht."),
        (try! NSRegularExpression(pattern: #"(?i)\bLiniennummer\b"#),
         "Interne Liniennummer – keine Kennzeichnungspflicht."),
        (try! NSRegularExpression(pattern: #"(?i)\bSilobezeichnung\b"#),
         "Interne Silobezeichnung – keine Kennzeichnungspflicht."),
        (try! NSRegularExpression(pattern: #"(?i)\bProzessschritt\b"#),
         "Interner Prozessschritt – keine Kennzeichnungspflicht."),
    ]

    /// Patterns for text that should be reviewed (could be relevant, needs manual check):
    private static let shouldReviewRegexes: [(NSRegularExpression, String)] = [
        (try! NSRegularExpression(pattern: #"(?i)\bRezeptur-(?:ID|Nr\.?|Nummer)\b"#),
         "Rezeptur-ID/Nummer: Möglicherweise als Partie-/Losnummer relevant – bitte manuell prüfen."),
        (try! NSRegularExpression(pattern: #"(?i)\bRezeptur-Datum\b"#),
         "Rezeptur-Datum: bitte prüfen."),
        (try! NSRegularExpression(pattern: #"(?i)\bArtikel-?Nr\.?\b"#),
         "Artikel-Nummer: Möglicherweise als Losnummergrundlage relevant – bitte manuell prüfen."),
        (try! NSRegularExpression(pattern: #"(?i)\bInternal\s+Ref\.?\b"#),
         "Interne Referenz: Möglicherweise als Losnummergrundlage relevant – bitte manuell prüfen."),
    ]

    // MARK: - Public API

    /// Analyze the OCR text of a basis document and return labeling requirement suggestions.
    ///
    /// Extraction order matters: not-relevant patterns are checked first to avoid
    /// incorrectly classifying internal codes as LOT numbers or additives.
    static func analyze(ocrText: String) -> [LabelingRequirementSuggestion] {
        var suggestions: [LabelingRequirementSuggestion] = []
        var seenKeys = Set<String>()

        let text = ocrText
        let textLower = text.lowercased()

        // ------------------------------------------------------------------
        // 1. Not-label-relevant (check first to suppress false classifications)
        // ------------------------------------------------------------------
        for (regex, note) in notRelevantRegexes {
            for match in regexMatches(regex, in: text) {
                let key = "not_" + match.lowercased().prefix(30)
                guard seenKeys.insert(String(key)).inserted else { continue }
                suggestions.append(LabelingRequirementSuggestion(
                    category: .internalProductionInfo,
                    status: .notLabelRelevant,
                    extractedText: match,
                    note: note
                ))
            }
        }

        // ------------------------------------------------------------------
        // 2. Should-review (e.g. Rezeptur-ID — not automatically a LOT)
        // ------------------------------------------------------------------
        for (regex, note) in shouldReviewRegexes {
            for match in regexMatches(regex, in: text) {
                let key = "review_" + match.lowercased().prefix(30)
                guard seenKeys.insert(String(key)).inserted else { continue }
                suggestions.append(LabelingRequirementSuggestion(
                    category: .lotNumber,
                    status: .shouldReview,
                    extractedText: match,
                    note: note
                ))
            }
        }

        // ------------------------------------------------------------------
        // 3. Analytical constituents with % value
        // ------------------------------------------------------------------
        for m in captureMatches(analyticalRegex, groupCount: 3, in: text) {
            let raw = m[0]; let numStr = m[2]; let unit = m[3]
            let key = "ana_" + m[1].lowercased().prefix(20)
            guard seenKeys.insert(String(key)).inserted else { continue }
            let numVal = AdditiveDeclarationParser.parseNumber(numStr)
            let nv = LabelingNormalizedValue(numericValue: numVal, unit: unit, textValue: raw)
            suggestions.append(LabelingRequirementSuggestion(
                category: .analyticalConstituents,
                status: .mustDeclare,
                extractedText: raw,
                normalizedValue: nv
            ))
        }

        // ------------------------------------------------------------------
        // 4. Additives with quantity+unit (mg/kg, IE/kg, etc.)
        // ------------------------------------------------------------------
        for m in captureMatches(additiveRegex, groupCount: 3, in: text) {
            let raw = m[0]; let substanceName = m[1]; let numStr = m[2]; let unit = m[3]
            // Exclude analytical constituents from the additive list
            let nameLower = substanceName.lowercased()
            guard !isAnalyticalConstituent(nameLower) else { continue }
            let key = "add_" + nameLower.prefix(20)
            guard seenKeys.insert(String(key)).inserted else { continue }
            let numVal = AdditiveDeclarationParser.parseNumber(numStr)
            let nv = LabelingNormalizedValue(numericValue: numVal, unit: unit, textValue: raw)
            suggestions.append(LabelingRequirementSuggestion(
                category: .additives,
                status: .mustDeclare,
                extractedText: raw,
                normalizedValue: nv
            ))
        }

        // ------------------------------------------------------------------
        // 5. Composition ingredients with %  (≥2 distinct ingredients)
        // ------------------------------------------------------------------
        let compMatches = captureMatches(compositionRegex, groupCount: 2, in: text)
        var compParts: [String] = []
        for m in compMatches {
            let ingredientName = m[1]
            let nameLower = ingredientName.lowercased()
            // Exclude analytical constituents and already-seen substances
            guard !isAnalyticalConstituent(nameLower) else { continue }
            let key = "comp_" + nameLower.prefix(20)
            guard seenKeys.insert(String(key)).inserted else { continue }
            compParts.append(m[0])
        }
        if compParts.count >= 2 {
            let combined = compParts.prefix(6).joined(separator: ", ")
            suggestions.append(LabelingRequirementSuggestion(
                category: .composition,
                status: .mustDeclare,
                extractedText: combined,
                note: "Zusammensetzung mit Prozentangaben erkannt."
            ))
        }

        // ------------------------------------------------------------------
        // 6. LOT / Charge with concrete code
        // ------------------------------------------------------------------
        var foundLotCode = false
        for regex in lotWithCodeRegexes {
            for match in regexMatches(regex, in: text) {
                let key = "lot_" + match.lowercased().prefix(30)
                guard seenKeys.insert(String(key)).inserted else { continue }
                foundLotCode = true
                suggestions.append(LabelingRequirementSuggestion(
                    category: .lotNumber,
                    status: .mustDeclare,
                    extractedText: match,
                    normalizedValue: LabelingNormalizedValue(
                        numericValue: nil, unit: nil, textValue: match
                    )
                ))
            }
        }
        // LOT keyword without concrete code
        if !foundLotCode && !suggestions.contains(where: { $0.category == .lotNumber && $0.status == .mustDeclare }) {
            for kw in lotKeywords {
                if textLower.contains(kw) {
                    suggestions.append(LabelingRequirementSuggestion(
                        category: .lotNumber,
                        status: .mustDeclare,
                        extractedText: kw,
                        note: "Chargenkennung erkannt – konkreter Code auf Verpackung prüfen."
                    ))
                    break
                }
            }
        }

        // ------------------------------------------------------------------
        // 7. MHD / EXP with concrete date
        // ------------------------------------------------------------------
        var foundMHDDate = false
        for regex in mhdWithDateRegexes {
            for match in regexMatches(regex, in: text) {
                let key = "mhd_" + match.lowercased().prefix(30)
                guard seenKeys.insert(String(key)).inserted else { continue }
                foundMHDDate = true
                suggestions.append(LabelingRequirementSuggestion(
                    category: .bestBefore,
                    status: .mustDeclare,
                    extractedText: match,
                    normalizedValue: LabelingNormalizedValue(
                        numericValue: nil, unit: nil, textValue: match
                    )
                ))
            }
        }
        // MHD keyword without concrete date
        if !foundMHDDate && !suggestions.contains(where: { $0.category == .bestBefore }) {
            for kw in mhdKeywords {
                if textLower.contains(kw) {
                    suggestions.append(LabelingRequirementSuggestion(
                        category: .bestBefore,
                        status: .mustDeclare,
                        extractedText: kw,
                        note: "MHD-Angabe erkannt – konkretes Datum auf Verpackung prüfen."
                    ))
                    break
                }
            }
        }

        return suggestions
    }

    // MARK: - Helpers

    /// Returns all full-match strings for a regex in `text`.
    private static func regexMatches(_ regex: NSRegularExpression, in text: String) -> [String] {
        let range = NSRange(text.startIndex..., in: text)
        return regex.matches(in: text, range: range).compactMap { m in
            Range(m.range, in: text).map { String(text[$0]) }
        }
    }

    /// Returns tuples: [fullMatch, group1, group2, …] for each match.
    /// `groupCount` is the number of capture groups expected.
    private static func captureMatches(
        _ regex: NSRegularExpression,
        groupCount: Int,
        in text: String
    ) -> [[String]] {
        let range = NSRange(text.startIndex..., in: text)
        return regex.matches(in: text, range: range).compactMap { m in
            guard let fullRange = Range(m.range, in: text) else { return nil }
            var result = [String(text[fullRange])]
            for i in 1...groupCount {
                let g = i < m.numberOfRanges
                    ? (Range(m.range(at: i), in: text).map { String(text[$0]) } ?? "")
                    : ""
                result.append(g)
            }
            return result
        }
    }

    private static func isAnalyticalConstituent(_ nameLower: String) -> Bool {
        let allKeywords = analyticalKeywordsDE + analyticalKeywordsEN
        return allKeywords.contains { nameLower.hasPrefix($0) }
    }
}
