import Foundation

// MARK: - ScanAnalysisService

/// Performs keyword-based analysis of merged OCR label text.
///
/// **No database, no network, no OCR** — pure text analysis on already-recognised text.
/// Called once by the Scan tab; its output is stored in `ScanEntry.analysisResult` and
/// shared with the Zusatzstoffe and Kennzeichnung modules.
struct ScanAnalysisService {

    // MARK: - Public entry point

    /// Analyses the merged OCR text produced by `MultiImageOCRSession` and returns a
    /// `ScanAnalysisResult` containing all extracted signals.
    ///
    /// - Parameters:
    ///   - mergedText: The deduplicated, merged OCR text from all scanned images.
    ///   - imageItems: Per-image OCR items (for coverage analysis). Pass `nil` for single-image scans.
    ///   - feedTypes:  Feed types from the labeling DB (optional; used for feed-type detection).
    ///                 When empty, feed-type detection is skipped.
    static func analyze(
        mergedText: String,
        imageItems: [OCRImageItem]?,
        feedTypes: [LabelingFeedType] = []
    ) -> ScanAnalysisResult {
        // Feed type detection
        let (ftId, ftConf) = detectFeedType(in: mergedText, feedTypes: feedTypes)

        // Animal/species hints (reuses IngredientScanService lexicon)
        let scanner = IngredientScanService()
        let animals = scanner.detectedAnimals(in: mergedText).map(\.label)

        // Labeling areas (keyword matching, no DB)
        let areas = detectLabelingAreas(in: mergedText)

        // Additive hints
        let hints = detectAdditiveHints(in: mergedText)

        // Image coverage
        let coverage = computeCoverage(imageItems: imageItems)

        // Quality warnings
        let warnings = generateWarnings(
            text: mergedText,
            areas: areas,
            coverage: coverage
        )

        return ScanAnalysisResult(
            detectedFeedTypeId: ftId,
            feedTypeConfidence: ftConf,
            detectedSpeciesHints: animals,
            labelingAreas: areas,
            additiveHints: hints,
            imageCoverage: coverage,
            qualityWarnings: warnings,
            analyzedAt: Date()
        )
    }

    // MARK: - Feed type detection

    private static func detectFeedType(
        in text: String,
        feedTypes: [LabelingFeedType]
    ) -> (id: String?, confidence: Double) {
        guard !feedTypes.isEmpty else { return (nil, 0) }
        let detector = LabelingFeedTypeDetector()
        guard let result = detector.detect(in: text, feedTypes: feedTypes) else { return (nil, 0) }
        return (result.feedType.id, result.confidence)
    }

    // MARK: - Labeling area detection

    /// Keywords mirroring `build_labeling_db.py` — no DB dependency.
    private static func detectLabelingAreas(in text: String) -> DetectedLabelingAreas {
        let t = text.lowercased()
        func kw(_ words: [String]) -> Bool { words.contains { t.contains($0.lowercased()) } }

        let hasComposition = kw([
            "Zusammensetzung", "Zutaten:", "Inhaltsstoffe",
            "composition", "ingredients", "composizione", "samenstelling"
        ])
        let hasAnalytical = kw([
            "Analytische Bestandteile", "Rohprotein", "Rohfett", "Rohfaser", "Rohasche",
            "analytical constituents", "crude protein", "crude fat", "crude fibre"
        ])
        let hasAdditives = kw([
            "Zusatzstoffe", "Zusatzstoff:", "Ernährungsphysiologische Zusatzstoffe",
            "Technologische Zusatzstoffe", "additives", "additivi", "additifs"
        ])
        let hasBestBefore = kw([
            "Mindesthaltbarkeit", "mindestens haltbar bis", "MHD", "BBD",
            "best before", "verwendbar bis", "haltbar bis", "ten minste houdbaar"
        ])
        let hasLot = kw([
            "Charge:", "Losnummer", "Chargennummer", "LOT", "Los:", "Partie:",
            "Partienummer", "Bezugsnummer der Partie",
            "lot number", "batch number", "numéro de lot"
        ]) || text.range(
            of: #"\b(LOT|L|Charge|Chargen-Nr\.?|Chargennummer|Los|Losnummer|Los-Nr\.?|Partie|Partienummer|Partie-Nr\.?|Partie\s+Nr\.?)(?!\w)\s?[:.\-]?\s?[A-Z0-9\-\/]*\d[A-Z0-9\-\/]*\b"#,
            options: [.regularExpression, .caseInsensitive]
        ) != nil
        let hasNetQty = kw([
            "Nettomasse", "Nettogewicht", "Nettomenge", "Netto",
            "net weight", "net contents", "poids net", "peso netto"
        ]) || text.range(
            of: #"\b\d+[,.]?\d*\s?(kg|g|t|ml|l)\s?e?\b"#,
            options: [.regularExpression, .caseInsensitive]
        ) != nil
        let hasOperator = kw([
            "GmbH", "GmbH & Co", " KG", " AG ", "Ltd.", "S.A.",
            "Hersteller:", "Vertrieb:", "Inverkehrbringer:", "verantwortlich:",
            "manufactured by", "distributed by", "hergestellt von", "hergestellt für"
        ])

        return DetectedLabelingAreas(
            hasComposition: hasComposition,
            hasAnalyticalConstituents: hasAnalytical,
            hasAdditives: hasAdditives,
            hasBestBefore: hasBestBefore,
            hasLotNumber: hasLot,
            hasNetQuantity: hasNetQty,
            hasOperator: hasOperator
        )
    }

