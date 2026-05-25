import Foundation

/// Prüft einen OCR-Text gegen die Kennzeichnungsanforderungen eines DLG-Positivliste-Eintrags.
///
/// Kein Netzwerkzugriff, keine externen APIs.
/// Reine Offline-Prüfung auf Basis erkannter OCR-Daten.
struct DlgLabelingCheckService {

    // MARK: - Haupteinstiegspunkt

    /// Vergleicht den OCR-Text mit den Kennzeichnungsangaben des DLG-Eintrags.
    ///
    /// - Parameters:
    ///   - ocrText: Zusammengeführter OCR-Text des gescannten Etiketts.
    ///   - material: Der identifizierte DLG-Positivliste-Eintrag.
    /// - Returns: `DlgCheckResult` mit je einem `DlgNutrientFinding` pro Anforderung.
    static func check(ocrText: String, material: DlgFeedMaterial) -> DlgCheckResult {
        let requirements = DlgLabelingParser.parse(material.labelingDe)

        guard !requirements.isEmpty else {
            // labelingDe war leer oder enthielt keine bekannten Nährstoffe
            return DlgCheckResult(material: material, findings: [])
        }

        let normalizedOCR = normalize(ocrText)

        let findings = requirements.map { req -> DlgNutrientFinding in
            let normalizedNutrient = normalize(req.nutrient)
            if normalizedOCR.contains(normalizedNutrient) {
                let snippet = extractSnippet(for: req.nutrient, in: ocrText)
                return DlgNutrientFinding(
                    requirement: req,
                    status: .found,
                    matchedText: snippet
                )
            } else if req.isMandatory {
                return DlgNutrientFinding(
                    requirement: req,
                    status: .missing,
                    matchedText: nil
                )
            } else {
                return DlgNutrientFinding(
                    requirement: req,
                    status: .conditionalAbsent,
                    matchedText: nil
                )
            }
        }

        return DlgCheckResult(material: material, findings: findings)
    }

    // MARK: - Hilfsfunktionen

    private static func normalize(_ text: String) -> String {
        text.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current)
            .lowercased()
    }

    private static func extractSnippet(for nutrient: String, in text: String) -> String {
        guard let range = text.range(of: nutrient, options: [.caseInsensitive, .diacriticInsensitive]) else {
            return nutrient
        }
        let start = text.index(range.lowerBound, offsetBy: -15, limitedBy: text.startIndex) ?? text.startIndex
        let end   = text.index(range.upperBound,  offsetBy: 30,  limitedBy: text.endIndex)   ?? text.endIndex
        return "…" + text[start..<end].replacingOccurrences(of: "\n", with: " ").trimmingCharacters(in: .whitespaces) + "…"
    }
}
