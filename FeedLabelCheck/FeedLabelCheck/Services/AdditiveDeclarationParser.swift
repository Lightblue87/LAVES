import Foundation

// MARK: - AdditiveDeclarationParser

/// Parses structured additive declarations from OCR label text.
///
/// Two-pass strategy:
/// 1. **Section-contextual**: extracts entries that appear after a recognised
///    Zusatzstoff section header (highest precision).
/// 2. **Unconditional E-number**: finds "E 300 200 mg/kg"-style entries
///    anywhere in the text.
///
/// All extracted entries are then matched against the loaded additive database.
///
/// **Offline-only — no network calls.**
struct AdditiveDeclarationParser {

    // MARK: - Section headers (longest first to avoid sub-string shadowing)

    private static let sectionHeaders: [String] = [
        "Ernährungsphysiologische Zusatzstoffe",
        "Zootechnische Zusatzstoffe",
        "Technologische Zusatzstoffe",
        "Sensorische Zusatzstoffe",
        "Zusatzstoff(e):",
        "Zusatzstoffe:",
        "Zusatzstoffe",
        "Zusatzstoff:",
        "Zusatzstoff",
    ]

    // MARK: - Analytical-constituent exclusion list
    // Substances that must NOT be treated as Zusatzstoffe declarations
    // (they appear in the "Analytische Bestandteile" section).
    private static let analyticalPrefixes: [String] = [
        "rohprotein", "rohfett", "rohfaser", "rohasche", "feuchtigkeit",
        "natrium", "phosphor", "stärke", "zucker", "kalium", "chlorid",
        "crude protein", "crude fat", "crude fibre", "crude ash", "moisture",
        "metabolisierbare", "umsetzbare",
    ]

    // MARK: - Compiled patterns (built once)