    // MARK: - Additive hints

    private static func detectAdditiveHints(in text: String) -> AdditiveHints {
        let hasSection = ["Zusatzstoffe", "Ernährungsphysiologische", "Technologische Zusatzstoffe",
                          "Zootechnische", "Sensorische Zusatzstoffe", "additives"]
            .contains { text.localizedCaseInsensitiveContains($0) }

        let hasAmounts: Bool = {
            let pattern = #"\b\d+[,.]?\d*\s*(mg|IE|IU|µg|g)\s*/\s*kg\b"#
            return text.range(of: pattern, options: .regularExpression) != nil
        }()

        let hasENumbers: Bool = {
            let pattern = #"\bE\s*\d{3,4}[a-z]?\b"#
            return text.range(of: pattern, options: [.regularExpression, .caseInsensitive]) != nil
        }()

        let hasStructured = AdditiveDeclarationParser.hasStructuredDeclaration(in: text)

        // Extract raw substance names (no DB match needed for hints)
        let rawDecls = AdditiveDeclarationParser.parse(text: text, additives: [])
        let names = rawDecls.map(\.substanceName)

        return AdditiveHints(
            hasAdditiveSection: hasSection,
            hasAmountPatterns: hasAmounts,
            hasENumbers: hasENumbers,
            hasStructuredDeclarations: hasStructured,
            detectedSubstanceNames: names
        )
    }

    // MARK: - Image coverage

    private static func computeCoverage(imageItems: [OCRImageItem]?) -> ImageCoverage {
        guard let items = imageItems, !items.isEmpty else {
            return ImageCoverage(
                imageCount: 1,
                coveredTypes: [.vorderseite],
                missingBodenOrDeckel: false,
                forcedNotCheckableRulePrefixes: []
            )
        }

        let covered = Set(items.map(\.imageType))
        let prefixes = LabelCoverageAnalyzer.forcedNotCheckableRulePrefixes(
            coveredTypes: covered,
            imageCount: items.count
        )
        let missingBD = items.count >= 2
            && !covered.contains(.boden)
            && !covered.contains(.deckel)

        return ImageCoverage(
            imageCount: items.count,
            coveredTypes: Array(covered),
            missingBodenOrDeckel: missingBD,
            forcedNotCheckableRulePrefixes: Array(prefixes)
        )
    }

    // MARK: - Quality warnings

    private static func generateWarnings(
        text: String,
        areas: DetectedLabelingAreas,
        coverage: ImageCoverage
    ) -> [String] {
        var warnings: [String] = []

        if text.count < 150 {
            warnings.append("OCR-Text sehr kurz (\(text.count) Zeichen) – Bildqualität prüfen.")
        }

        if areas.detectedCount == 0 && text.count >= 50 {
            warnings.append("Keine bekannten Kennzeichnungsbereiche erkannt – bitte Bild prüfen.")
        }

        if coverage.missingBodenOrDeckel {
            warnings.append("Kein Boden-/Deckel-Bild – Losnummer oder MHD möglicherweise nicht sichtbar.")
        }

        return warnings
    }
}
