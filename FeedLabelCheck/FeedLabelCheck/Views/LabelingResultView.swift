import SwiftUI

struct LabelingResultView: View {
    let result: LabelingCheckResult
    /// Passed through to allow "Zusatzstoff prüfen" navigation from declaration rows.
    var additiveStore: AdditiveStore? = nil
    var onRecheckWithDifferentFeedType: (() -> Void)?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                overallSection
                recheckSection
                imageCoverageSection
                additiveDeclarationsSection
                dlgSection
                metaSection
                rulesSection
                disclaimerSection
            }
            .navigationTitle("Ergebnis")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Fertig") { dismiss() }
                }
            }
        }
    }

    // MARK: - Sections

    private var overallSection: some View {
        Section {
            HStack(spacing: 12) {
                Image(systemName: result.overallStatus.icon)
                    .font(.largeTitle)
                    .foregroundStyle(overallColor)
                VStack(alignment: .leading, spacing: 4) {
                    Text(result.overallStatus.rawValue)
                        .font(.headline)
                        .foregroundStyle(overallColor)
                    Text("Futtermittelart: \(result.feedType.displayName)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(.vertical, 6)
        }
    }

    @ViewBuilder
    private var imageCoverageSection: some View {
        if let items = result.imageItems, !items.isEmpty {
            Section("Gescannte Bildbereiche") {
                LabeledContent("Bilder", value: "\(items.count) von \(MultiImageOCRSession.maxImages)")
                let coveredNames = items.map(\.imageType.displayName).joined(separator: ", ")
                LabeledContent("Erfasste Bereiche", value: coveredNames)

                let covered = Set(items.map(\.imageType))
                let missing = OCRImageType.allCases.filter { !covered.contains($0) }
                if !missing.isEmpty {
                    LabeledContent("Nicht erfasst", value: missing.map(\.displayName).joined(separator: ", "))
                        .foregroundStyle(.secondary)
                }

                // Coverage warnings for location-specific rules
                let hasBodenOrDeckel = covered.contains(.boden) || covered.contains(.deckel)
                if !hasBodenOrDeckel {
                    Label(
                        "Kein Boden- oder Deckel-Bild – Losnummer/MHD möglicherweise nicht sichtbar.",
                        systemImage: "exclamationmark.triangle"
                    )
                    .font(.caption)
                    .foregroundStyle(.orange)
                }
            }
        }
    }

    private var recheckSection: some View {
        Section {
            if let recheck = onRecheckWithDifferentFeedType {
                Button {
                    dismiss()
                    recheck()
                } label: {
                    Label("Andere Futtermittelart prüfen", systemImage: "arrow.trianglehead.2.clockwise")
                }
            }
        }
    }

    @ViewBuilder
    private var additiveDeclarationsSection: some View {
        if let declarations = result.additiveDeclarations, !declarations.isEmpty {
            Section {
                ForEach(declarations) { decl in
                    if let store = additiveStore {
                        NavigationLink {
                            AdditiveDeclarationDetailView(
                                declaration: decl,
                                additiveStore: store
                            )
                        } label: {
                            AdditiveDeclarationRow(declaration: decl)
                        }
                    } else {
                        AdditiveDeclarationRow(declaration: decl)
                    }
                }

                if declarations.contains(where: { $0.confidence.requiresConfirmation }) {
                    Label(
                        "Ein oder mehrere Treffer erfordern manuelle Bestätigung.",
                        systemImage: "exclamationmark.triangle"
                    )
                    .font(.caption)
                    .foregroundStyle(.orange)
                }
            } header: {
                Text("Erkannte Zusatzstoffangaben")
            } footer: {
                let hasNormalized = declarations.contains { $0.amount?.isBareUnit == true }
                Text("Automatische Erkennung – kein Ersatz für eine amtliche Kontrolle."
                     + (hasNormalized ? " Mengenangaben ohne /kg-Suffix entsprechen der Deklaration je kg gemäß VO 767/2009." : ""))
                    .font(.caption2)
            }
        }
    }

    // MARK: - DLG Section

    @ViewBuilder
    private var dlgSection: some View {
        if let dlg = result.dlgCheckResult {
            Section {
                // Materialname-Zeile
                HStack(spacing: 10) {
                    Image(systemName: "list.bullet.clipboard")
                        .foregroundStyle(.blue)
                        .frame(width: 20)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(dlg.material.nameDe)
                            .font(.subheadline)
                            .fontWeight(.medium)
                        Text("\(dlg.material.number) · Gruppe \(dlg.material.groupNum): \(dlg.material.groupNameDe)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 2)

                if dlg.isNotDeclared {
                    Label("Keine Kennzeichnungsanforderungen in der DLG Positivliste hinterlegt.",
                          systemImage: "info.circle")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(dlg.findings) { finding in
                        DlgFindingRow(finding: finding)
                    }

                    if dlg.hasMissingMandatory {
                        Label(
                            "Eine oder mehrere Pflichtangaben wurden im OCR-Text nicht gefunden.",
                            systemImage: "exclamationmark.triangle.fill"
                        )
                        .font(.caption)
                        .foregroundStyle(.red)
                    }
                }
            } header: {
                Text("DLG Positivliste – Kennzeichnungsabgleich")
            } footer: {
                Text("Automatischer Abgleich auf Basis erkannter OCR-Daten. \(dlg.material.number) \(dlg.material.nameDe) · DLG Positivliste 15. Auflage 2023")
                    .font(.caption2)
            }
        }
    }

    private var metaSection: some View {
        Section("Prüfinformation") {
            LabeledContent("Hinweis", value: "Mobiler Schnellcheck")
            LabeledContent("Regelwerk", value: result.databaseInfo?.regulation ?? "VO (EG) Nr. 767/2009")
            LabeledContent("Quelle", value: result.databaseInfo?.celex ?? "02009R0767-20181226")
            LabeledContent("Regelversion", value: result.dbVersion)
            LabeledContent("Datenstand", value: formattedDataDate(result.databaseInfo?.createdAt ?? "–"))
            LabeledContent("Futtermittelart", value: result.feedType.displayName)
            LabeledContent("Erkennung", value: "\(Int(result.feedTypeConfidence * 100)) %")
            if !matchedLanguageSummary.isEmpty {
                LabeledContent("Hinweise gefunden in", value: matchedLanguageSummary)
            }
            LabeledContent("Geprüft", value: result.checkedAt.formatted(date: .abbreviated, time: .shortened))
            LabeledContent("Relevante Regeln geprüft", value: "\(result.ruleResults.count)")
            if let total = result.databaseInfo?.totalRuleCount {
                LabeledContent("Gesamtregeln in Datenbank", value: "\(total)")
            }
            Text("Es werden nur die für \"\(result.feedType.displayName)\" geltenden und allgemeinen Regeln geprüft – nicht alle \(result.databaseInfo.map { "\($0.totalRuleCount)" } ?? "–") Datenbankregeln.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var rulesSection: some View {
        Section("Regelprüfung") {
            ForEach(result.ruleResults) { ruleResult in
                NavigationLink {
                    LabelingRuleDetailView(ruleResult: ruleResult)
                } label: {
                    RuleResultRow(ruleResult: ruleResult)
                }
            }
        }
    }

    private var disclaimerSection: some View {
        Section {
            Text("Mobiler Schnellcheck – keine finale Rechtsbewertung. Bildqualität, verdeckte Angaben und OCR-Fehler können das Ergebnis beeinflussen. Ergebnis muss durch eine finale Bewertung bestätigt werden.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var overallColor: Color {
        switch result.overallStatus {
        case .keineAuffaelligkeit: return .green
        case .auffaellig: return .red
        case .unklar: return .orange
        case .nichtPruefbar: return .gray
        }
    }

    private var matchedLanguageSummary: String {
        let languages = Set(result.ruleResults.compactMap { $0.matchedLanguage })
        let ordered = ["de", "en", "other"].filter { languages.contains($0) }
        let remaining = languages.subtracting(ordered).sorted()
        return (ordered + remaining)
            .map { LabelingCheckService.languageName($0) }
            .joined(separator: ", ")
    }

    private func formattedDataDate(_ value: String) -> String {
        let isoWithFractional = ISO8601DateFormatter()
        isoWithFractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime]

        guard let date = isoWithFractional.date(from: value) ?? iso.date(from: value) else {
            return value
        }

        return date.formatted(date: .abbreviated, time: .shortened)
    }
}

// MARK: - Additive Declaration Row

private struct AdditiveDeclarationRow: View {
    let declaration: AdditiveDeclaration

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: declaration.confidence.icon)
                .foregroundStyle(confidenceColor)
                .frame(width: 20)
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(declaration.substanceName)
                        .font(.subheadline)
                    if let amount = declaration.amount {
                        Text("–")
                            .foregroundStyle(.secondary)
                        Text(amount.displayString)
                            .font(.subheadline)
                            .foregroundStyle(.primary)
                    }
                }
                Text(declaration.confidence.label)
                    .font(.caption)
                    .foregroundStyle(confidenceColor)
                if let matched = declaration.matchedAdditive, !matched.eNumber.isEmpty {
                    Text(matched.eNumber)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 2)
    }

    private var confidenceColor: Color {
        switch declaration.confidence {
        case .exactMatch:    return .green
        case .exactNoAmount: return .teal
        case .fuzzyMatch:    return .orange
        case .noDBMatch:     return .red
        }
    }
}

// MARK: - Additive Declaration Detail View

struct AdditiveDeclarationDetailView: View {
    let declaration: AdditiveDeclaration
    @ObservedObject var additiveStore: AdditiveStore

    var body: some View {
        List {
            // Parsed declaration
            Section("Erkannte Angabe") {
                LabeledContent("Stoff", value: declaration.substanceName)
                if let amount = declaration.amount {
                    LabeledContent("Menge", value: amount.displayString)
                    LabeledContent("Rohtext", value: amount.rawText)
                } else {
                    LabeledContent("Menge", value: "Nicht erkannt")
                }
                LabeledContent("OCR-Fragment") {
                    Text(declaration.rawText)
                        .font(.caption)
                        .textSelection(.enabled)
                }
            }

            // DB match
            if let additive = declaration.matchedAdditive {
                Section("Datenbankeintrag") {
                    if !additive.eNumber.isEmpty {
                        LabeledContent("Kennnummer", value: additive.eNumber)
                    }
                    LabeledContent("Name", value: additive.name)
                    if !additive.normalizedSpecies.isEmpty {
                        LabeledContent("Tierarten", value: additive.normalizedSpecies)
                    }
                    if let min = additive.minMgKg {
                        LabeledContent("Min.", value: "\(formatValue(min)) \(additive.unit ?? "mg/kg")")
                    }
                    if let max = additive.maxMgKg {
                        LabeledContent("Max.", value: "\(formatValue(max)) \(additive.unit ?? "mg/kg")")
                    }
                    // Within-limits check
                    if let amount = declaration.amount, let max = additive.maxMgKg {
                        limitRow(parsedValue: amount.value, max: max, unit: additive.unit ?? amount.unit)
                    }
                }
            } else {
                Section("Datenbank") {
                    switch declaration.confidence {
                    case .fuzzyMatch:
                        Label("Ähnlicher Treffer – bitte in der Datenbank nachschlagen.",
                              systemImage: "questionmark.circle")
                            .foregroundStyle(.orange)
                    default:
                        Label("Kein Eintrag gefunden – manuelle Prüfung erforderlich.",
                              systemImage: "exclamationmark.circle")
                            .foregroundStyle(.red)
                    }
                }
            }

            Section {
                Text("Automatische Erkennung – kein Ersatz für eine amtliche Kontrolle. Ergebnis muss durch eine finale Bewertung bestätigt werden.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .navigationTitle(declaration.substanceName)
        .navigationBarTitleDisplayMode(.inline)
    }

    @ViewBuilder
    private func limitRow(parsedValue: Double, max: Double, unit: String) -> some View {
        if parsedValue <= max {
            Label(
                "Menge \(formatValue(parsedValue)) \(unit) liegt unter dem Höchstwert (\(formatValue(max)) \(unit)).",
                systemImage: "checkmark.circle"
            )
            .foregroundStyle(.green)
            .font(.caption)
        } else {
            Label(
                "Menge \(formatValue(parsedValue)) \(unit) überschreitet Höchstwert (\(formatValue(max)) \(unit)) – bitte prüfen!",
                systemImage: "exclamationmark.triangle.fill"
            )
            .foregroundStyle(.red)
            .font(.caption)
        }
    }

    private func formatValue(_ v: Double) -> String {
        v == v.rounded(.towardZero) && v < 1_000_000 ? "\(Int(v))" : String(format: "%.2f", v)
    }
}

// MARK: - DLG Finding Row

private struct DlgFindingRow: View {
    let finding: DlgNutrientFinding

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: finding.statusIcon)
                .foregroundStyle(statusColor)
                .frame(width: 20)
            VStack(alignment: .leading, spacing: 3) {
                Text(finding.requirement.nutrient)
                    .font(.subheadline)
                if !finding.requirement.isMandatory, let cond = finding.requirement.condition {
                    Text(cond)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if let snippet = finding.matchedText {
                    Text(snippet)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                Text(finding.statusLabel)
                    .font(.caption)
                    .foregroundStyle(statusColor)
            }
        }
        .padding(.vertical, 2)
    }

    private var statusColor: Color {
        switch finding.status {
        case .found:             return .green
        case .missing:           return .red
        case .conditionalAbsent: return .orange
        }
    }
}

// MARK: - Rule Result Row

private struct RuleResultRow: View {
    let ruleResult: RuleCheckResult

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: ruleResult.status.icon)
                .foregroundStyle(statusColor)
                .frame(width: 20)
            VStack(alignment: .leading, spacing: 3) {
                Text(ruleResult.rule.titleDe)
                    .font(.subheadline)
                Text(ruleResult.status.title)
                    .font(.caption)
                    .foregroundStyle(statusColor)
                if let matched = ruleResult.matchedText {
                    Text(matched)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                if let language = ruleResult.matchedLanguage, language != "de" {
                    Text("Sprache: \(LabelingCheckService.languageName(language))")
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 2)
    }

    private var statusColor: Color {
        switch ruleResult.status {
        case .found: return .green
        case .probablyFound: return .teal
        case .missing: return ruleResult.rule.severity == .critical ? .red : .orange
        case .unclear: return .orange
        case .notApplicable: return .secondary
        case .notCheckable: return .gray
        }
    }
}

// MARK: - Rule Detail View

struct LabelingRuleDetailView: View {
    let ruleResult: RuleCheckResult

    var body: some View {
        List {
            Section("Status") {
                HStack {
                    Image(systemName: ruleResult.status.icon)
                        .foregroundStyle(statusColor)
                    Text(ruleResult.status.title)
                        .foregroundStyle(statusColor)
                }
                if let matched = ruleResult.matchedText {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Gefundener Text:")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        Text(matched)
                            .font(.body)
                            .textSelection(.enabled)
                    }
                }
                if let language = ruleResult.matchedLanguage {
                    LabeledContent("Gefunden in", value: LabelingCheckService.languageName(language))
                }
                if let note = ruleResult.note {
                    Text(note)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                if ruleResult.confidence > 0 {
                    LabeledContent("Konfidenz", value: "\(Int(ruleResult.confidence * 100)) %")
                }
            }

            Section("Regel") {
                LabeledContent("Titel", value: ruleResult.rule.titleDe)
                LabeledContent("Schwere") {
                    severityLabel
                }
                Text(ruleResult.rule.descriptionDe)
                    .font(.body)
                    .foregroundStyle(.secondary)
            }

            Section("Rechtsgrundlage") {
                Text(ruleResult.rule.legalBasis)
                    .textSelection(.enabled)
            }
        }
        .navigationTitle(ruleResult.rule.titleDe)
        .navigationBarTitleDisplayMode(.inline)
    }

    private var statusColor: Color {
        switch ruleResult.status {
        case .found: return .green
        case .probablyFound: return .teal
        case .missing: return ruleResult.rule.severity == .critical ? .red : .orange
        case .unclear: return .orange
        case .notApplicable: return .secondary
        case .notCheckable: return .gray
        }
    }

    private var severityLabel: some View {
        let (label, color): (String, Color) = {
            switch ruleResult.rule.severity {
            case .critical: return ("Kritisch", .red)
            case .warning: return ("Warnung", .orange)
            case .info: return ("Information", .secondary)
            }
        }()
        return Text(label)
            .font(.caption)
            .fontWeight(.semibold)
            .foregroundStyle(color)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(color.opacity(0.12))
            .clipShape(Capsule())
    }
}
