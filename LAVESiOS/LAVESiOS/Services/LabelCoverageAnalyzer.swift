import Foundation

/// Analyzes which packaging areas are covered by a multi-image OCR session and
/// determines which labeling rules should be downgraded to `.notCheckable`
/// when critical packaging areas (Boden, Deckel) were not photographed.
struct LabelCoverageAnalyzer {

    // MARK: - Rule prefixes tied to packaging location

    /// Lot number / batch designation — typically stamped on the bottom or lid.
    private static let lotNumberRulePrefix = "art15_004"

    /// MHD / best-before date — typically on the bottom, lid, or side.
    private static let mhdRulePrefixes = ["art16_002", "art17_002"]

    // MARK: - Analysis

    /// Returns rule-ID prefixes whose results should be overridden to `.notCheckable`
    /// when critical areas are missing from the session.
    ///
    /// Logic (only applied for sessions with ≥ 2 images):
    /// - No Boden **and** no Deckel image → lot number and MHD rules become notCheckable
    ///   because those are commonly printed on the bottom or lid.
    ///
    /// Important: this override only applies when the OCR itself also returned `.missing`
    /// for those rules. If OCR already found the value, the found status is preserved.
    static func forcedNotCheckableRulePrefixes(
        coveredTypes: Set<OCRImageType>,
        imageCount: Int
    ) -> Set<String> {
        guard imageCount >= 2 else { return [] }

        var prefixes = Set<String>()

        let hasBottomOrLid = coveredTypes.contains(.boden) || coveredTypes.contains(.deckel)
        if !hasBottomOrLid {
            prefixes.insert(lotNumberRulePrefix)
            prefixes.formUnion(mhdRulePrefixes)
        }

        return prefixes
    }

    /// Human-readable note added to rules forced to notCheckable by coverage analysis.
    static let missingAreaNote =
        "Boden/Deckel-Bild fehlt – Angabe möglicherweise nicht erfasst."
}
