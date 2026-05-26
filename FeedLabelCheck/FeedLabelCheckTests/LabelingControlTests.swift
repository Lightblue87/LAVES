import XCTest
@testable import FeedLabelCheck

// MARK: - A) Grundlage-Auswertung

final class LabelingRequirementSuggestionServiceTests: XCTestCase {

    // Helper to run analysis and find the first suggestion matching category + status
    private func firstSuggestion(
        in text: String,
        category: LabelingRequirementCategory,
        status: LabelingRequirementStatus
    ) -> LabelingRequirementSuggestion? {
        LabelingRequirementSuggestionService.analyze(ocrText: text)
            .first { $0.category == category && $0.status == status }
    }

    // MARK: Analytical constituents → mustDeclare

    func testRohproteinMustDeclare() {
        let text = "Rohprotein 12,5 %  Rohfett 8,0 %"
        let s = firstSuggestion(in: text, category: .analyticalConstituents, status: .mustDeclare)
        XCTAssertNotNil(s, "Rohprotein 12,5 % must produce a mustDeclare suggestion")
        XCTAssertEqual(s?.normalizedValue?.numericValue ?? -1.0, 12.5, accuracy: 0.001)
        XCTAssertEqual(s?.normalizedValue?.unit, "%")
    }

    func testRohfettMustDeclare() {
        let text = "Rohfett 8,0 % Rohasche 2,5 %"
        let suggestions = LabelingRequirementSuggestionService.analyze(ocrText: text)
        let categories = suggestions.filter { $0.status == .mustDeclare }.map { $0.category }
        XCTAssertTrue(
            categories.contains(.analyticalConstituents),
            "Rohfett/Rohasche must produce analyticalConstituents mustDeclare"
        )
    }

    func testCrudeProteinMustDeclare() {
        let text = "crude protein 18.0 %"
        let s = firstSuggestion(in: text, category: .analyticalConstituents, status: .mustDeclare)
        XCTAssertNotNil(s, "English 'crude protein 18.0 %' must produce a mustDeclare suggestion")
        XCTAssertEqual(s?.normalizedValue?.numericValue ?? 0, 18.0, accuracy: 0.001)
    }

    // MARK: Additives → mustDeclare

    func testTaurinMgKgMustDeclare() {
        let text = "Zusatzstoffe: Taurin 1000 mg/kg"
        let s = firstSuggestion(in: text, category: .additives, status: .mustDeclare)
        XCTAssertNotNil(s, "Taurin 1000 mg/kg must produce a mustDeclare additives suggestion")
        XCTAssertEqual(s?.normalizedValue?.numericValue ?? -1.0, 1000.0, accuracy: 0.001)
        XCTAssertEqual(s?.normalizedValue?.unit, "mg/kg")
    }

    func testTaurinWithThousandsSeparatorMustDeclare() {
        let text = "Taurin 1.000 mg/kg"
        let s = firstSuggestion(in: text, category: .additives, status: .mustDeclare)
        XCTAssertNotNil(s)
        XCTAssertEqual(s?.normalizedValue?.numericValue ?? -1.0, 1000.0, accuracy: 0.001)
    }

    func testVitaminD3IEKgMustDeclare() {
        let text = "Vitamin D3 200 IE/kg"
        let s = firstSuggestion(in: text, category: .additives, status: .mustDeclare)
        XCTAssertNotNil(s, "Vitamin D3 200 IE/kg must produce a mustDeclare additives suggestion")
        XCTAssertEqual(s?.normalizedValue?.numericValue ?? -1.0, 200.0, accuracy: 0.001)
        XCTAssertEqual(s?.normalizedValue?.unit, "IE/kg")
    }

    // MARK: Composition → mustDeclare

    func testCompositionWithPercentsMustDeclare() {
        let text = "Huhn 70 %, Brühe 28 %, Mineralstoffe 1 %, Pflanzenöl 1 %"
        let s = firstSuggestion(in: text, category: .composition, status: .mustDeclare)
        XCTAssertNotNil(s, "Composition with ≥2 ingredients must produce a mustDeclare suggestion")
    }

    func testSingleIngredientNoCompositionSuggestion() {
        // Only one ingredient → composition suggestion is suppressed
        let text = "Huhn 70 %"
        let suggestions = LabelingRequirementSuggestionService.analyze(ocrText: text)
        let comp = suggestions.filter {
            $0.category == .composition && $0.status == .mustDeclare
        }
        XCTAssertTrue(comp.isEmpty, "Single ingredient must not produce a composition suggestion")
    }

    // MARK: Charge / LOT → mustDeclare

    func testChargeWithCodeMustDeclare() {
        let text = "Charge A12345 Rohprotein 25 %"
        let s = firstSuggestion(in: text, category: .lotNumber, status: .mustDeclare)
        XCTAssertNotNil(s, "Charge A12345 must produce a mustDeclare lotNumber suggestion")
    }

    func testLotCodeMustDeclare() {
        let text = "LOT 20240901A"
        let s = firstSuggestion(in: text, category: .lotNumber, status: .mustDeclare)
        XCTAssertNotNil(s, "LOT 20240901A must produce a mustDeclare lotNumber suggestion")
    }

    // MARK: MHD / EXP → mustDeclare

    func testMHDWithDateMustDeclare() {
        let text = "MHD 31.12.2025"
        let s = firstSuggestion(in: text, category: .bestBefore, status: .mustDeclare)
        XCTAssertNotNil(s, "MHD 31.12.2025 must produce a mustDeclare bestBefore suggestion")
    }

    func testEXPWithDateMustDeclare() {
        let text = "EXP: 29.11.2026 NU250529H"
        let s = firstSuggestion(in: text, category: .bestBefore, status: .mustDeclare)
        XCTAssertNotNil(s, "EXP: 29.11.2026 must produce a mustDeclare bestBefore suggestion")
    }

