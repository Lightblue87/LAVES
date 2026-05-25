import Foundation

/// Parst das `labeling_de`-Feld eines DLG-Positivliste-Eintrags.
///
/// Das Feld enthält kommagetrennte Nährstoffangaben, z.B.:
///   "Rohprotein, Rohfaser, Rohfett, Rohasche, Stärke, Feuchte"
///   "Rohprotein, Rohfaser, Calcium, Phosphor, Natrium"
///   "Rohprotein, Rohfett, Rohfaser, Rohasche, Stärke, wenn als Energiefuttermittel verwendet"
///
/// Ein Nährstoff ist **Pflicht** (mandatory), wenn kein `, wenn`-Zusatz folgt.
/// Ein Nährstoff ist **bedingt** (conditional), wenn `, wenn …` im selben Segment steht.
struct DlgLabelingParser {

    // MARK: - Bekannte Nährstoffe (längste zuerst – verhindert Teilüberlappungen)

    static let knownNutrients: [String] = [
        "salzsäureunlösliche Asche",
        "Gesamtzucker, berechnet als Saccharose",
        "Gesamtzucker",
        "Ammoniumstickstoff",
        "Stickstoff",
        "Calciumcarbonat",
        "Propylenglycol",
        "Bitterstoffe",
        "Cellobiose",
        "Rohprotein",
        "Rohfaser",
        "Rohfett",
        "Rohasche",
        "Calcium",
        "Phosphor",
        "Natrium",
        "Magnesium",
        "Kalium",
        "Schwefel",
        "Chlorid",
        "Saccharose",
        "Laktose",
        "Lactose",
        "Fructose",
        "Glucose",
        "Dextrose",
        "Stärke",
        "Feuchte",
        "Inulin",
        "Glycerin",
        "Gossypol",
        "Jodzahl",
    ]

    // MARK: - Parsing

    /// Gibt die Nährstoffanforderungen zurück, die im `labeling_de`-Feld kodiert sind.
    static func parse(_ labelingDe: String) -> [DlgNutrientRequirement] {
        let text = labelingDe.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, text != "–", text != "-" else { return [] }

        // Tokenisiere: Finde alle bekannten Nährstoffe (case-/diakritik-insensitiv, längste zuerst)
        var hits: [(range: Range<String.Index>, nutrient: String)] = []
        let normalized = normalize(text)
        for nutrient in knownNutrients {
            let normNutrient = normalize(nutrient)
            var searchStart = normalized.startIndex
            while let range = normalized.range(of: normNutrient, options: [.caseInsensitive, .diacriticInsensitive], range: searchStart..<normalized.endIndex) {
                // Kein Überlappen mit bereits gefundenen Treffern
                let overlaps = hits.contains { existing in
                    existing.range.overlaps(range)
                }
                if !overlaps {
                    hits.append((range: range, nutrient: nutrient))
                }
                searchStart = range.upperBound
            }
        }

        guard !hits.isEmpty else { return [] }

        // Sortiere nach Auftreten (Reihenfolge im Text)
        hits.sort { $0.range.lowerBound < $1.range.lowerBound }

        // Bestimme für jeden Treffer: mandatory vs. conditional
        var requirements: [DlgNutrientRequirement] = []
        for i in hits.indices {
            let hit = hits[i]

            // Segment: vom Ende dieses Treffers bis zum Beginn des nächsten (oder Textende)
            let segmentStart = hit.range.upperBound
            let segmentEnd: String.Index
            if i + 1 < hits.count {
                segmentEnd = hits[i + 1].range.lowerBound
            } else {
                segmentEnd = normalized.endIndex
            }
            let segment = String(normalized[segmentStart..<segmentEnd])

            // Enthält das Segment ", wenn" oder " wenn " → bedingt
            let hasCondition = segment.contains("wenn")
            if hasCondition {
                // Extrahiere originale Bedingung aus dem Originaltext
                let origSegmentStart = text.index(text.startIndex, offsetBy: normalized.distance(from: normalized.startIndex, to: segmentStart), limitedBy: text.endIndex) ?? text.endIndex
                let origSegmentEnd = text.index(text.startIndex, offsetBy: normalized.distance(from: normalized.startIndex, to: segmentEnd), limitedBy: text.endIndex) ?? text.endIndex
                let origSegment = String(text[origSegmentStart..<origSegmentEnd])

                // Extrahiere die Bedingung nach "wenn"
                let condition: String?
                if let wennRange = origSegment.range(of: "wenn", options: [.caseInsensitive]) {
                    let afterWenn = origSegment[wennRange.upperBound...].trimmingCharacters(in: .whitespacesAndNewlines.union(CharacterSet(charactersIn: ",")))
                    condition = afterWenn.isEmpty ? nil : "wenn \(afterWenn)"
                } else {
                    condition = nil
                }
                requirements.append(DlgNutrientRequirement(
                    nutrient: hit.nutrient,
                    isMandatory: false,
                    condition: condition
                ))
            } else {
                requirements.append(DlgNutrientRequirement(
                    nutrient: hit.nutrient,
                    isMandatory: true,
                    condition: nil
                ))
            }
        }

        return requirements
    }

    // MARK: - Hilfsfunktionen

    private static func normalize(_ text: String) -> String {
        text.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current)
            .lowercased()
    }
}
