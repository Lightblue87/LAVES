import XCTest
@testable import FeedLabelCheck

/// Tests for the Phase G scan architecture:
/// - `ScanAnalysisService` area detection, additive hints, coverage, quality warnings
/// - `ScanEntry` backward compatibility (decode legacy JSON without analysisResult)
/// - `ScanEntry` round-trip encode/decode with analysisResult
final class ScanArchitectureTests: XCTestCase {

    // MARK: - Helpers

    private func makeItem(_ type: OCRImageType, text: String = "test") -> OCRImageItem {
        OCRImageItem(
            id: UUID(),
            imageType: type,
            thumbnailFileName: nil,
            ocrText: text,
            capturedAt: Date()
        )
    }

    private func analyze(text: String, items: [OCRImageItem]? = nil) -> ScanAnalysisResult {
        ScanAnalysisService.analyze(mergedText: text, imageItems: items, feedTypes: [])
    }

    private var feedTypes: [LabelingFeedType] {
        [
            LabelingFeedType(
                id: "complete_feed",
                nameDe: "Alleinfuttermittel",
                descriptionDe: nil,
                keywordsDe: [
                    "Alleinfuttermittel",
                    "complete pet food",
                    "complete feed",
                    "aliment complet",
                    // Now stored in DB (previously hardcoded in expandedKeywords())
                    "Diät-Alleinfuttermittel",
                    "Diaet-Alleinfuttermittel",
                    "Diät Alleinfuttermittel",
                    "complete nutrition",
                    "100% complete nutrition"
                ]
            ),
            LabelingFeedType(
                id: "complementary_feed",
                nameDe: "Ergänzungsfuttermittel",
                descriptionDe: nil,
                keywordsDe: [
                    "Ergänzungsfuttermittel",
                    "complementary pet food",
                    "complementary feed",
                    "aliment complémentaire",
                    "alimento complementare",
                    // Now stored in DB (previously hardcoded in expandedKeywords())
                    "Ergänzungsfutermittel",
                    "Ergaenzungsfutermittel",
                    "Ergänzungsfuttermitel",
                    "Ergaenzungsfuttermitel",
                    "Ergaenzungsfuttermittel",
                    "Raufutterergänzung",
                    "supplementary feed",
                    "supplementary feed for",
                    "aanvullend diervoeder"
                ]
            ),
            LabelingFeedType(
                id: "mineral_feed",
                nameDe: "Mineralfuttermittel",
                descriptionDe: nil,
                keywordsDe: [
                    "Mineralfuttermittel",
                    "Mineral-Futtermittel",
                    "Mineralfutter"
                ]
            )
        ]
    }

    // MARK: - Labeling area detection

    func testCompositionKeywordDetected() {
        let result = analyze(text: "Zusammensetzung: Huhn 40 %, Reis 20 %")
        XCTAssertTrue(result.labelingAreas.hasComposition)
    }

    func testAdditivesKeywordDetected() {
        let text = "Zusatzstoffe: Taurin 1.000 mg/kg, Vitamin E 100 mg/kg"
        let result = analyze(text: text)
        XCTAssertTrue(result.labelingAreas.hasAdditives)
    }

    func testBestBeforeKeywordDetected() {
        let result = analyze(text: "Mindesthaltbarkeit: 12/2026")
        XCTAssertTrue(result.labelingAreas.hasBestBefore)
    }

    func testLotNumberKeywordDetected() {
        let result = analyze(text: "LOT: 20240501A")
        XCTAssertTrue(result.labelingAreas.hasLotNumber)
    }

    func testNoKeywordsDetected() {
        let result = analyze(text: "ABC DEF GHI JKL MNO PQR STU VWX YZ ABC DEF")
        XCTAssertFalse(result.labelingAreas.hasComposition)
        XCTAssertFalse(result.labelingAreas.hasAdditives)
        XCTAssertFalse(result.labelingAreas.hasBestBefore)
    }

