import Foundation

/// Suchdienst im Einzelfuttermittelkatalog (VO (EU) Nr. 68/2013).
///
/// Reine Wertstruktur mit statischen Methoden – kein State, keine Seiteneffekte.
struct FeedMaterialLookupService {

    // MARK: - Suche

    /// Sucht Einträge nach einem freien Suchtext.
    /// Trifft auf Katalognummer, Namen und Beschreibung.
    static func search(
        query: String,
        in materials: [FeedMaterial],
        maxResults: Int = 50
    ) -> [FeedMaterial] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { return [] }

        let normalized = normalize(q)
        var results: [(FeedMaterial, Int)] = []

        for m in materials {
            let score = matchScore(query: normalized, material: m)
            if score > 0 { results.append((m, score)) }
        }

        return results
            .sorted { $0.1 > $1.1 }
            .prefix(maxResults)
            .map(\.0)
    }

    /// Prüft, ob ein OCR-extrahierter Zutatenname mit einem Katalogeintrag übereinstimmt.
    static func findBestMatch(
        for text: String,
        in materials: [FeedMaterial]
    ) -> FeedMaterial? {
        let normalized = normalize(text)
        guard normalized.count >= 3 else { return nil }

        var best: (FeedMaterial, Int)? = nil
        for m in materials {
            let score = matchScore(query: normalized, material: m)
            if score > 0 {
                if let current = best {
                    if score > current.1 { best = (m, score) }
                } else {
                    best = (m, score)
                }
            }
        }
        return best?.0
    }

    /// Gibt alle Einträge eines Kapitels zurück.
    static func materials(forChapter chapter: Int, in materials: [FeedMaterial]) -> [FeedMaterial] {
        materials.filter { $0.chapter == chapter }
    }

    // MARK: - Private

    private static func matchScore(query: String, material: FeedMaterial) -> Int {
        let name = normalize(material.nameDe)
        let desc = normalize(material.descriptionDe)
        let num  = material.catalogNumber

        // Exakte Übereinstimmung Katalognummer
        if num == query { return 100 }

        // Katalognummer enthält Query (z.B. "2.14" → alle 2.14.x)
        if num.hasPrefix(query + ".") || num == query { return 90 }

        // Exakter Name-Match
        if name == query { return 80 }

        // Name beginnt mit Query
        if name.hasPrefix(query) { return 70 }

        // Query ist Teilstring des Namens
        if name.contains(query) { return 50 }

        // Query ist Teilstring der Beschreibung
        if desc.contains(query) { return 20 }

        // Alle Wörter des Query kommen im Namen vor
        let words = query.split(separator: " ").map(String.init)
        if words.count > 1, words.allSatisfy({ name.contains($0) }) { return 40 }

        return 0
    }

    static func normalize(_ text: String) -> String {
        text
            .folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current)
            .lowercased()
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    // MARK: - DLG Positivliste

    /// Sucht in der DLG Positivliste nach einem freien Suchtext.
    static func searchDlg(
        query: String,
        in materials: [DlgFeedMaterial],
        maxResults: Int = 25
    ) -> [DlgFeedMaterial] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else { return [] }
        let normalized = normalize(q)
        var results: [(DlgFeedMaterial, Int)] = []
        for m in materials {
            let score = dlgMatchScore(query: normalized, material: m)
            if score > 0 { results.append((m, score)) }
        }
        return results.sorted { $0.1 > $1.1 }.prefix(maxResults).map(\.0)
    }

    private static func dlgMatchScore(query: String, material: DlgFeedMaterial) -> Int {
        let name = normalize(material.nameDe)
        let desc = normalize(material.descriptionDe)
        let num  = material.number
        if num == query              { return 100 }
        if num.hasPrefix(query)      { return 90 }
        if name == query             { return 80 }
        if name.hasPrefix(query)     { return 70 }
        if name.contains(query)      { return 50 }
        let words = query.split(separator: " ").map(String.init)
        if words.count > 1, words.allSatisfy({ name.contains($0) }) { return 40 }
        if desc.contains(query)      { return 20 }
        return 0
    }
}