    // MARK: Not-label-relevant

    func testInterneFreigabeNotLabelRelevant() {
        let text = "interne Freigabe QC-Protokoll Charge A100"
        let s = firstSuggestion(in: text, category: .internalProductionInfo, status: .notLabelRelevant)
        XCTAssertNotNil(s, "'interne Freigabe' must produce a notLabelRelevant suggestion")
    }

    func testProduktionslinieNotLabelRelevant() {
        let text = "Produktionslinie 4 Chargennummer B100"
        let s = firstSuggestion(in: text, category: .internalProductionInfo, status: .notLabelRelevant)
        XCTAssertNotNil(s, "'Produktionslinie 4' must produce a notLabelRelevant suggestion")
    }

    func testQCNumberNotLabelRelevant() {
        let text = "QC-17 interne Kontrollnummer"
        let s = firstSuggestion(in: text, category: .internalProductionInfo, status: .notLabelRelevant)
        XCTAssertNotNil(s, "'QC-17' must produce a notLabelRelevant suggestion")
    }

    // MARK: shouldReview (Rezeptur-ID)

    func testRezepturIdShouldReview() {
        let text = "Rezeptur-ID R0042 Rohprotein 18 %"
        let s = firstSuggestion(in: text, category: .lotNumber, status: .shouldReview)
        XCTAssertNotNil(s, "Rezeptur-ID must produce a shouldReview (not mustDeclare) lotNumber suggestion")
    }

    func testRezepturIdNotAutomaticallyLot() {
        let text = "Rezeptur-ID R0042"
        let suggestions = LabelingRequirementSuggestionService.analyze(ocrText: text)
        let mustDeclareLot = suggestions.filter {
            $0.category == .lotNumber && $0.status == .mustDeclare
        }
        XCTAssertTrue(
            mustDeclareLot.isEmpty,
            "Rezeptur-ID must NOT produce a mustDeclare LOT suggestion"
        )
    }

    // MARK: Analytical constituents not misclassified as additives

    func testRohproteinNotClassifiedAsAdditive() {
        let text = "Rohprotein 18 %"
        let suggestions = LabelingRequirementSuggestionService.analyze(ocrText: text)
        let additiveSuggestions = suggestions.filter { $0.category == .additives }
        XCTAssertTrue(additiveSuggestions.isEmpty,
                      "Rohprotein must not be classified as an additive")
    }
}

// MARK: - B) Regression: existing packaging check still green

final class LabelingControlRegressionTests: XCTestCase {

    private func makeDummyFeedType() -> LabelingFeedType {
        LabelingFeedType(
            id: "complementary_feed",
            nameDe: "Ergänzungsfuttermittel",
            descriptionDe: nil,
            keywordsDe: ["Ergänzungsfuttermittel"]
        )
    }

    private func makeDummyRule(
        id: String,
        requirementType: String,
        patterns: [LabelingRulePattern] = []
    ) -> LabelingRule {
        LabelingRule(
            id: id,
            regulationId: "reg_767_2009",
            feedTypeId: "all",
            titleDe: id,
            descriptionDe: "",
            legalBasis: "",
            requirementType: requirementType,
            severity: .critical,
            isMandatory: true,
            displayOrder: 0,
            patterns: patterns
        )
    }

    func testExistingCheckServiceUnchanged() {
        // Verify LabelingCheckService.check still works without modification
        let text = "Ergänzungsfuttermittel für Hunde. Zusammensetzung: Fleisch. Rohprotein 28 %."
        let result = LabelingCheckService.check(
            ocrText: text,
            feedType: makeDummyFeedType(),
            feedTypeConfidence: 0.9,
            rules: [],
            dbInfo: nil
        )
        XCTAssertEqual(result.ruleResults.count, 0)
        XCTAssertEqual(result.overallStatus, .nichtPruefbar)
    }

    func testAnimalSpeciesHintUpgradesMissingRule() {
        let rule = makeDummyRule(
            id: "art17_001",
            requirementType: "animal_species",
            patterns: [
                LabelingRulePattern(
                    id: "p1",
                    ruleId: "art17_001",
                    patternType: "keyword",
                    patternValue: "für Katzen",
                    patternLanguage: "de",
                    confidenceWeight: 1.0,
                    isNegativePattern: false
                )
            ]
        )
        let result = LabelingCheckService.check(
            ocrText: "Ergänzungsfuttermittel für ausgewachsene Katzen Zusammensetzung Fleisch Rohprotein 28 Prozent",
            feedType: makeDummyFeedType(),
            feedTypeConfidence: 0.9,
            rules: [rule],
            dbInfo: nil,
            detectedSpeciesHints: ["Katze"]
        )

        XCTAssertEqual(result.ruleResults.first?.status, .found)
        XCTAssertEqual(result.ruleResults.first?.matchedText, "Katze")
    }

    func testStructuredAdditiveDeclarationUpgradesMissingAdditiveRule() {
        let rule = makeDummyRule(
            id: "art15_006",
            requirementType: "additives",
            patterns: [
                LabelingRulePattern(
                    id: "p1",
                    ruleId: "art15_006",
                    patternType: "keyword",
                    patternValue: "Zusatzstoffe",
                    patternLanguage: "de",
                    confidenceWeight: 1.0,
                    isNegativePattern: false
                )
            ]
        )
        let declaration = AdditiveDeclaration(
            substanceName: "Taurin",
            amount: ParsedAdditiveAmount(value: 1000, unit: "mg/kg", rawText: "1000 mg/kg"),
            rawText: "Taurin 1000 mg/kg",
            confidence: .exactMatch,
            matchedAdditive: nil
        )
        let result = LabelingCheckService.check(
            ocrText: "Ergaenzungsfuttermittel fuer Katzen Taurin 1000 mg/kg Rohprotein 28 Prozent",
            feedType: makeDummyFeedType(),
            feedTypeConfidence: 0.9,
            rules: [rule],
            dbInfo: nil,
            additiveDeclarations: [declaration]
        )

        XCTAssertEqual(result.ruleResults.first?.status, .found)
        XCTAssertTrue(result.ruleResults.first?.note?.contains("Strukturierte Zusatzstoffdeklaration") == true)
    }