    func testDetectedNamesReflectsFoundAreas() {
        let text = "Zusammensetzung: Fleisch. Rohprotein 28 g/100g. Mindesthaltbarkeit 12.2026."
        let result = analyze(text: text)
        let names = result.labelingAreas.detectedNames
        XCTAssertTrue(names.contains("Zusammensetzung"))
        XCTAssertTrue(names.contains("Analytische Bestandteile"))
        XCTAssertTrue(names.contains("Mindesthaltbarkeit"))
    }

    // MARK: - Additive hints

    func testStructuredAdditiveHintDetected() {
        let text = "Zusatzstoffe: Taurin 1.000 mg/kg, Vitamin E 150 mg/kg"
        let result = analyze(text: text)
        XCTAssertTrue(result.additiveHints.hasAdditiveSection)
        XCTAssertTrue(result.additiveHints.hasStructuredDeclarations)
    }

    func testAdditiveHintAmountPatternDetected() {
        let text = "Taurin 500 mg/kg"
        let result = analyze(text: text)
        XCTAssertTrue(result.additiveHints.hasAmountPatterns)
    }

    func testENumberHintDetected() {
        let text = "E 306 enthält natürliches Vitamin E"
        let result = analyze(text: text)
        XCTAssertTrue(result.additiveHints.hasENumbers)
    }

    // MARK: - Real label OCR snippets added 2026-05-25

    func testTodayLoftysRodentSnackSnippetDetectsNagerAndComplementaryFeed() {
        let text = """
        Light and airy baked crispy pillows with essential oats and timothy hay.
        A treat for all rodents!
        Ergänzungsiutiemitict Nager. Zusammensetzung: Hafermehl 35%, Weizenmehl,
        Timothy Heu 10%. Mindestens haltbar bis/Partienummer: Siehe Stempel.
        Aliment complémentaire pour rongeurs.
        """

        let result = ScanAnalysisService.analyze(mergedText: text, imageItems: nil, feedTypes: feedTypes)

        XCTAssertEqual(result.detectedFeedTypeId, "complementary_feed")
        XCTAssertTrue(result.detectedSpeciesHints.contains("Nager"))
        XCTAssertTrue(result.labelingAreas.hasComposition)
        XCTAssertTrue(result.labelingAreas.hasBestBefore)
        XCTAssertTrue(result.labelingAreas.hasLotNumber)
    }

    func testTodayEdekaMuckelSnippetDetectsRabbitGuineaPigCompleteFeedAndNetQuantity() {
        let text = """
        Alleinfuttermittel für Zwergkaninchen und Meerschweinchen
        Zusammensetzung: Gras getrocknet, 9,1 % Luzerne getrocknet,
        Analytische Bestandteile: Rohprotein 11,2 %, Rohfett 2,1 %, Rohfaser 20,0 %.
        Zusatzstoffe: Ernährungsphysiologische Zusatzstoffe/kg: Vitamin A 12000 IE.
        600g e
        """

        let result = ScanAnalysisService.analyze(mergedText: text, imageItems: nil, feedTypes: feedTypes)

        XCTAssertEqual(result.detectedFeedTypeId, "complete_feed")
        XCTAssertTrue(result.detectedSpeciesHints.contains("Kaninchen"))
        XCTAssertTrue(result.detectedSpeciesHints.contains("Meerschweinchen"))
        XCTAssertTrue(result.labelingAreas.hasComposition)
        XCTAssertTrue(result.labelingAreas.hasAnalyticalConstituents)
        XCTAssertTrue(result.labelingAreas.hasAdditives)
        XCTAssertTrue(result.labelingAreas.hasNetQuantity)
    }

    func testTodayDokasCatSnackSnippetKeepsChickenAsIngredientNotPoultrySpecies() {
        let text = """
        FREEZE-DRIED CHICKEN HEARTS
        DE Ergänzungsfuttermittel für Katzen - Zusammensetzung: 99,5 % Hühnerherz.
        Analytische Bestandteile: Rohprotein 73,8 %, Rohfett 14,0 %.
        """

        let result = ScanAnalysisService.analyze(mergedText: text, imageItems: nil, feedTypes: feedTypes)

        XCTAssertEqual(result.detectedFeedTypeId, "complementary_feed")
        XCTAssertTrue(result.detectedSpeciesHints.contains("Katze"))
        XCTAssertFalse(result.detectedSpeciesHints.contains("Geflügel"))
    }

