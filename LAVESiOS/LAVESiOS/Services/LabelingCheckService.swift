import Foundation

struct LabelingCheckService {

    // Minimum OCR text length to attempt a check
    static let minOCRLength = 40

    // MARK: - Main entry point

    static func check(
        ocrText: String,
        feedType: LabelingFeedType,
        feedTypeConfidence: Double,
        rules: [LabelingRule],
        dbInfo: LabelingDatabaseInfo?,
        /// Rule-ID prefixes for which `.missing` results are downgraded to `.notCheckable`
        /// due to missing packaging area images (see `LabelCoverageAnalyzer`).
        forcedNotCheckableRulePrefixes: Set<String> = [],
        imageItems: [OCRImageItem]? = nil
    ) -> LabelingCheckResult {
        guard ocrText.count >= minOCRLength else {
            let results = rules.map { rule in
                RuleCheckResult(rule: rule, status: .notCheckable, matchedText: nil,
                                matchedLanguage: nil, confidence: 0,
                                note: "OCR-Text zu kurz für eine Prüfung.")
            }
            return LabelingCheckResult(
                feedType: feedType,
                feedTypeConfidence: feedTypeConfidence,
                ruleResults: results,
                overallStatus: .nichtPruefbar,
                checkedAt: Date(),
                dbVersion: dbInfo?.version ?? "–",
                databaseInfo: dbInfo,
                ocrText: ocrText,
                imageItems: imageItems
            )
        }

        var ruleResults = rules.map { rule in
            checkRule(rule, in: ocrText)
        }

        // Apply coverage-based notCheckable overrides (only for .missing results)
        if !forcedNotCheckableRulePrefixes.isEmpty {
            ruleResults = ruleResults.map { result in
                guard result.status == .missing,
                      forcedNotCheckableRulePrefixes.contains(where: { result.rule.id.hasPrefix($0) }) else {
                    return result
                }
                return RuleCheckResult(
                    rule: result.rule,
                    status: .notCheckable,
                    matchedText: nil,
                    matchedLanguage: nil,
                    confidence: 0,
                    note: LabelCoverageAnalyzer.missingAreaNote
                )
            }
        }

        let overall = overallStatus(from: ruleResults)

        return LabelingCheckResult(
            feedType: feedType,
            feedTypeConfidence: feedTypeConfidence,
            ruleResults: ruleResults,
            overallStatus: overall,
            checkedAt: Date(),
            dbVersion: dbInfo?.version ?? "–",
            databaseInfo: dbInfo,
            ocrText: ocrText,
            imageItems: imageItems
        )
    }

    // MARK: - Rule checking

    static func checkRule(_ rule: LabelingRule, in text: String) -> RuleCheckResult {
        let positivePatterns = rule.patterns.filter { !$0.isNegativePattern }
        let negativePatterns = rule.patterns.filter { $0.isNegativePattern }

        guard !positivePatterns.isEmpty else {
            return RuleCheckResult(rule: rule, status: .notCheckable, matchedText: nil,
                                   matchedLanguage: nil, confidence: 0,
                                   note: "Keine Prüfmuster hinterlegt.")
        }

        // Check for negative pattern match first (exclusion)
        let hasNegativeMatch = negativePatterns.contains { match(pattern: $0, in: text) != nil }

        // Find best positive match
        var bestMatch: (text: String, language: String, weight: Double, languagePriority: Int)? = nil
        for pattern in positivePatterns {
            if let m = match(pattern: pattern, in: text) {
                let priority = languagePriority(pattern.patternLanguage)
                if bestMatch == nil
                    || priority < bestMatch!.languagePriority
                    || (priority == bestMatch!.languagePriority && pattern.confidenceWeight > bestMatch!.weight) {
                    bestMatch = (m, pattern.patternLanguage, pattern.confidenceWeight, priority)
                }
            }
        }

        if hasNegativeMatch {
            return RuleCheckResult(rule: rule, status: .unclear, matchedText: bestMatch?.text,
                                   matchedLanguage: bestMatch?.language, confidence: 0.3,
                                   note: "Ausschlussmuster erkannt – manuelle Prüfung empfohlen.")
        }

        guard let found = bestMatch else {
            let note = rule.severity == .critical
                ? "Pflichtangabe wurde im OCR-Text nicht gefunden. Bitte Etikett manuell prüfen."
                : "Angabe wurde im OCR-Text nicht gefunden. Bitte Etikett manuell prüfen."
            return RuleCheckResult(rule: rule, status: .missing, matchedText: nil,
                                   matchedLanguage: nil, confidence: 0, note: note)
        }

        let confidence = found.weight
        let status: RuleCheckStatus = confidence >= 0.85 ? .found : .probablyFound
        var notes: [String] = []
        if found.language != "de" {
            notes.append("Hinweis wurde in \(languageName(found.language)) gefunden.")
        }
        if status == .probablyFound {
            notes.append("Indirekter Treffer erkannt – Etikett bitte manuell bestätigen.")
        }
        return RuleCheckResult(rule: rule, status: status, matchedText: found.text,
                               matchedLanguage: found.language, confidence: confidence,
                               note: notes.isEmpty ? nil : notes.joined(separator: " "))
    }