    func testScanEntryBackwardCompatibilityUnchanged() throws {
        // ScanEntry must still decode legacy JSON (no new required fields)
        let json = """
        {
          "id": "22222222-2222-2222-2222-222222222222",
          "timestamp": 0,
          "ocrText": "Ergänzungsfuttermittel für Hunde",
          "isPinned": false
        }
        """
        let data = try XCTUnwrap(json.data(using: .utf8))
        let entry = try JSONDecoder().decode(ScanEntry.self, from: data)
        XCTAssertEqual(entry.ocrText, "Ergänzungsfuttermittel für Hunde")
        XCTAssertNil(entry.analysisResult, "Legacy entry must decode with nil analysisResult")
    }
}

// MARK: - C) Abgleich (comparison)

final class LabelingControlComparisonServiceTests: XCTestCase {

    // MARK: - Value normalization

    func testValuesMatchExact() {
        XCTAssertTrue(LabelingControlComparisonService.valuesMatch(1000.0, 1000.0))
    }

    func testValuesMatchWithinOnePct() {
        // 1000 vs 1005 → 0.5% difference → match
        XCTAssertTrue(LabelingControlComparisonService.valuesMatch(1000.0, 1005.0))
    }

    func testValuesMismatchBeyondOnePct() {
        // 12.5 vs 10.0 → 20% difference → mismatch
        XCTAssertFalse(LabelingControlComparisonService.valuesMatch(12.5, 10.0))
    }

    func testValuesMatchDecimalVariants() {
        // 12.5 % (basis) vs 12.50 % (packaging) → same value
        XCTAssertTrue(LabelingControlComparisonService.valuesMatch(12.5, 12.50))
    }

    // MARK: - Taurin 1000 mg/kg vs Taurin 1.000 mg/kg → matched

    func testTaurinThousandsSeparatorMatched() {
        let suggestion = LabelingRequirementSuggestion(
            category: .additives,
            status: .mustDeclare,
            extractedText: "Taurin 1000 mg/kg",
            normalizedValue: LabelingNormalizedValue(
                numericValue: 1000.0, unit: "mg/kg", textValue: "Taurin 1000 mg/kg"
            )
        )
        let packagingText = "Zusatzstoffe: Taurin 1.000 mg/kg, Vitamin E 150 mg/kg"
        let entry = LabelingControlComparisonService.compare(
            suggestion: suggestion,
            checkResult: makeDummyCheckResult(),
            packagingText: packagingText
        )
        XCTAssertEqual(
            entry.packagingStatus, .matched,
            "Taurin 1000 mg/kg (basis) vs Taurin 1.000 mg/kg (packaging) must be matched"
        )
    }

    // MARK: - Rohprotein 12,5 % vs Rohprotein 12.50 % → matched

    func testRohproteinDecimalVariantsMatched() {
        let suggestion = LabelingRequirementSuggestion(
            category: .analyticalConstituents,
            status: .mustDeclare,
            extractedText: "Rohprotein 12,5 %",
            normalizedValue: LabelingNormalizedValue(
                numericValue: 12.5, unit: "%", textValue: "Rohprotein 12,5 %"
            )
        )
        let packagingText = "Rohprotein 12.50 % Rohfett 8,0 %"
        let entry = LabelingControlComparisonService.compare(
            suggestion: suggestion,
            checkResult: makeDummyCheckResult(),
            packagingText: packagingText
        )
        XCTAssertEqual(
            entry.packagingStatus, .matched,
            "Rohprotein 12,5% (basis) vs Rohprotein 12.50% (packaging) must be matched"
        )
    }

    // MARK: - Rohprotein 12,5 % vs Rohprotein 10,0 % → mismatch

    func testRohproteinValueMismatch() {
        let suggestion = LabelingRequirementSuggestion(
            category: .analyticalConstituents,
            status: .mustDeclare,
            extractedText: "Rohprotein 12,5 %",
            normalizedValue: LabelingNormalizedValue(
                numericValue: 12.5, unit: "%", textValue: "Rohprotein 12,5 %"
            )
        )
        let packagingText = "Rohprotein 10,0 % Rohfett 8,0 %"
        let entry = LabelingControlComparisonService.compare(
            suggestion: suggestion,
            checkResult: makeDummyCheckResult(),
            packagingText: packagingText
        )
        XCTAssertEqual(
            entry.packagingStatus, .mismatch,
            "Rohprotein 12,5 % (basis) vs Rohprotein 10,0 % (packaging) must be mismatch"
        )
    }

    // MARK: - Charge A12345 vs LOT A12345 → matched

    func testChargeLOTAliasMatched() {
        let suggestion = LabelingRequirementSuggestion(
            category: .lotNumber,
            status: .mustDeclare,
            extractedText: "Charge A12345",
            normalizedValue: LabelingNormalizedValue(
                numericValue: nil, unit: nil, textValue: "Charge A12345"
            )
        )
        let packagingText = "LOT A12345 MHD 12.2026"
        let entry = LabelingControlComparisonService.compare(
            suggestion: suggestion,
            checkResult: makeCheckResultWithLot(status: .found, matchedText: "LOT A12345"),
            packagingText: packagingText
        )
        XCTAssertEqual(
            entry.packagingStatus, .matched,
            "Charge A12345 (basis) with LOT A12345 found on packaging must be matched"
        )
    }