    func testTodayMediPetDietSnippetDetectsDogAndCompleteFeed() {
        let text = """
        Medi Pet+ Schonkost, Huhn mit Steckrübe.
        Diät-Alleinfuttermittel für ausgewachsene Hunde zur Minderung von
        Ausgangserzeugnis- und Nährstoffintoleranzerscheinungen.
        Zusammensetzung: Fleisch und tierische Nebenerzeugnisse (60% Huhn).
        FÜTTERUNGSEMPFEHLUNG
        """

        let result = ScanAnalysisService.analyze(mergedText: text, imageItems: nil, feedTypes: feedTypes)

        XCTAssertEqual(result.detectedFeedTypeId, "complete_feed")
        XCTAssertTrue(result.detectedSpeciesHints.contains("Hund"))
        XCTAssertFalse(result.detectedSpeciesHints.contains("Geflügel"))
        XCTAssertTrue(result.labelingAreas.hasComposition)
    }

    func testTodayIamsSnippetDetectsCatFromMultilingualText() {
        let text = """
        WITH CHICKEN AND NEW ZEALAND LAMB IN GRAVY
        mit HUHN UND NEUSEELAND-LAMM IN SAUCE
        1+ Adult Ausgewachsene Katzen
        IAMS NATURALLY 100% complete nutrition
        """

        let result = ScanAnalysisService.analyze(mergedText: text, imageItems: nil, feedTypes: feedTypes)

        XCTAssertEqual(result.detectedFeedTypeId, "complete_feed")
        XCTAssertTrue(result.detectedSpeciesHints.contains("Katze"))
        XCTAssertFalse(result.detectedSpeciesHints.contains("Geflügel"))
        XCTAssertFalse(result.detectedSpeciesHints.contains("Schaf"))
    }

    // MARK: - Real label OCR snippets added 2026-05-26

    func testPavoWeightLiftSnippetDetectsHorseAndComplementaryFeedFromMultilingualText() {
        let text = """
        Pavo WeightLift ist eine Raufutterergänzung.
        Aanvullend diervoeder voor paarden / Ergänzungsfutter für Pferde /
        Supplementary feed for horses. Analytische Bestandteile.
        """

        let result = ScanAnalysisService.analyze(mergedText: text, imageItems: nil, feedTypes: feedTypes)

        XCTAssertEqual(result.detectedFeedTypeId, "complementary_feed")
        XCTAssertTrue(result.detectedSpeciesHints.contains("Pferd"))
        XCTAssertTrue(result.labelingAreas.hasAnalyticalConstituents)
    }

    func testBrottrunkSnippetDetectsSingleFeedAndMultipleTargetSpecies() {
        let text = """
        Kanne Brottrunk für Tiere.
        Einzelfuttermittel für Wiederkäuer, Schweine, Pferde, Geflügel und andere Tiere.
        Mindestens haltbar bis: 20.10.2027 L.25293. Inhalt 5 kg.
        """

        let singleFeedTypes = feedTypes + [
            LabelingFeedType(
                id: "single_feed",
                nameDe: "Einzelfuttermittel",
                descriptionDe: nil,
                keywordsDe: ["Einzelfuttermittel"]
            )
        ]
        let result = ScanAnalysisService.analyze(mergedText: text, imageItems: nil, feedTypes: singleFeedTypes)

        XCTAssertEqual(result.detectedFeedTypeId, "single_feed")
        XCTAssertTrue(result.detectedSpeciesHints.contains("Rind"))
        XCTAssertTrue(result.detectedSpeciesHints.contains("Schwein"))
        XCTAssertTrue(result.detectedSpeciesHints.contains("Pferd"))
        XCTAssertTrue(result.detectedSpeciesHints.contains("Geflügel"))
        XCTAssertTrue(result.labelingAreas.hasBestBefore)
        XCTAssertTrue(result.labelingAreas.hasLotNumber)
        XCTAssertTrue(result.labelingAreas.hasNetQuantity)
    }

