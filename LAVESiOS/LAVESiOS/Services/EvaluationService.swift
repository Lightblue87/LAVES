import Foundation

enum EvaluationState {
    case unauffaellig
    case auffaellig
    case nichtBewertbar

    var title: String {
        switch self {
        case .unauffaellig: return "UNAUFFÄLLIG"
        case .auffaellig: return "AUFFÄLLIG"
        case .nichtBewertbar: return "NICHT BEWERTBAR"
        }
    }

    var icon: String {
        switch self {
        case .unauffaellig: return "checkmark.circle.fill"
        case .auffaellig: return "exclamationmark.triangle.fill"
        case .nichtBewertbar: return "questionmark.circle.fill"
        }
    }

    static let schnellcheckDisclaimer = "Mobiler Schnellcheck – keine rechtsverbindliche Aussage. Finale Bewertung erforderlich."
}

struct EvaluationResult: Identifiable {
    let id = UUID()
    let state: EvaluationState
    let lines: [String]
}

struct EvaluationService {

    // Mirrors CATEGORY_SPECIES_KEYWORDS from the desktop app (laves_eval.py)
    static let categorySpeciesKeywords: [String: [String: String]] = [
        "Schweine": [
            "schwein": "Schweine", "ferkel": "Ferkel", "sau": "Sauen"
        ],
        "Geflügel": [
            "masthuh": "Masthühner", "legehuh": "Legehennen", "junghen": "Junghennen",
            "lege": "Legehennen", "henne": "Hennen", "huhn": "Hühner",
            "truthahn": "Truthühner", "truthühn": "Truthühner",
            "ente": "Enten", "gans": "Gänse", "ziervog": "Ziervögel",
            "geflüg": "Geflügel", "vogel": "Vögel"
        ],
        "Rinder": [
            "mastrin": "Mastrinder", "milchkuh": "Milchkühe",
            "rind": "Rinder", "kalb": "Kälber", "kuh": "Kühe",
            "bulle": "Bullen", "wiederkä": "Wiederkäuer"
        ],
        "Schafe/Ziegen": [
            "schaf": "Schafe", "lamm": "Lämmer", "ziege": "Ziegen", "bock": "Böcke"
        ],
        "Heimtiere": [
            "hund": "Hunde", "katze": "Katzen", "kaninchen": "Kaninchen",
            "pferd": "Pferde", "pony": "Ponys", "esel": "Esel"
        ],
        "Fische/Krebstiere": [
            "fisch": "Fische", "krebs": "Krebstiere", "forelle": "Forellen",
            "lachs": "Lachs", "garnele": "Garnelen"
        ],
        "Sonstige": [
            "strauß": "Strauße", "mastkan": "Mastkaninchen", "kaninchen": "Kaninchen",
            "pferd": "Pferde", "hase": "Hasen", "zier": "Ziervögel"
        ]
    ]

    // Reverse map: canonical species name → longest keyword (for matching in candidates)
    private static let speciesNameToKeyword: [String: String] = {
        var result: [String: String] = [:]
        for (_, keywords) in categorySpeciesKeywords {
            for (keyword, canonical) in keywords {
                if let existing = result[canonical] {
                    if keyword.count > existing.count { result[canonical] = keyword }
                } else {
                    result[canonical] = keyword
                }
            }
        }
        return result
    }()

    // Extracts canonical individual species names from a raw species text string.
    // Mirrors extract_individual_species() in laves_eval.py.
    static func extractIndividualSpecies(from speciesText: String, category: String? = nil) -> Set<String> {
        let normalized = speciesText
            .folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current)
            .replacingOccurrences(of: "\n", with: " ")
            .replacingOccurrences(of: ";", with: " ")
        guard !normalized.isEmpty else { return [] }

        let keywords: [String: String]
        if let category, let catKeywords = categorySpeciesKeywords[category] {
            keywords = catKeywords
        } else {
            keywords = categorySpeciesKeywords.values.reduce(into: [:]) { $0.merge($1) { $1 } }
        }