    // MARK: - Charge A12345 missing, no Boden image → notCheckable

    func testChargeA12345MissingNoBoden() {
        let suggestion = LabelingRequirementSuggestion(
            category: .lotNumber,
            status: .mustDeclare,
            extractedText: "Charge A12345",
            normalizedValue: LabelingNormalizedValue(
                numericValue: nil, unit: nil, textValue: "Charge A12345"
            )
        )
        let entry = LabelingControlComparisonService.compare(
            suggestion: suggestion,
            checkResult: makeCheckResultWithLot(status: .missing, matchedText: nil, hasBodenImage: false),
            packagingText: "Zusammensetzung: Fleisch Rohprotein 28 %"
        )
        XCTAssertEqual(
            entry.packagingStatus, .notCheckable,
            "Missing LOT without Boden image must be notCheckable"
        )
    }

    // MARK: - interne Freigabe QC-17 → notRequired

    func testInterneFreigabeNotRequired() {
        let suggestion = LabelingRequirementSuggestion(
            category: .internalProductionInfo,
            status: .notLabelRelevant,
            extractedText: "interne Freigabe QC-17"
        )
        let entry = LabelingControlComparisonService.compare(
            suggestion: suggestion,
            checkResult: makeDummyCheckResult(),
            packagingText: "Zusammensetzung: Fleisch"
        )
        XCTAssertEqual(
            entry.packagingStatus, .notRequired,
            "interne Freigabe must produce notRequired comparison status"
        )
    }

    // MARK: - Substance name extraction

    func testExtractSubstanceNameTaurin() {
        let name = LabelingControlComparisonService.extractSubstanceName(from: "Taurin 1000 mg/kg")
        XCTAssertEqual(name, "Taurin")
    }

    func testExtractSubstanceNameVitaminD3() {
        let name = LabelingControlComparisonService.extractSubstanceName(from: "Vitamin D3 200 IE/kg")
        XCTAssertEqual(name, "Vitamin D3")
    }

    func testExtractLotCode() {
        let code = LabelingControlComparisonService.extractLotCode(from: "Charge A12345")
        XCTAssertEqual(code, "A12345")
    }

    func testExtractLotCodeNil() {
        // Keyword without code
        let code = LabelingControlComparisonService.extractLotCode(from: "Charge: s. Boden")
        XCTAssertNil(code)
    }

    // MARK: - EN↔DE substance synonym

    func testTaurineTaurinSynonym() {
        XCTAssertTrue(
            LabelingControlComparisonService.textContainsSubstance("Taurine", in: "Taurin 1.000 mg/kg"),
            "Taurine must match Taurin (EN→DE)"
        )
        XCTAssertTrue(
            LabelingControlComparisonService.textContainsSubstance("Taurin", in: "Taurine 1000 mg/kg"),
            "Taurin must match Taurine (DE→EN)"
        )
    }

    // MARK: - Numeric value extraction

    func testExtractNumericValueTaurin() {
        let text = "Taurin 1.000 mg/kg"
        let v = LabelingControlComparisonService.extractNumericValue(
            forKeyword: "Taurin", unit: "mg/kg", in: text
        )
        XCTAssertNotNil(v)
        XCTAssertEqual(v!, 1000.0, accuracy: 0.001)
    }

    func testExtractNumericValueRohprotein() {
        let text = "Rohprotein 12,5 %"
        let v = LabelingControlComparisonService.extractNumericValue(
            forKeyword: "Rohprotein", unit: "%", in: text
        )
        XCTAssertNotNil(v)
        XCTAssertEqual(v!, 12.5, accuracy: 0.001)
    }

    // MARK: - MHD date comparison

    func testMHDDateMatched() {
        let suggestion = LabelingRequirementSuggestion(
            category: .bestBefore,
            status: .mustDeclare,
            extractedText: "MHD 31.12.2026",
            normalizedValue: LabelingNormalizedValue(
                numericValue: nil, unit: nil, textValue: "MHD 31.12.2026"
            )
        )
        let packagingText = "MHD 31.12.2026 LOT A12345 Rohprotein 28 %"
        let entry = LabelingControlComparisonService.compare(
            suggestion: suggestion,
            checkResult: makeCheckResultWithMHD(status: .found, matchedText: "MHD 31.12.2026"),
            packagingText: packagingText
        )
        XCTAssertEqual(
            entry.packagingStatus, .matched,
            "MHD 31.12.2026 in basis AND packaging must be matched"
        )
    }

    func testMHDDateMismatch() {
        let suggestion = LabelingRequirementSuggestion(
            category: .bestBefore,
            status: .mustDeclare,
            extractedText: "MHD 31.12.2026",
            normalizedValue: LabelingNormalizedValue(
                numericValue: nil, unit: nil, textValue: "MHD 31.12.2026"
            )
        )
        // Packaging shows a different year
        let packagingText = "MHD 31.12.2025 LOT A12345 Rohprotein 28 %"
        let entry = LabelingControlComparisonService.compare(
            suggestion: suggestion,
            checkResult: makeCheckResultWithMHD(status: .found, matchedText: "MHD 31.12.2025"),
            packagingText: packagingText
        )
        XCTAssertEqual(
            entry.packagingStatus, .mismatch,
            "MHD 31.12.2026 (basis) vs MHD 31.12.2025 (packaging) must be mismatch"
        )
    }

