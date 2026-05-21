import Foundation

enum EvaluationState {
    case compliant
    case nonCompliant
    case warning

    var title: String {
        switch self {
        case .compliant: return "KONFORM"
        case .nonCompliant: return "NICHT KONFORM"
        case .warning: return "PRÜFUNG NICHT MÖGLICH"
        }
    }
}

struct EvaluationResult: Identifiable {
    let id = UUID()
    let state: EvaluationState
    let lines: [String]
}

struct EvaluationService {
    static func candidates(
        in additives: [Additive],
        eNumber: String,
        substance: String,
        animalCategory: String
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
            return matchesENumber && matchesSubstance && matchesCategory
        }
    }

    static func evaluate(value: Double, additive: Additive) -> EvaluationResult {
        let hasMin = additive.minMgKg != nil
        let hasMax = additive.maxMgKg != nil
        let unit = additive.unit ?? "mg/kg"

        guard hasMin || hasMax else {
            return EvaluationResult(
                state: .warning,
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
            state: ok ? .compliant : .nonCompliant,
            lines: metadataLines(for: additive, prefix: lines)
        )
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
