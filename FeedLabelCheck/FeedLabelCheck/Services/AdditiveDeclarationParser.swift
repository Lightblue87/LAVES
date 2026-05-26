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
    // These are the built-in defaults; the DB can supply an updated list via AdditiveParserConfig.

    static let defaultSectionHeaders: [String] = [
        // German — with "/kg" suffix variant common on multi-language EU labels
        // e.g. "Zusatzstoffe: Ernährungsphysiologische Zusatzstoffe/kg: Vitamin A …"
        "Ernährungsphysiologische Zusatzstoffe/kg",
        "Ernährungsphysiologische Zusatzstoffe",
        "Zootechnische Zusatzstoffe/kg",
        "Zootechnische Zusatzstoffe",
        "Technologische Zusatzstoffe/kg",
        "Technologische Zusatzstoffe",
        "Sensorische Zusatzstoffe/kg",
        "Sensorische Zusatzstoffe",
        "Zusatzstoff(e):",
        "Zusatzstoffe/kg:",
        "Zusatzstoffe je kg:",
        "Zusatzstoffe je kg",
        "Zusatzstoffe:",
        "Zusatzstoffe",
        "Zusatzstoff:",
        "Zusatzstoff",
        // English — IAMS Naturally uses "Additives per kg:", Felix uses "additives"
        "nutritional additives",
        "zootechnical additives",
        "technological additives",
        "sensory additives",
        "additives per kg:",
        "additives per kg",
        "additives:",
    ]

    // MARK: - Analytical-constituent exclusion list
    // Substances that must NOT be treated as Zusatzstoffe declarations
    // (they appear in the "Analytische Bestandteile" section).
    // These are the built-in defaults; the DB can supply an updated list via AdditiveParserConfig.
    static let defaultAnalyticalPrefixes: [String] = [
        "rohprotein", "rohfett", "rohfaser", "rohasche",
        "feuchtegehalt", "feuchtigkeit", "feuchte",
        "natrium", "phosphor", "stärke", "zucker", "kalium", "chlorid",
        "linolsaure", "linolsäure",
        "crude protein", "crude fat", "crude fibre", "crude ash", "moisture",
        "metabolisierbare", "umsetzbare",
        // Omega-fatty acids (appear in Analytische Bestandteile, not Zusatzstoffe)
        "omega",
    ]

    // MARK: - Compiled patterns (built once)

    /// Captures: (1) substance name, (2) amount raw text, (3) unit
    private static let entryRegex: NSRegularExpression? = {
        // Name: capital-start word ≥3 chars, optionally followed by 1 more word
        //       (handles "Vitamin A", "Vitamin D3", single words like "Taurin")
        // Amount: digit followed by up to 9 more digits/separators/spaces
        // Unit: explicit per-kg units OR bare units when /kg is in the section header
        //       Bare mg/IE/IU/µg/g are common on multi-language EU labels where the
        //       section header already contains "/kg" (e.g. "Zusatzstoffe/kg: Taurin 570mg")
        //       Longer forms come first to avoid "mg" matching inside "mg/kg".
        let nameGroup = #"([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\-]{2,}(?:\s+[A-Za-zÄÖÜäöüß0-9][A-Za-zÄÖÜäöüß0-9\-]*)?)"#
        let amountGroup = #"(\d[\d\.,\s]{0,9})"#
        let unitGroup   = additiveUnitPattern
        let pattern = nameGroup + #"\s+"# + amountGroup + #"\s*"# + unitGroup
        return try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive])
    }()

    /// Captures common additive declarations where the amount comes before the
    /// substance name, e.g. "15.000I.E. Vitamin A" or "540µg Biotin".
    private static let amountFirstEntryRegex: NSRegularExpression? = {
        let amountGroup = #"(\d[\d\.,\s]{0,9})"#
        let unitGroup = additiveUnitPattern
        let nameGroup = #"(Vitamin\s+[A-Za-z0-9]+|[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9\-]{2,})"#
        let pattern = amountGroup + #"\s*"# + unitGroup + #"\s+"# + nameGroup
        return try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive])
    }()

    /// Captures: (1) E-number (old Directive 70/524/EEC format), (2) amount raw text, (3) unit
    private static let eNumberRegex: NSRegularExpression? = {
        let eNumGroup   = #"(E\s*\d{3,4}[a-z]?)"#
        let amountGroup = #"(\d[\d\.,\s]{0,9})"#
        let unitGroup   = #"(mg/kg|g/kg|[Il]\.?\s?E\.?/kg|IE/kg|IU/kg|KBE/kg|CFU/kg|µg/kg|mcg/kg|æg/kg|mg/l|%)"#
        let pattern = #"\b"# + eNumGroup + #"\s+"# + amountGroup + #"\s*"# + unitGroup
        return try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive])
    }()

    private static let additiveUnitPattern =
        #"(mg/kg|g/kg|[Il]\.?\s?E\.?/kg|IE/kg|IU/kg|KBE/kg|CFU/kg|µg/kg|mcg/kg|æg/kg|mg/l|%|[Il]\.?\s?E\.?|IE|IU|µg|mcg|æg|mg|\bg\b)"#

    /// Captures: (1) new EU 1831/2003 kennnummer, (2) amount raw text, (3) unit
    /// Format: 1-2 leading digits + 1-2 letters + digits + optional trailing letters
    /// Examples on labels: 3a300 200 mg/kg, 1m558 5000 mg/kg, 2b620i 500 mg/kg
    private static let kennnummerRegex: NSRegularExpression? = {
        let kNumGroup   = #"(\d{1,2}[a-zA-Z]{1,2}\d+[a-zA-Z]{0,4})"#
        let amountGroup = #"(\d[\d\.,\s]{0,9})"#
        let unitGroup   = #"(mg/kg|g/kg|IE/kg|IU/kg|KBE/kg|CFU/kg|µg/kg|mg/l|%)"#
        let pattern = #"\b"# + kNumGroup + #"\s+"# + amountGroup + #"\s*"# + unitGroup
        return try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive])
    }()

    // MARK: - Public API

    /// Returns `true` when the text contains at least one structured additive
    /// declaration (substance name + numeric amount + unit) — no DB lookup needed.
    static func hasStructuredDeclaration(in text: String, config: AdditiveParserConfig? = nil) -> Bool {
        !extractRawEntries(from: text, config: config).isEmpty
    }

    /// Parses all additive declarations from OCR text and matches them against
    /// the provided additive database.
    ///
    /// - Parameters:
    ///   - text:      The (merged, deduplicated) OCR text from the label.
    ///   - additives: Loaded additive database entries for DB matching.
    ///   - config:    Optional DB-driven parser config; falls back to built-in defaults when nil.
    /// - Returns: Parsed and DB-matched declarations, deduplicated by substance name **and**
    ///            identifier label. Both old E-numbers (e.g. "E310") and new EU 1831/2003
    ///            kennnummern (e.g. "3a300", "1m558") are treated as fallback identifiers:
    ///            when the same substance was already found by its chemical/common name and
    ///            the DB link is known, the redundant identifier entry is suppressed.
    static func parse(text: String, additives: [Additive], config: AdditiveParserConfig? = nil) -> [AdditiveDeclaration] {
        let rawEntries = extractRawEntries(from: text, config: config)
        guard !rawEntries.isEmpty else { return [] }

        // Pass 1 — deduplicate exact repeated declarations, run DB matching.
        // Keep the same substance when OCR exposes different unit variants
        // ("540æg Biotin" and "15.000 mcg Biotin") so they remain reviewable.
        var seen = Set<String>()
        var all: [AdditiveDeclaration] = []
        for entry in rawEntries {
            let unitKey = entry.amount?.unit.lowercased().replacingOccurrences(of: " ", with: "") ?? ""
            let valueKey = entry.amount.map { String(format: "%.6f", $0.value) } ?? ""
            let key = [
                entry.name.lowercased().trimmingCharacters(in: .whitespaces),
                valueKey,
                unitKey
            ].joined(separator: "|")
            guard seen.insert(key).inserted else { continue }
            let (confidence, matched) = matchToDatabase(substanceName: entry.name,
                                                        additives: additives)
            all.append(AdditiveDeclaration(
                substanceName: entry.name,
                amount: entry.amount,
                rawText: entry.rawText,
                confidence: confidence,
                matchedAdditive: matched
            ))
        }

        // Pass 2 — suppress redundant identifier entries.
        // Both old E-numbers (e.g. "E310") and new EU 1831/2003 kennnummern (e.g. "3a300")
        // are fallback identifiers. If the same substance was already captured under its
        // chemical/common name and the DB provides the kennnummer link, the bare identifier
        // entry is dropped to avoid duplicates.
        //
        // Cross-format dedup: "1m558" (new format) and "E 558" (old format) describe the same
        // substance. relatedKennnummern() finds all DB entries sharing the same numeric core
        // (the significant digit sequence, e.g. "558") and adds their normalised kennnummern
        // to the covered set, bridging the format gap without needing an explicit mapping table.
        var coveredIdentifiers = Set<String>()
        for decl in all where !looksLikeIdentifier(decl.substanceName) {
            guard let k = decl.matchedAdditive?.eNumber, !k.isEmpty else { continue }
            coveredIdentifiers.insert(normalizeENumber(k))
            coveredIdentifiers.formUnion(relatedKennnummern(k, in: additives))
        }
        guard !coveredIdentifiers.isEmpty else { return all }

        return all.filter { decl in
            guard looksLikeIdentifier(decl.substanceName) else { return true }
            return !coveredIdentifiers.contains(normalizeENumber(decl.substanceName))
        }
    }

    // MARK: - Identifier helpers (E-numbers + kennnummern)

    /// Returns true when `name` looks like an old-style E-number (e.g. "E306", "E 300", "E160a").
    /// Internal (not private) so it can be tested directly.
    static func looksLikeENumber(_ name: String) -> Bool {
        let n = name.uppercased().replacingOccurrences(of: " ", with: "")
        guard n.hasPrefix("E"), n.count >= 4 else { return false }
        return n.dropFirst().prefix(3).allSatisfy(\.isNumber)
    }

    /// Returns true when `name` looks like a new EU 1831/2003 kennnummer
    /// (e.g. "3a300", "1m558", "2b620i", "3c322IV").
    /// Format: 1–2 leading digits + 1–2 letters + digits + optional trailing letters.
    static func looksLikeKennnummer(_ name: String) -> Bool {
        let n = name.replacingOccurrences(of: " ", with: "")
        guard n.count >= 4 else { return false }
        let pattern = #"^\d{1,2}[a-zA-Z]{1,2}\d+[a-zA-Z]{0,4}$"#
        return n.range(of: pattern, options: .regularExpression) != nil
    }

    /// Returns true when `name` is any kind of substance identifier label
    /// — either an old E-number or a new EU 1831/2003 kennnummer.
    static func looksLikeIdentifier(_ name: String) -> Bool {
        looksLikeENumber(name) || looksLikeKennnummer(name)
    }

    /// Normalises an identifier to a canonical uppercase no-space form.
    /// Strips spaces, asterisks (used in DB for legacy entries), and uppercases.
    /// "E 306" → "E306", "E 310*" → "E310", "3a300" → "3A300"
    static func normalizeENumber(_ raw: String) -> String {
        raw.uppercased()
            .replacingOccurrences(of: " ", with: "")
            .replacingOccurrences(of: "*", with: "")
    }

    /// Extracts the significant numeric sequence from a kennnummer.
    /// The EU kept the same number across both systems (old "E 558*" → new "1m558"),
    /// so the longest 2+-digit run is a reliable link between formats.
    ///   "E 310*" → "310",  "1m558" → "558",  "3a300" → "300",  "3c322IV" → "322"
    private static func numericCore(_ kennnummer: String) -> String? {
        let n = normalizeENumber(kennnummer)
        let matches = n.matches(of: /\d{2,}/).map { String(n[$0.range]) }
        return matches.max(by: { $0.count < $1.count })
    }

    /// Returns the normalised kennnummern of ALL DB entries that share the same
    /// numeric core as `kennnummer` — bridging old E-numbers and new 1831/2003 codes.
    /// Only produces results when the DB actually has cross-format entries; no guessing.
    private static func relatedKennnummern(_ kennnummer: String, in additives: [Additive]) -> Set<String> {
        guard let core = numericCore(kennnummer), !core.isEmpty else { return [] }
        var result = Set<String>()
        for additive in additives {
            let k = additive.eNumber
            guard !k.isEmpty, let kCore = numericCore(k), kCore == core else { continue }
            result.insert(normalizeENumber(k))
        }
        return result
    }

    // MARK: - Raw entry extraction

    private static func extractRawEntries(
        from text: String,
        config: AdditiveParserConfig? = nil
    ) -> [(name: String, amount: ParsedAdditiveAmount?, rawText: String)] {
        var results: [(name: String, amount: ParsedAdditiveAmount?, rawText: String)] = []
        results.append(contentsOf: extractFromSections(text, config: config))
        results.append(contentsOf: extractENumberEntries(text))       // old E-number fallback
        results.append(contentsOf: extractKennnummerEntries(text))    // new kennnummer fallback
        return results
    }

    // MARK: - Section-based extraction

    private static func extractFromSections(
        _ text: String,
        config: AdditiveParserConfig? = nil
    ) -> [(name: String, amount: ParsedAdditiveAmount?, rawText: String)] {
        let headers = config?.sectionHeaders.isEmpty == false
            ? config!.sectionHeaders
            : defaultSectionHeaders
        let textLower = text.lowercased()
        var sectionStarts: [String.Index] = []

        for header in headers {
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
            let exclusions = config?.analyticalExclusions.isEmpty == false
                ? config!.analyticalExclusions
                : defaultAnalyticalPrefixes
            let sectionText = String(text[start..<end])
            results.append(contentsOf: applyEntryRegex(entryRegex, to: sectionText, exclusions: exclusions))
            results.append(contentsOf: applyAmountFirstEntryRegex(amountFirstEntryRegex, to: sectionText, exclusions: exclusions))
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

    // MARK: - Kennnummer unconditional extraction

    /// Extracts new EU 1831/2003 kennnummer entries ("3a300 200 mg/kg") from anywhere in text.
    private static func extractKennnummerEntries(
        _ text: String
    ) -> [(name: String, amount: ParsedAdditiveAmount?, rawText: String)] {
        guard let regex = kennnummerRegex else { return [] }
        let nsText = text as NSString
        let fullRange = NSRange(location: 0, length: nsText.length)
        var results: [(name: String, amount: ParsedAdditiveAmount?, rawText: String)] = []

        for match in regex.matches(in: text, range: fullRange) {
            guard let nameRange   = Range(match.range(at: 1), in: text),
                  let amountRange = Range(match.range(at: 2), in: text),
                  let unitRange   = Range(match.range(at: 3), in: text),
                  let matchRange  = Range(match.range,        in: text) else { continue }

            // Preserve kennnummer case as found (normalisation happens in dedup pass)
            let name      = String(text[nameRange])
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
        to text: String,
        exclusions: [String]
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

            let cleanedName = cleanSubstanceName(name)
            guard !isAnalyticalConstituent(cleanedName, exclusions: exclusions) else { continue }

            let parsed = parseNumber(amountRaw).map {
                ParsedAdditiveAmount(value: $0, unit: unit, rawText: amountRaw)
            }
            results.append((name: cleanedName, amount: parsed, rawText: rawText))
        }
        return results
    }

    private static func applyAmountFirstEntryRegex(
        _ regex: NSRegularExpression?,
        to text: String,
        exclusions: [String]
    ) -> [(name: String, amount: ParsedAdditiveAmount?, rawText: String)] {
        guard let regex else { return [] }
        let nsText = text as NSString
        let fullRange = NSRange(location: 0, length: nsText.length)
        var results: [(name: String, amount: ParsedAdditiveAmount?, rawText: String)] = []

        for match in regex.matches(in: text, range: fullRange) {
            guard let amountRange = Range(match.range(at: 1), in: text),
                  let unitRange   = Range(match.range(at: 2), in: text),
                  let nameRange   = Range(match.range(at: 3), in: text),
                  let matchRange  = Range(match.range,        in: text) else { continue }

            let amountRaw = String(text[amountRange]).trimmingCharacters(in: .whitespaces)
            let unit      = String(text[unitRange])
            let name      = cleanSubstanceName(String(text[nameRange]).trimmingCharacters(in: .whitespaces))
            let rawText   = String(text[matchRange])

            guard !isAnalyticalConstituent(name, exclusions: exclusions) else { continue }

            let parsed = parseNumber(amountRaw).map {
                ParsedAdditiveAmount(value: $0, unit: unit, rawText: amountRaw)
            }
            results.append((name: name, amount: parsed, rawText: rawText))
        }
        return results
    }

    private static func cleanSubstanceName(_ raw: String) -> String {
        let separators = [" als ", " as ", " como ", " en tant que "]
        var cleaned = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        for separator in separators {
            if let range = cleaned.range(of: separator, options: [.caseInsensitive]) {
                cleaned = String(cleaned[..<range.lowerBound])
            }
        }
        return cleaned.trimmingCharacters(in: CharacterSet(charactersIn: " ,;:-()"))
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

    private static func isAnalyticalConstituent(_ name: String, exclusions: [String]) -> Bool {
        let normalized = name.lowercased()
            .replacingOccurrences(of: "-", with: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        let exactOnly = Set([
            "natrium", "phosphor", "stärke", "zucker", "kalium", "chlorid", "calcium"
        ])

        return exclusions.contains { exclusion in
            let e = exclusion.lowercased()
            if exactOnly.contains(e) {
                return normalized == e
            }
            return normalized.hasPrefix(e)
        }
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

        // 2. Old E-number match (e.g. "E306" or "E 306")
        let eNorm = nameLower.replacingOccurrences(of: " ", with: "")
        if eNorm.hasPrefix("e"), eNorm.count >= 4,
           Int(eNorm.dropFirst()) != nil {
            if let match = additives.first(where: {
                $0.eNumber.lowercased().replacingOccurrences(of: " ", with: "") == eNorm
            }) {
                return (.exactMatch, match)
            }
        }

        // 2b. New EU 1831/2003 kennnummer match (e.g. "3a300", "1m558", "2b620i")
        if looksLikeKennnummer(substanceName) {
            let kNorm = normalizeENumber(substanceName)  // uppercase, strip spaces/*
            if let match = additives.first(where: {
                normalizeENumber($0.eNumber) == kNorm
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