    func testMHDNoBasisDate_AcceptedAsMatched() {
        // Basis only has MHD keyword without concrete date → no date comparison → matched
        let suggestion = LabelingRequirementSuggestion(
            category: .bestBefore,
            status: .mustDeclare,
            extractedText: "mhd",
            normalizedValue: LabelingNormalizedValue(
                numericValue: nil, unit: nil, textValue: "mhd"
            )
        )
        let packagingText = "MHD 31.12.2026 Rohprotein 28 %"
        let entry = LabelingControlComparisonService.compare(
            suggestion: suggestion,
            checkResult: makeCheckResultWithMHD(status: .found, matchedText: "MHD 31.12.2026"),
            packagingText: packagingText
        )
        XCTAssertEqual(
            entry.packagingStatus, .matched,
            "MHD keyword without concrete date in basis must accept packaging result as matched"
        )
    }

    func testExtractDateFromMHD() {
        let date = LabelingControlComparisonService.extractDate(from: "MHD 31.12.2026")
        XCTAssertEqual(date, "31.12.2026")
    }

    func testExtractDateNilWhenNone() {
        let date = LabelingControlComparisonService.extractDate(from: "mhd")
        XCTAssertNil(date)
    }

    func testExtractDateNormalizesYearFirst() {
        // Year-first input must be normalized to DD.MM.YYYY
        let date = LabelingControlComparisonService.extractDate(from: "EXP 2026/12/31")
        XCTAssertEqual(date, "31.12.2026", "Year-first date must be normalized to DD.MM.YYYY")
    }

    func testExtractDateNormalizesLeadingZeros() {
        // Two-digit year and single-digit day/month
        let date = LabelingControlComparisonService.extractDate(from: "MHD 1.2.26")
        XCTAssertEqual(date, "01.02.2026", "Short date must be normalized with leading zeros and 4-digit year")
    }

    func testMHDSeparatorVariantMatched() {
        // Basis "31.12.2026", packaging "31-12-2026" → same date, different separator → matched
        let suggestion = LabelingRequirementSuggestion(
            category: .bestBefore,
            status: .mustDeclare,
            extractedText: "MHD 31.12.2026",
            normalizedValue: LabelingNormalizedValue(numericValue: nil, unit: nil, textValue: "MHD 31.12.2026")
        )
        let entry = LabelingControlComparisonService.compare(
            suggestion: suggestion,
            checkResult: makeCheckResultWithMHD(status: .found, matchedText: "MHD 31-12-2026"),
            packagingText: "MHD 31-12-2026 LOT A12345"
        )
        XCTAssertEqual(
            entry.packagingStatus, .matched,
            "31.12.2026 (basis) vs 31-12-2026 (packaging) must be matched despite different separator"
        )
    }

    func testMHDYearFirstFormatMatched() {
        // Basis "EXP 2026/12/31", packaging also year-first → matched
        let suggestion = LabelingRequirementSuggestion(
            category: .bestBefore,
            status: .mustDeclare,
            extractedText: "EXP 2026/12/31",
            normalizedValue: LabelingNormalizedValue(numericValue: nil, unit: nil, textValue: "EXP 2026/12/31")
        )
        let entry = LabelingControlComparisonService.compare(
            suggestion: suggestion,
            checkResult: makeCheckResultWithMHD(status: .found, matchedText: "EXP 2026/12/31"),
            packagingText: "EXP 2026/12/31 NU250529H"
        )
        XCTAssertEqual(
            entry.packagingStatus, .matched,
            "Year-first date on both basis and packaging must be matched"
        )
    }

    func testMHDLeadingZeroVariantMatched() {
        // Basis "1.2.2026" (no leading zero), packaging "01.02.2026" (leading zeros) → matched
        let suggestion = LabelingRequirementSuggestion(
            category: .bestBefore,
            status: .mustDeclare,
            extractedText: "MHD 1.2.2026",
            normalizedValue: LabelingNormalizedValue(numericValue: nil, unit: nil, textValue: "MHD 1.2.2026")
        )
        let entry = LabelingControlComparisonService.compare(
            suggestion: suggestion,
            checkResult: makeCheckResultWithMHD(status: .found, matchedText: "MHD 01.02.2026"),
            packagingText: "MHD 01.02.2026"
        )
        XCTAssertEqual(
            entry.packagingStatus, .matched,
            "1.2.2026 (basis) vs 01.02.2026 (packaging) must be matched"
        )
    }

    // MARK: - D) Regression: no new OCR workflow / no duplicate storage

    func testLabelingCheckResultStructureUnchanged() {
        // LabelingCheckResult must still be constructable with the original API
        let feedType = LabelingFeedType(
            id: "pet_feed", nameDe: "Heimtierfutter", descriptionDe: nil, keywordsDe: []
        )
        let result = LabelingCheckResult(
            feedType: feedType,
            feedTypeConfidence: 0.9,
            ruleResults: [],
            overallStatus: .nichtPruefbar,
            checkedAt: Date(),
            dbVersion: "1.0",
            databaseInfo: nil,
            ocrText: "test",
            imageItems: nil,
            additiveDeclarations: nil,
            dlgCheckResult: nil
        )
        XCTAssertEqual(result.feedType.id, "pet_feed")
        XCTAssertNil(result.additiveDeclarations)
    }

    func testScanEntryStructureUnchanged() throws {
        // ScanEntry must encode/decode without new required fields
        let entry = ScanEntry(
            ocrText: "Ergänzungsfuttermittel für Katzen",
            thumbnailFileName: nil
        )
        let encoded = try JSONEncoder().encode(entry)
        let decoded = try JSONDecoder().decode(ScanEntry.self, from: encoded)
        XCTAssertEqual(decoded.ocrText, "Ergänzungsfuttermittel für Katzen")
    }

    // MARK: - Helpers