    func testAgrobsSnippetDetectsAdditiveSectionWithMcgAndHorse() {
        let text = """
        AGROBS Seniormineral Ergänzungsfuttermittel für Pferde.
        Zusatzstoffe je kg: 100.000 I.E. Vitamin A, 15.000 mcg Biotin.
        Charge: 120300. MHD: 03/2027. Inhalt: 3 kg.
        """

        let result = ScanAnalysisService.analyze(mergedText: text, imageItems: nil, feedTypes: feedTypes)

        XCTAssertEqual(result.detectedFeedTypeId, "complementary_feed")
        XCTAssertTrue(result.detectedSpeciesHints.contains("Pferd"))
        XCTAssertTrue(result.additiveHints.hasStructuredDeclarations)
        XCTAssertTrue(result.labelingAreas.hasAdditives)
    }

    func testAlpengruenMashKeepsComplementaryFeedDespiteMineralRecommendation() {
        let text = """
        AlpenGrün Mash
        Ergänzungsfuttermittel für Pferde nach GMP+ FSA gesichert
        Zusammensetzung Wiesengräser und -kräuter, Leinkuchen, Apfeltrester.
        Analytische Bestandteile Rohprotein 13,0 %, Rohfett 4,1 %, Rohfaser 20,3 %.
        Zur Mineralstoffversorgung empfehlen wir ein zu Ihrem Pferd und seinem Bedarf
        passendes AGROBS Mineralfutter. Chargennummer: 01102000040327.
        Mindestens haltbar bis: 04.09.2026. 5kg
        """

        let result = ScanAnalysisService.analyze(mergedText: text, imageItems: nil, feedTypes: feedTypes)

        XCTAssertEqual(result.detectedFeedTypeId, "complementary_feed")
        XCTAssertTrue(result.detectedSpeciesHints.contains("Pferd"))
        XCTAssertTrue(result.labelingAreas.hasComposition)
        XCTAssertTrue(result.labelingAreas.hasAnalyticalConstituents)
        XCTAssertTrue(result.labelingAreas.hasLotNumber)
        XCTAssertTrue(result.labelingAreas.hasBestBefore)
        XCTAssertTrue(result.labelingAreas.hasNetQuantity)
    }

    // MARK: - Image coverage

    func testSingleImageSessionCoverage() {
        // nil imageItems → single-image default
        let result = analyze(text: "Zusammensetzung: Fleisch", items: nil)
        XCTAssertEqual(result.imageCoverage.imageCount, 1)
        XCTAssertFalse(result.imageCoverage.missingBodenOrDeckel)
    }

    func testTwoImagesWithoutBodenOrDeckelFlagsMissing() {
        let items: [OCRImageItem] = [
            makeItem(.vorderseite, text: "Zusammensetzung: Fleisch"),
            makeItem(.rueckseite, text: "Rohprotein 28 g"),
        ]
        let result = analyze(text: "Zusammensetzung: Fleisch Rohprotein 28 g", items: items)
        XCTAssertEqual(result.imageCoverage.imageCount, 2)
        XCTAssertTrue(result.imageCoverage.missingBodenOrDeckel)
    }

    func testTwoImagesWithBodenDoesNotFlagMissing() {
        let items: [OCRImageItem] = [
            makeItem(.vorderseite, text: "Zusammensetzung: Fleisch"),
            makeItem(.boden, text: "LOT 20240501"),
        ]
        let result = analyze(text: "Zusammensetzung: Fleisch LOT 20240501", items: items)
        XCTAssertFalse(result.imageCoverage.missingBodenOrDeckel)
    }

    // MARK: - Quality warnings

