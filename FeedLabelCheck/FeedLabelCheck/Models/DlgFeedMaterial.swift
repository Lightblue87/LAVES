import Foundation

/// Ein Eintrag aus der DLG Positivliste für Einzelfuttermittel (15. Auflage, 2023).
struct DlgFeedMaterial: Identifiable, Hashable {
    let number: String              // z.B. "01.02.01"
    let groupNum: Int               // Gruppenziffer (1–20)
    let groupNameDe: String
    let nameDe: String
    let descriptionDe: String
    let differentiationDe: String   // Differenzierungsmerkmale (v.H.)
    let requirementsDe: String      // Anforderungen (v.H.)
    let labelingDe: String          // Angaben zur Kennzeichnung
    let processDe: String           // Zusätzliche Angaben zum Herstellungsprozess
    let remarksDe: String           // Bemerkungen
    let edition: String             // Auflage (z.B. "15")

    var id: String { number }

    /// Kurzanzeige: Nummer + Name
    var displayTitle: String { "\(number) \(nameDe)" }

    /// Kennzeichnungspflichtige Inhaltsstoffe als einzelne Strings
    var labelingList: [String] {
        labelingDe
            .components(separatedBy: CharacterSet.whitespacesAndNewlines)
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty && $0 != "," }
    }
}