        var result = Set<String>()
        for (keyword, canonical) in keywords {
            let nk = keyword.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current)
            if normalized.contains(nk) { result.insert(canonical) }
        }
        return result
    }

    static func candidates(
        in additives: [Additive],
        eNumber: String,
        substance: String,
        animalCategory: String,
        selectedSpecies: String = "Alle Tierarten"
    ) -> [Additive] {
        let eQuery = eNumber.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let sQuery = substance.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()

        return additives.filter { additive in
            let matchesENumber = eQuery.isEmpty || additive.eNumber.lowercased() == eQuery
            let matchesSubstance = sQuery.isEmpty || additive.name.lowercased().contains(sQuery)
            let matchesCategory = animalCategory == "Alle Kategorien"
                || additive.animalCategory == animalCategory
                || additive.animalCategory == "Alle Tierarten"
                || additive.animalCategory == nil
            let matchesSpecies: Bool
            if selectedSpecies == "Alle Tierarten" || additive.normalizedSpecies == "Alle Tierarten" {
                matchesSpecies = true
            } else if let keyword = speciesNameToKeyword[selectedSpecies] {
                let normalizedText = additive.normalizedSpecies
                    .folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current)
                let normalizedKeyword = keyword
                    .folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current)
                matchesSpecies = normalizedText.contains(normalizedKeyword)
            } else {
                matchesSpecies = additive.normalizedSpecies.localizedCaseInsensitiveContains(selectedSpecies)
            }
            return matchesENumber && matchesSubstance && matchesCategory && matchesSpecies
        }
    }

    static func evaluate(value: Double, additive: Additive) -> EvaluationResult {
        let hasMin = additive.minMgKg != nil
        let hasMax = additive.maxMgKg != nil
        let unit = additive.unit ?? "mg/kg"

        guard hasMin || hasMax else {
            return EvaluationResult(
                state: .nichtBewertbar,
                lines: metadataLines(
                    for: additive,
                    prefix: ["Keine Grenzwerte im Datensatz hinterlegt."]
                )
            )
        }

        var ok = true
        var lines: [String] = []

        if let min = additive.minMgKg, value < min {
            ok = false
            lines.append("Unterschreitung: \(format(value)) \(unit) < \(format(min)) \(unit)")
        }

        if let max = additive.maxMgKg, value > max {
            ok = false
            lines.append("Überschreitung: \(format(value)) \(unit) > \(format(max)) \(unit)")
        }

        if ok {
            lines.append("Ergebnis: KONFORM mit den hinterlegten Grenzwerten.")
        }

        var limitParts: [String] = []
        if let min = additive.minMgKg {
            limitParts.append("Mindestwert: \(format(min)) \(unit)")
        }
        if let max = additive.maxMgKg {
            limitParts.append("Höchstwert: \(format(max)) \(unit)")
        }
        lines.append("Hinterlegte Grenzwerte: " + limitParts.joined(separator: " | "))

        return EvaluationResult(
            state: ok ? .unauffaellig : .auffaellig,
            lines: metadataLines(for: additive, prefix: lines)
        )
    }

    static func filteredSubstances(
        in additives: [Additive],
        eNumber: String,
        animalCategory: String,
        selectedSpecies: String
    ) -> [String] {
        let matches = candidates(in: additives, eNumber: eNumber, substance: "",
                                 animalCategory: animalCategory, selectedSpecies: selectedSpecies)
        return Array(Set(matches.map(\.name).filter { !$0.isEmpty })).sorted()
    }

    static func filteredENumbers(
        in additives: [Additive],
        substance: String,
        animalCategory: String,
        selectedSpecies: String
    ) -> [String] {
        let matches = candidates(in: additives, eNumber: "", substance: substance,
                                 animalCategory: animalCategory, selectedSpecies: selectedSpecies)
        return Array(Set(matches.map(\.eNumber).filter { !$0.isEmpty })).sorted()
    }

    // Resolves the E-number for an exact substance name. The picker always
    // provides exact names, so we try exact match first before falling back
    // to contains — this avoids "L-Carnitin" ambiguously matching
    // "L-Carnitin-L-Tartrat" and returning two E-numbers instead of one.
    static func eNumberForSubstance(
        in additives: [Additive],
        substanceName: String,
        animalCategory: String,
        selectedSpecies: String
    ) -> String? {
        let sQuery = substanceName.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let base = candidates(in: additives, eNumber: "", substance: "",
                              animalCategory: animalCategory, selectedSpecies: selectedSpecies)
        // Exact match first
        let exactE = Array(Set(base
            .filter { $0.name.lowercased() == sQuery }
            .map(\.eNumber).filter { !$0.isEmpty }))
        if exactE.count == 1 { return exactE[0] }
        // Contains fallback
        let containsE = Array(Set(base
            .filter { $0.name.lowercased().contains(sQuery) }
            .map(\.eNumber).filter { !$0.isEmpty }))
        if containsE.count == 1 { return containsE[0] }
        return nil
    }

    static func batchConcentrationMgKg(percent: Double) -> Double {
        percent * 10_000
    }

    static func massKg(batchKg: Double, percent: Double) -> Double {
        batchKg * percent / 100
    }

    static func batchKg(value: Double, unit: String) -> Double {
        switch unit {
        case "g": return value / 1_000
        case "t": return value * 1_000
        default: return value
        }
    }

    private static func metadataLines(for additive: Additive, prefix: [String]) -> [String] {
        var lines = prefix
        lines.append("Zusatzstoff: \(additive.displayTitle)")
        lines.append("Tierarten: \(additive.normalizedSpecies)")
        if let regulation = additive.regulation, !regulation.isEmpty {
            lines.append("Rechtsgrundlage: \(regulation)")
        }
        if let sourceFile = additive.sourceFile {
            let page = additive.sourcePage.map { ":S.\($0)" } ?? ""
            lines.append("Quelle: \(sourceFile)\(page)")
        }
        return lines
    }

    private static func format(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(0...3)))
    }
}
