import Foundation

/// Ein Eintrag aus dem Katalog der Einzelfuttermittel (VO (EU) Nr. 68/2013).
struct FeedMaterial: Identifiable, Hashable {
    let catalogNumber: String      // z.B. "2.14.3"
    let chapter: Int               // 1–12
    let chapterNameDe: String
    let nameDe: String
    let descriptionDe: String
    let mandatoryDeclarationsDe: String  // Kommagetrennte Pflichtangaben
    let restrictionsDe: String
    let regulation: String         // "68/2013"

    var id: String { catalogNumber }

    var mandatoryDeclarationList: [String] {
        mandatoryDeclarationsDe
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
    }

    /// Kurzanzeige: Katalognummer + Name
    var displayTitle: String { "\(catalogNumber) \(nameDe)" }
}