    private func makeDummyCheckResult() -> LabelingCheckResult {
        let feedType = LabelingFeedType(
            id: "complementary_feed",
            nameDe: "Ergänzungsfuttermittel",
            descriptionDe: nil,
            keywordsDe: []
        )
        return LabelingCheckResult(
            feedType: feedType,
            feedTypeConfidence: 0.9,
            ruleResults: [],
            overallStatus: .nichtPruefbar,
            checkedAt: Date(),
            dbVersion: "test",
            databaseInfo: nil,
            ocrText: "",
            imageItems: nil,
            additiveDeclarations: nil,
            dlgCheckResult: nil
        )
    }

    private func makeCheckResultWithLot(
        status: RuleCheckStatus,
        matchedText: String?,
        hasBodenImage: Bool = true
    ) -> LabelingCheckResult {
        let lotPattern = LabelingRulePattern(
            id: "p1", ruleId: "art15_004",
            patternType: "keyword", patternValue: "LOT",
            patternLanguage: "de", confidenceWeight: 0.7,
            isNegativePattern: false
        )
        let lotRule = LabelingRule(
            id: "art15_004",
            regulationId: "reg_767_2009",
            feedTypeId: "all",
            titleDe: "Partie-/Losnummer",
            descriptionDe: "",
            legalBasis: "",
            requirementType: "lot_number",
            severity: .critical,
            isMandatory: true,
            displayOrder: 40,
            patterns: [lotPattern]
        )
        let lotResult = RuleCheckResult(
            rule: lotRule,
            status: status,
            matchedText: matchedText,
            matchedLanguage: "de",
            confidence: status == .found ? 1.0 : 0.7,
            note: nil
        )
        let feedType = LabelingFeedType(
            id: "complementary_feed",
            nameDe: "Ergänzungsfuttermittel",
            descriptionDe: nil,
            keywordsDe: []
        )
        // hasBodenImage=false → only Vorderseite; hasBodenImage=true → include Boden
        let items: [OCRImageItem]? = hasBodenImage
            ? [
                OCRImageItem(id: UUID(), imageType: .vorderseite, thumbnailFileName: nil, ocrText: "test"),
                OCRImageItem(id: UUID(), imageType: .boden, thumbnailFileName: nil, ocrText: "LOT A12345"),
            ]
            : [
                OCRImageItem(id: UUID(), imageType: .vorderseite, thumbnailFileName: nil, ocrText: "test"),
            ]
        return LabelingCheckResult(
            feedType: feedType,
            feedTypeConfidence: 0.9,
            ruleResults: [lotResult],
            overallStatus: .nichtPruefbar,
            checkedAt: Date(),
            dbVersion: "test",
            databaseInfo: nil,
            ocrText: "",
            imageItems: items,
            additiveDeclarations: nil,
            dlgCheckResult: nil
        )
    }

    private func makeCheckResultWithMHD(
        status: RuleCheckStatus,
        matchedText: String?
    ) -> LabelingCheckResult {
        let mhdRule = LabelingRule(
            id: "art17_002_complementary",
            regulationId: "reg_767_2009",
            feedTypeId: "complementary_feed",
            titleDe: "Mindesthaltbarkeitsdatum",
            descriptionDe: "",
            legalBasis: "",
            requirementType: "best_before",
            severity: .critical,
            isMandatory: true,
            displayOrder: 30,
            patterns: []
        )
        let mhdResult = RuleCheckResult(
            rule: mhdRule,
            status: status,
            matchedText: matchedText,
            matchedLanguage: "de",
            confidence: 1.0,
            note: nil
        )
        let feedType = LabelingFeedType(
            id: "complementary_feed",
            nameDe: "Ergänzungsfuttermittel",
            descriptionDe: nil,
            keywordsDe: []
        )
        return LabelingCheckResult(
            feedType: feedType,
            feedTypeConfidence: 0.9,
            ruleResults: [mhdResult],
            overallStatus: .nichtPruefbar,
            checkedAt: Date(),
            dbVersion: "test",
            databaseInfo: nil,
            ocrText: "",
            imageItems: [
                OCRImageItem(id: UUID(), imageType: .vorderseite, thumbnailFileName: nil, ocrText: "test"),
            ],
            additiveDeclarations: nil,
            dlgCheckResult: nil
        )
    }
}

// MARK: - G) AdditiveDeclarationParser unit tests

final class AdditiveDeclarationParserTests: XCTestCase {

    // Regression for Codex P2 review comment: bare `g` unit must be recognised
    // when the section header already contains "/kg"
    // (e.g. "Zusatzstoffe/kg: L-Carnitin 0,5 g")
    func testBareGramUnitParsedInPerKgSection() {
        let text = "Zusatzstoffe/kg: L-Carnitin 0,5 g"
        XCTAssertTrue(AdditiveDeclarationParser.hasStructuredDeclaration(in: text),
                      "L-Carnitin with bare 'g' unit in /kg section should be recognised")
        let declarations = AdditiveDeclarationParser.parse(text: text, additives: [])
        XCTAssertFalse(declarations.isEmpty, "parse() should return at least one declaration")
        if let first = declarations.first {
            XCTAssertTrue(first.substanceName.lowercased().contains("carnitin"),
                          "Substance name should contain 'carnitin', got '\(first.substanceName)'")
            XCTAssertEqual(first.amount?.unit, "g")
            if let value = first.amount?.value {
                XCTAssertEqual(value, 0.5, accuracy: 0.001)
            } else {
                XCTFail("amount.value should not be nil")
            }
        }
    }

    // Existing bare mg unit — must not regress
    func testBareMgUnitParsedInPerKgSection() {
        let text = "Zusatzstoffe/kg: Taurin 570 mg"
        XCTAssertTrue(AdditiveDeclarationParser.hasStructuredDeclaration(in: text))
        let declarations = AdditiveDeclarationParser.parse(text: text, additives: [])
        XCTAssertFalse(declarations.isEmpty)
        XCTAssertEqual(declarations.first?.amount?.unit, "mg")
        if let value = declarations.first?.amount?.value {
            XCTAssertEqual(value, 570.0, accuracy: 0.001)
        } else {
            XCTFail("amount.value should not be nil")
        }
    }

