import SwiftUI

struct LabelingResultView: View {
    let result: LabelingCheckResult
    var onRecheckWithDifferentFeedType: (() -> Void)?
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                overallSection
                recheckSection
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