    /// Captures: (1) substance name, (2) amount raw text, (3) unit
    private static let entryRegex: NSRegularExpression? = {
        // Name: capital-start word ≥3 chars, optionally followed by 1 more word
        //       (handles "Vitamin A", "Vitamin D3", single words like "Taurin")
        // Amount: digit followed by up to 9 more digits/separators/spaces
        // Unit: all recognised units
        let nameGroup = #"([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\-]{2,}(?:\s+[A-Za-zÄÖÜäöüß0-9][A-Za-zÄÖÜäöüß0-9\-]*)?)"#
        let amountGroup = #"(\d[\d\.,\s]{0,9})"#
        let unitGroup   = #"(mg/kg|g/kg|IE/kg|IU/kg|KBE/kg|CFU/kg|µg/kg|mg/l|%)"#
        let pattern = nameGroup + #"\s+"# + amountGroup + #"\s*"# + unitGroup
        return try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive])
    }()

    /// Captures: (1) E-number, (2) amount raw text, (3) unit
    private static let eNumberRegex: NSRegularExpression? = {
        let eNumGroup   = #"(E\s*\d{3,4}[a-z]?)"#
        let amountGroup = #"(\d[\d\.,\s]{0,9})"#
        let unitGroup   = #"(mg/kg|g/kg|IE/kg|IU/kg|KBE/kg|CFU/kg|µg/kg|mg/l|%)"#
        let pattern = #"\b"# + eNumGroup + #"\s+"# + amountGroup + #"\s*"# + unitGroup
        return try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive])
    }()

    // MARK: - Public API

    /// Returns `true` when the text contains at least one structured additive
    /// declaration (substance name + numeric amount + unit) — no DB lookup needed.
    static func hasStructuredDeclaration(in text: String) -> Bool {
        !extractRawEntries(from: text).isEmpty
    }

    /// Parses all additive declarations from OCR text and matches them against
    /// the provided additive database.
    ///
    /// - Parameters:
    ///   - text:      The (merged, deduplicated) OCR text from the label.
    ///   - additives: Loaded additive database entries for DB matching.
    /// - Returns: Parsed and DB-matched declarations, deduplicated by substance name.
    static func parse(text: String, additives: [Additive]) -> [AdditiveDeclaration] {
        let rawEntries = extractRawEntries(from: text)
        guard !rawEntries.isEmpty else { return [] }

        // Deduplicate by normalised substance name
        var seen = Set<String>()
        return rawEntries.compactMap { entry in
            let key = entry.name.lowercased().trimmingCharacters(in: .whitespaces)
            guard seen.insert(key).inserted else { return nil }
            let (confidence, matched) = matchToDatabase(substanceName: entry.name,
                                                        additives: additives)
            return AdditiveDeclaration(
                substanceName: entry.name,
                amount: entry.amount,
                rawText: entry.rawText,
                confidence: confidence,
                matchedAdditive: matched
            )
        }
    }

    // MARK: - Raw entry extraction

    private static func extractRawEntries(
        from text: String
    ) -> [(name: String, amount: ParsedAdditiveAmount?, rawText: String)] {
        var results: [(name: String, amount: ParsedAdditiveAmount?, rawText: String)] = []
        results.append(contentsOf: extractFromSections(text))
        results.append(contentsOf: extractENumberEntries(text))
        return results
    }

    // MARK: - Section-based extraction

    private static func extractFromSections(
        _ text: String
    ) -> [(name: String, amount: ParsedAdditiveAmount?, rawText: String)] {
        let textLower = text.lowercased()
        var sectionStarts: [String.Index] = []

        for header in sectionHeaders {
            var searchAt = textLower.startIndex
            let headerLower = header.lowercased()
            while let range = textLower.range(of: headerLower,
                                              options: .caseInsensitive,
                                              range: searchAt..<textLower.endIndex) {
                sectionStarts.append(range.upperBound)
                searchAt = range.upperBound
            }
        }
        guard !sectionStarts.isEmpty else { return [] }

        sectionStarts.sort()

        var results: [(name: String, amount: ParsedAdditiveAmount?, rawText: String)] = []
        for (idx, start) in sectionStarts.enumerated() {
            // Content window: up to the next section header or 800 characters
            let end: String.Index
            if idx + 1 < sectionStarts.count {
                end = sectionStarts[idx + 1]
            } else {
                end = text.index(start, offsetBy: 800, limitedBy: text.endIndex) ?? text.endIndex
            }
            let sectionText = String(text[start..<end])
            results.append(contentsOf: applyEntryRegex(entryRegex, to: sectionText))
        }
        return results
    }

    // MARK: - E-number unconditional extraction

    private static func extractENumberEntries(
        _ text: String
    ) -> [(name: String, amount: ParsedAdditiveAmount?, rawText: String)] {
        guard let regex = eNumberRegex else { return [] }
        let nsText = text as NSString
        let fullRange = NSRange(location: 0, length: nsText.length)
        var results: [(name: String, amount: ParsedAdditiveAmount?, rawText: String)] = []

        for match in regex.matches(in: text, range: fullRange) {
            guard let nameRange   = Range(match.range(at: 1), in: text),
                  let amountRange = Range(match.range(at: 2), in: text),
                  let unitRange   = Range(match.range(at: 3), in: text),
                  let matchRange  = Range(match.range,        in: text) else { continue }

            // Normalise E-number: remove spaces, uppercase ("E 306" → "E306")
            let name = String(text[nameRange])
                .replacingOccurrences(of: " ", with: "")
                .uppercased()
            let amountRaw = String(text[amountRange]).trimmingCharacters(in: .whitespaces)
            let unit      = String(text[unitRange])
            let rawText   = String(text[matchRange])

            let parsed = parseNumber(amountRaw).map {
                ParsedAdditiveAmount(value: $0, unit: unit, rawText: amountRaw)
            }
            results.append((name: name, amount: parsed, rawText: rawText))
        }
        return results
    }

    // MARK: - Generic regex application

    private static func applyEntryRegex(
        _ regex: NSRegularExpression?,
        to text: String
    ) -> [(name: String, amount: ParsedAdditiveAmount?, rawText: String)] {
        guard let regex else { return [] }
        let nsText = text as NSString
        let fullRange = NSRange(location: 0, length: nsText.length)
        var results: [(name: String, amount: ParsedAdditiveAmount?, rawText: String)] = []

        for match in regex.matches(in: text, range: fullRange) {
            guard let nameRange   = Range(match.range(at: 1), in: text),
                  let amountRange = Range(match.range(at: 2), in: text),
                  let unitRange   = Range(match.range(at: 3), in: text),
                  let matchRange  = Range(match.range,        in: text) else { continue }

            let name      = String(text[nameRange]).trimmingCharacters(in: .whitespaces)
            let amountRaw = String(text[amountRange]).trimmingCharacters(in: .whitespaces)
            let unit      = String(text[unitRange])
            let rawText   = String(text[matchRange])

            guard !isAnalyticalConstituent(name) else { continue }

            let parsed = parseNumber(amountRaw).map {
                ParsedAdditiveAmount(value: $0, unit: unit, rawText: amountRaw)
            }
            results.append((name: name, amount: parsed, rawText: rawText))
        }
        return results
    }

    // MARK: - Number parsing (3-digit separator rule)

    /// Parses a number string:
    /// - "1.000" or "1,000"   → 1000.0  (exactly 3 digits after separator → thousands)
    /// - "15.000"              → 15000.0
    /// - "1 000" or "15 000"  → 1000.0 / 15000.0  (space as thousands separator)
    /// - "1.5"                 → 1.5    (1 digit after separator → decimal)
    /// - "200"                 → 200.0
    static func parseNumber(_ raw: String) -> Double? {
        let text = raw.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return nil }

        // Space-separated thousands: "1 000", "15 000"
        let spaceSepPattern = #"^(\d{1,3})\s(\d{3})$"#
        if let m = try? NSRegularExpression(pattern: spaceSepPattern)
            .firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
           let range = Range(m.range, in: text) {
            let digits = String(text[range]).filter(\.isNumber)
            return Double(digits)
        }

        // Dot or comma separator
        let sepPattern = #"^(\d+)([.,])(\d+)$"#
        if let m = try? NSRegularExpression(pattern: sepPattern)
            .firstMatch(in: text, range: NSRange(text.startIndex..., in: text)),
           let fracRange = Range(m.range(at: 3), in: text) {
            let fracPart = String(text[fracRange])
            if fracPart.count == 3 {
                // Thousands separator (e.g. "1.000" or "1,000")
                return Double(text.filter(\.isNumber))
            } else {
                // Decimal point (e.g. "1.5", "15.50")
                return Double(text.replacingOccurrences(of: ",", with: "."))
            }
        }

        // Plain integer or fallback
        return Double(text.replacingOccurrences(of: ",", with: "."))
    }

    // MARK: - Analytical-constituent filter

    private static func isAnalyticalConstituent(_ name: String) -> Bool {
        let normalized = name.lowercased().replacingOccurrences(of: "-", with: "")
        return analyticalPrefixes.contains { normalized.hasPrefix($0) }
    }

    // MARK: - DB matching

    /// Matches `substanceName` against the additive database.
    ///
    /// Priority:
    /// 1. Exact case-insensitive name match
    /// 2. E-number match (normalised)
    /// 3. English-to-German synonym ("Taurine" → "Taurin")
    /// 4. Fuzzy match (Levenshtein ≤ 2, name ≥ 6 chars) — requires confirmation
    /// 5. No match found
    static func matchToDatabase(
        substanceName: String,
        additives: [Additive]
    ) -> (AdditiveDeclarationConfidence, Additive?) {
        guard !additives.isEmpty else { return (.noDBMatch, nil) }

        let nameLower = substanceName.lowercased().trimmingCharacters(in: .whitespaces)

        // 1. Exact name match
        if let match = additives.first(where: { $0.name.lowercased() == nameLower }) {
            return (.exactMatch, match)
        }

        // 2. E-number match (e.g. "E306" or "E 306")
        let eNorm = nameLower.replacingOccurrences(of: " ", with: "")
        if eNorm.hasPrefix("e"), eNorm.count >= 4,
           Int(eNorm.dropFirst()) != nil {
            if let match = additives.first(where: {
                $0.eNumber.lowercased().replacingOccurrences(of: " ", with: "") == eNorm
            }) {
                return (.exactMatch, match)
            }
        }

        // 3. English → German: strip trailing 'e' ("Taurine" → "Taurin")
        if nameLower.hasSuffix("e"), nameLower.count > 4 {
            let deVariant = String(nameLower.dropLast())
            if let match = additives.first(where: { $0.name.lowercased() == deVariant }) {
                return (.exactMatch, match)
            }
        }

        // 4. High-threshold fuzzy match (Levenshtein ≤ 2, only for names ≥ 6 chars)
        if nameLower.count >= 6 {
            var bestDist = Int.max
            var bestMatch: Additive?
            for additive in additives {
                let dbName = additive.name.lowercased()
                guard dbName.count >= 4 else { continue }
                // Quick length-based early exit
                guard abs(nameLower.count - dbName.count) <= 2 else { continue }
                let dist = levenshtein(nameLower, dbName)
                if dist < bestDist {
                    bestDist = dist
                    bestMatch = additive
                }
            }
            if bestDist <= 2, let match = bestMatch {
                return (.fuzzyMatch, match)
            }
        }

        return (.noDBMatch, nil)
    }

    // MARK: - Levenshtein distance

    private static func levenshtein(_ a: String, _ b: String) -> Int {
        let a = Array(a), b = Array(b)
        let m = a.count, n = b.count
        guard m > 0 else { return n }
        guard n > 0 else { return m }

        var prev = Array(0...n)
        var curr = [Int](repeating: 0, count: n + 1)

        for i in 1...m {
            curr[0] = i
            for j in 1...n {
                let cost = a[i - 1] == b[j - 1] ? 0 : 1
                curr[j] = Swift.min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
            }
            swap(&prev, &curr)
        }
        return prev[n]
    }
}