    // g/kg (explicit) must still parse — g/kg comes before \bg\b in the alternation
    func testGramPerKgUnitNotAffected() {
        let text = "Zusatzstoffe: Vitamin E 300 mg/kg"
        let declarations = AdditiveDeclarationParser.parse(text: text, additives: [])
        XCTAssertFalse(declarations.isEmpty)
        XCTAssertEqual(declarations.first?.amount?.unit, "mg/kg")
    }

    // E-number suppression: when a named entry matches an E-number in the DB,
    // the bare E-number entry must be dropped to avoid duplicates.
    func testENumberSuppressedWhenNameFoundInDB() {
        // Build a minimal mock DB: Taurin = E999 (fictitious E-number for testing)
        let mockAdditive = Additive(
            eNumber: "E999",
            name: "Taurin",
            species: "Alle Tierarten",
            maxAgeDays: nil,
            minMgKg: nil,
            maxMgKg: nil,
            unit: nil,
            regulation: nil,
            sourceFile: nil,
            sourcePage: nil,
            animalCategory: nil
        )
        // Label declares both the name and the E-number
        let text = "Zusatzstoffe: Taurin 570 mg/kg, E 999 570 mg/kg"
        let declarations = AdditiveDeclarationParser.parse(text: text, additives: [mockAdditive])

        // Only "Taurin" should appear; "E999" must be suppressed
        XCTAssertEqual(declarations.count, 1,
                       "E-number entry must be suppressed when the same substance was found by name")
        XCTAssertEqual(declarations.first?.substanceName, "Taurin")
    }

    // E-number must be kept when no named entry exists for it
    func testENumberKeptWhenNoNameFound() {
        // No DB → no suppression possible
        let text = "Zusatzstoffe: E 306 200 mg/kg"
        let declarations = AdditiveDeclarationParser.parse(text: text, additives: [])
        XCTAssertFalse(declarations.isEmpty, "E-number entry must be kept when no name is found")
        XCTAssertTrue(AdditiveDeclarationParser.looksLikeENumber("E306"))
        XCTAssertTrue(AdditiveDeclarationParser.looksLikeENumber("E 300"))
        XCTAssertFalse(AdditiveDeclarationParser.looksLikeENumber("Taurin"))
    }

    // New EU 1831/2003 kennnummer format detection
    func testLooksLikeKennnummer() {
        XCTAssertTrue(AdditiveDeclarationParser.looksLikeKennnummer("3a300"),   "3a300 → kennnummer")
        XCTAssertTrue(AdditiveDeclarationParser.looksLikeKennnummer("1m558"),   "1m558 → kennnummer")
        XCTAssertTrue(AdditiveDeclarationParser.looksLikeKennnummer("2b620i"),  "2b620i → trailing letter")
        XCTAssertTrue(AdditiveDeclarationParser.looksLikeKennnummer("3c322IV"), "3c322IV → Roman numeral suffix")
        XCTAssertTrue(AdditiveDeclarationParser.looksLikeKennnummer("3c305ii"), "3c305ii → two trailing letters")
        XCTAssertFalse(AdditiveDeclarationParser.looksLikeKennnummer("E300"),   "E300 → old E-number")
        XCTAssertFalse(AdditiveDeclarationParser.looksLikeKennnummer("E 306"),  "E 306 → old E-number")
        XCTAssertFalse(AdditiveDeclarationParser.looksLikeKennnummer("Taurin"), "Taurin → name")
        XCTAssertFalse(AdditiveDeclarationParser.looksLikeKennnummer("S01"),    "S01 → starts with letter")
        XCTAssertFalse(AdditiveDeclarationParser.looksLikeKennnummer("12000"),  "12000 → plain number")
    }

    // New kennnummer is extracted from label text
    func testKennnummerExtractedFromLabelText() {
        let text = "Zusatzstoffe: 3a300 200 mg/kg, 1m558 5000 mg/kg"
        let declarations = AdditiveDeclarationParser.parse(text: text, additives: [])
        XCTAssertEqual(declarations.count, 2, "Both kennnummern must be extracted")
        let names = declarations.map(\.substanceName)
        XCTAssertTrue(names.contains("3a300") || names.contains("3A300"),
                      "3a300 must appear in declarations")
        XCTAssertTrue(names.contains("1m558") || names.contains("1M558"),
                      "1m558 must appear in declarations")
    }

    // Kennnummer is suppressed when the named substance was found and DB provides the link
    func testKennnummerSuppressedWhenNameFoundInDB() {
        let mockAdditive = Additive(
            eNumber: "3a300",
            name: "Ascorbinsäure",
            species: "Alle Tierarten",
            maxAgeDays: nil, minMgKg: nil, maxMgKg: nil, unit: nil,
            regulation: nil, sourceFile: nil, sourcePage: nil, animalCategory: nil
        )
        let text = "Zusatzstoffe: Ascorbinsäure 200 mg/kg, 3a300 200 mg/kg"
        let declarations = AdditiveDeclarationParser.parse(text: text, additives: [mockAdditive])
        XCTAssertEqual(declarations.count, 1,
                       "Kennnummer must be suppressed when name found via DB")
        XCTAssertEqual(declarations.first?.substanceName, "Ascorbinsäure")
    }

