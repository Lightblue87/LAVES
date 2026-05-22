import Foundation

struct Additive: Identifiable, Decodable, Hashable {
    var id: String {
        let min = minMgKg.map { "\($0)" } ?? ""
        let max = maxMgKg.map { "\($0)" } ?? ""
        return "\(eNumber)|\(name)|\(species)|\(animalCategory ?? "")|\(min)|\(max)"
    }
    let eNumber: String
    let name: String
    let species: String
    let maxAgeDays: Double?
    let minMgKg: Double?
    let maxMgKg: Double?
    let unit: String?
    let regulation: String?
    let sourceFile: String?
    let sourcePage: Int?
    let animalCategory: String?

    enum CodingKeys: String, CodingKey {
        case eNumber = "kennnummer"
        case name
        case species = "tierarten"
        case maxAgeDays = "hoechstalter_tage"
        case minMgKg = "min_mg_kg"
        case maxMgKg = "max_mg_kg"
        case unit = "einheit"
        case regulation = "rechtsgrundlage"
        case sourceFile = "source_file"
        case sourcePage = "source_page"
        case animalCategory = "tierart_kategorie"
    }

    init(
        eNumber: String,
        name: String,
        species: String,
        maxAgeDays: Double?,
        minMgKg: Double?,
        maxMgKg: Double?,
        unit: String?,
        regulation: String?,
        sourceFile: String?,
        sourcePage: Int?,
        animalCategory: String?
    ) {
        self.eNumber = eNumber.trimmingCharacters(in: .whitespacesAndNewlines)
        self.name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        self.species = species.trimmingCharacters(in: .whitespacesAndNewlines)
        self.maxAgeDays = maxAgeDays
        self.minMgKg = minMgKg
        self.maxMgKg = maxMgKg
        self.unit = unit
        self.regulation = regulation
        self.sourceFile = sourceFile
        self.sourcePage = sourcePage
        self.animalCategory = animalCategory
    }

    var displayTitle: String {
        [eNumber, name].filter { !$0.isEmpty }.joined(separator: " - ")
    }

    var normalizedSpecies: String {
        let trimmed = species
            .replacingOccurrences(of: "Alle Tierar-\nten", with: "Alle Tierarten")
            .replacingOccurrences(of: "Alle Tier-\narten", with: "Alle Tierarten")
            .replacingOccurrences(of: "Alle\nTierarten", with: "Alle Tierarten")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? "Alle Tierarten" : trimmed
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        eNumber = try container.decodeIfPresent(String.self, forKey: .eNumber)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        name = try container.decodeIfPresent(String.self, forKey: .name)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        species = try container.decodeFlexibleString(forKey: .species) ?? "Alle Tierarten"
        maxAgeDays = try container.decodeFlexibleDouble(forKey: .maxAgeDays)
        minMgKg = try container.decodeFlexibleDouble(forKey: .minMgKg)
        maxMgKg = try container.decodeFlexibleDouble(forKey: .maxMgKg)
        unit = try container.decodeIfPresent(String.self, forKey: .unit)
        regulation = try container.decodeIfPresent(String.self, forKey: .regulation)
        sourceFile = try container.decodeIfPresent(String.self, forKey: .sourceFile)
        sourcePage = try container.decodeIfPresent(Int.self, forKey: .sourcePage)
        animalCategory = try container.decodeIfPresent(String.self, forKey: .animalCategory)
    }
}

extension KeyedDecodingContainer {
    func decodeFlexibleString(forKey key: Key) throws -> String? {
        if let value = try decodeIfPresent(String.self, forKey: key) {
            return value
        }
        if let values = try decodeIfPresent([String].self, forKey: key) {
            return values.joined(separator: ", ")
        }
        return nil
    }

    func decodeFlexibleDouble(forKey key: Key) throws -> Double? {
        if let value = try decodeIfPresent(Double.self, forKey: key) {
            return value
        }
        if let value = try decodeIfPresent(Int.self, forKey: key) {
            return Double(value)
        }
        if let value = try decodeIfPresent(String.self, forKey: key) {
            return Double(value.replacingOccurrences(of: ",", with: "."))
        }
        return nil
    }
}