    func testShortOCRTextProducesWarning() {
        let text = "Fleisch" // well under 150 chars
        let result = analyze(text: text)
        let hasShortWarning = result.qualityWarnings.contains { $0.contains("kurz") }
        XCTAssertTrue(hasShortWarning, "Expected short-text warning but got: \(result.qualityWarnings)")
    }

    func testNoAreasWarningWhenTextSufficientButNoKeywords() {
        // >50 chars, no known labeling area keywords
        let text = String(repeating: "abc def ghi ", count: 5) // 60 chars, no keywords
        let result = analyze(text: text)
        let hasAreaWarning = result.qualityWarnings.contains { $0.contains("Keine bekannten") }
        XCTAssertTrue(hasAreaWarning, "Expected no-area warning but got: \(result.qualityWarnings)")
    }

    func testMissingBodenDeckelProducesWarning() {
        let items: [OCRImageItem] = [
            makeItem(.vorderseite, text: "Zusammensetzung: Rind"),
            makeItem(.rueckseite, text: "Rohprotein 25 g"),
        ]
        let text = "Zusammensetzung: Rind Rohprotein 25 g"
        let result = analyze(text: text, items: items)
        let hasBodenWarning = result.qualityWarnings.contains { $0.contains("Boden") }
        XCTAssertTrue(hasBodenWarning, "Expected Boden/Deckel warning but got: \(result.qualityWarnings)")
    }

    // MARK: - ScanEntry backward compatibility

    func testDecodesScanEntryWithoutAnalysisResult() throws {
        // Minimal legacy JSON without analysisResult field
        let json = """
        {
          "id": "11111111-1111-1111-1111-111111111111",
          "timestamp": 0,
          "ocrText": "Zusammensetzung: Rind",
          "isPinned": false
        }
        """
        let data = try XCTUnwrap(json.data(using: .utf8))
        let entry = try JSONDecoder().decode(ScanEntry.self, from: data)
        XCTAssertNil(entry.analysisResult, "Legacy entry must decode with nil analysisResult")
        XCTAssertEqual(entry.ocrText, "Zusammensetzung: Rind")
    }

    func testScanEntryRoundTripWithAnalysisResult() throws {
        let areas = DetectedLabelingAreas(
            hasComposition: true, hasAnalyticalConstituents: false,
            hasAdditives: true, hasBestBefore: false,
            hasLotNumber: false, hasNetQuantity: false, hasOperator: false
        )
        let hints = AdditiveHints(
            hasAdditiveSection: true, hasAmountPatterns: true,
            hasENumbers: false, hasStructuredDeclarations: true,
            detectedSubstanceNames: ["Taurin"]
        )
        let coverage = ImageCoverage(
            imageCount: 2, coveredTypes: [.vorderseite, .rueckseite],
            missingBodenOrDeckel: true, forcedNotCheckableRulePrefixes: ["lot", "mhd"]
        )
        let analysisResult = ScanAnalysisResult(
            detectedFeedTypeId: "complete_feed",
            feedTypeConfidence: 0.92,
            detectedSpeciesHints: ["Hund"],
            labelingAreas: areas,
            additiveHints: hints,
            imageCoverage: coverage,
            qualityWarnings: ["Kein Boden-/Deckel-Bild"],
            analyzedAt: Date(timeIntervalSince1970: 1_000_000)
        )
        let entry = ScanEntry(
            ocrText: "Zusammensetzung: Rind",
            thumbnailFileName: nil,
            analysisResult: analysisResult
        )

        let encoded = try JSONEncoder().encode(entry)
        let decoded = try JSONDecoder().decode(ScanEntry.self, from: encoded)

        XCTAssertEqual(decoded.analysisResult, analysisResult)
        XCTAssertEqual(decoded.analysisResult?.detectedFeedTypeId, "complete_feed")
        XCTAssertEqual(decoded.analysisResult?.additiveHints.detectedSubstanceNames, ["Taurin"])
        XCTAssertEqual(decoded.analysisResult?.imageCoverage.forcedNotCheckableRulePrefixes, ["lot", "mhd"])
    }
}