    // MARK: - Overall status

    static func overallStatus(from results: [RuleCheckResult]) -> LabelingOverallStatus {
        if results.allSatisfy({ $0.status == .notCheckable }) {
            return .nichtPruefbar
        }
        let criticalMissing = results.contains {
            $0.rule.severity == .critical && $0.status == .missing
        }
        if criticalMissing { return .auffaellig }

        // Critical rule only indirectly confirmed → uncertain
        let hasCriticalUncertain = results.contains {
            $0.rule.severity == .critical
                && ($0.status == .probablyFound || $0.status == .unclear)
        }
        let hasUnclear = results.contains { $0.status == .unclear }
        let hasWarningMissing = results.contains {
            $0.rule.severity == .warning && $0.status == .missing
        }
        if hasCriticalUncertain || hasUnclear || hasWarningMissing { return .unklar }

        return .keineAuffaelligkeit
    }

    // MARK: - Pattern matching

    private static func match(pattern: LabelingRulePattern, in text: String) -> String? {
        switch pattern.patternType {
        case "keyword":
            return keywordMatch(pattern.patternValue, in: text)
        case "regex":
            return regexMatch(pattern.patternValue, in: text)
        default:
            return keywordMatch(pattern.patternValue, in: text)
        }
    }

    private static func languagePriority(_ language: String) -> Int {
        switch language.lowercased() {
        case "de": return 0
        case "en": return 1
        default: return 2
        }
    }

    static func languageName(_ language: String) -> String {
        switch language.lowercased() {
        case "de": return "Deutsch"
        case "en": return "Englisch"
        default: return "einer weiteren Sprache"
        }
    }

    private static func keywordMatch(_ keyword: String, in text: String) -> String? {
        let options: String.CompareOptions = [.caseInsensitive, .diacriticInsensitive]
        guard let range = text.range(of: keyword, options: options) else { return nil }
        // Return a snippet around the match (up to 60 chars)
        let start = text.index(range.lowerBound, offsetBy: -20, limitedBy: text.startIndex) ?? text.startIndex
        let end = text.index(range.upperBound, offsetBy: 40, limitedBy: text.endIndex) ?? text.endIndex
        return "…" + text[start..<end].replacingOccurrences(of: "\n", with: " ").trimmingCharacters(in: .whitespaces) + "…"
    }

    private static func regexMatch(_ pattern: String, in text: String) -> String? {
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]) else {
            return nil
        }
        let range = NSRange(text.startIndex..., in: text)
        guard let match = regex.firstMatch(in: text, options: [], range: range) else { return nil }
        guard let swiftRange = Range(match.range, in: text) else { return nil }
        let matchedText = String(text[swiftRange])
        // Return snippet: matched text truncated
        return matchedText.count > 80 ? String(matchedText.prefix(80)) + "…" : matchedText
    }
}