    // DB entry with old E-style kennnummer (e.g. "E 310*") — label shows "E 310" → suppress
    func testOldEStyleKennnummerSuppressedWhenNameFound() {
        let mockAdditive = Additive(
            eNumber: "E 310*",
            name: "Propylgallat",
            species: "Alle Tierarten",
            maxAgeDays: nil, minMgKg: nil, maxMgKg: nil, unit: nil,
            regulation: nil, sourceFile: nil, sourcePage: nil, animalCategory: nil
        )
        let text = "Zusatzstoffe: Propylgallat 100 mg/kg, E 310 100 mg/kg"
        let declarations = AdditiveDeclarationParser.parse(text: text, additives: [mockAdditive])
        // "Propylgallat" → DB kennnummer "E 310*" → normalised "E310"
        // "E 310" on label → normalised "E310" → suppressed
        XCTAssertEqual(declarations.count, 1,
                       "Old E-style kennnummer must be suppressed when name found via DB")
        XCTAssertEqual(declarations.first?.substanceName, "Propylgallat")
    }

    func testAmountFirstInternationalUnitVariantsParsed() {
        let text = """
        Zusatzstoffe je kg:
        15.000I.E. Vitamin A; 1.500 l.E. Vitamin D3; 540æg Biotin;
        15.000 mcg Biotin; 20mg Kupfer als Kupfer-(II)-sulfat.
        """

        let declarations = AdditiveDeclarationParser.parse(text: text, additives: [])
        let names = Set(declarations.map(\.substanceName))

        XCTAssertTrue(names.contains("Vitamin A"))
        XCTAssertTrue(names.contains("Vitamin D3"))
        XCTAssertTrue(names.contains("Biotin"))
        XCTAssertTrue(names.contains("Kupfer"))
        XCTAssertTrue(declarations.contains { $0.amount?.unit.localizedCaseInsensitiveContains("I.E") == true })
        XCTAssertTrue(declarations.contains { $0.amount?.unit == "æg" })
        XCTAssertTrue(declarations.contains { $0.amount?.unit == "mcg" })
    }

    func testAdditiveNamesStartingWithAnalyticalMineralWordsAreNotExcluded() {
        let text = "Zusatzstoffe je kg: Calcium-D-Pantothenat 1.000 mg, Natriumselenit 10 mg"

        let declarations = AdditiveDeclarationParser.parse(text: text, additives: [])
        let names = Set(declarations.map(\.substanceName))

        XCTAssertTrue(names.contains("Calcium-D-Pantothenat"))
        XCTAssertTrue(names.contains("Natriumselenit"))
    }

    // Cross-format dedup: DB has BOTH new kennnummer AND old E-style for the same substance.
    // Label shows the name + old E-number, but DB entry for the name uses the new kennnummer.
    // relatedKennnummern() must bridge the gap via numeric core matching.
    func testCrossFormatDedup_NewKennnummerInDB_OldENumberOnLabel() {
        // DB: two entries for the same substance (Bentonit variants)
        let bentonitNew = Additive(
            eNumber: "1m558",         // new kennnummer
            name: "Bentonit",
            species: "Rinder", maxAgeDays: nil, minMgKg: nil, maxMgKg: 20000, unit: nil,
            regulation: nil, sourceFile: nil, sourcePage: nil, animalCategory: nil
        )
        let bentonitOld = Additive(
            eNumber: "E 558*",        // old E-style kennnummer, same numeric core "558"
            name: "Bentonit-Montmorillonit",
            species: "Schweine", maxAgeDays: nil, minMgKg: nil, maxMgKg: 20000, unit: nil,
            regulation: nil, sourceFile: nil, sourcePage: nil, animalCategory: nil
        )
        let db = [bentonitNew, bentonitOld]

        // Label: name + old E-number (most common cross-format case)
        let text = "Zusatzstoffe: Bentonit 5000 mg/kg, E 558 5000 mg/kg"
        let declarations = AdditiveDeclarationParser.parse(text: text, additives: db)

        // "Bentonit" → DB match "1m558" (core "558")
        // relatedKennnummern("1m558", in: db) → also finds "E 558*" (core "558") → adds "E558"
        // "E 558" on label → normalised "E558" → in coveredIdentifiers → suppressed
        XCTAssertEqual(declarations.count, 1,
                       "Old E-number must be suppressed via numeric-core cross-reference")
        XCTAssertEqual(declarations.first?.substanceName, "Bentonit")
    }

    // Inverse: label has name + new kennnummer; DB entry uses old E-style kennnummer
    func testCrossFormatDedup_OldENumberInDB_NewKennnummerOnLabel() {
        let tartrazinOld = Additive(
            eNumber: "E 102*",        // old-style kennnummer in DB
            name: "Tartrazin",
            species: "Alle Tierarten", maxAgeDays: nil, minMgKg: nil, maxMgKg: nil, unit: nil,
            regulation: nil, sourceFile: nil, sourcePage: nil, animalCategory: nil
        )
        let tartrazinNew = Additive(
            eNumber: "2a102",         // new-style kennnummer in DB, same core "102"
            name: "Tartrazin",
            species: "Alle Tierarten", maxAgeDays: nil, minMgKg: nil, maxMgKg: nil, unit: nil,
            regulation: nil, sourceFile: nil, sourcePage: nil, animalCategory: nil
        )
        let db = [tartrazinOld, tartrazinNew]

        // Label: name + new kennnummer (label updated to new system, DB still has old entry too)
        let text = "Zusatzstoffe: Tartrazin 50 mg/kg, 2a102 50 mg/kg"
        let declarations = AdditiveDeclarationParser.parse(text: text, additives: db)

        // "Tartrazin" → DB match "E 102*" or "2a102" (both have core "102")
        // coveredIdentifiers gets "E102" + "2A102" (via relatedKennnummern)
        // "2a102" on label → looksLikeKennnummer → normalised "2A102" → suppressed
        XCTAssertEqual(declarations.count, 1,
                       "New kennnummer must be suppressed when name found and DB has cross-format entry")
        XCTAssertEqual(declarations.first?.substanceName, "Tartrazin")
    }
}
