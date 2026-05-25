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

    /// Versucht, aus einem langen OCR-Text automatisch den passenden DLG-Eintrag zu ermitteln.
    ///
    /// Gibt nil zurück, wenn kein Eintrag mit einem Score ≥ `minScore` gefunden wird.
    static func findBestDlgMatch(
        for ocrText: String,
        in materials: [DlgFeedMaterial],
        minScore: Int = 50
    ) -> DlgFeedMaterial? {
        let normalizedOCR = normalize(ocrText)
        guard normalizedOCR.count >= 10 else { return nil }

        var best: (DlgFeedMaterial, Int)? = nil
        for m in materials {
            let score = dlgTextScore(ocrText: normalizedOCR, material: m)
            if score >= minScore {
                if let current = best {
                    if score > current.1 { best = (m, score) }
                } else {
                    best = (m, score)
                }
            }
        }
        return best?.0
    }

    /// Bewertet, wie gut der OCR-Text zu einem DLG-Eintrag passt.
    /// (Umkehrung von `dlgMatchScore`: hier suchen wir den Materialnamen IM OCR-Text.)
    private static func dlgTextScore(ocrText: String, material: DlgFeedMaterial) -> Int {
        let name = normalize(material.nameDe)
        guard name.count >= 4 else { return 0 }

        // Ganzer Name im OCR-Text enthalten → Score proportional zur Namenslänge
        if ocrText.contains(name) { return 50 + min(name.count, 50) }

        // Alle Wörter (≥ 4 Zeichen) des Namens im OCR-Text enthalten
        let words = name.split(separator: " ").map(String.init).filter { $0.count >= 4 }
        if words.count >= 2, words.allSatisfy({ ocrText.contains($0) }) {
            return 40 + words.count * 3
        }

        return 0
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
