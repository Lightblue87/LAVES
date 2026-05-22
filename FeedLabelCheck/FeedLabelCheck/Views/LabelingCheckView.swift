import SwiftUI
import UIKit

struct LabelingCheckView: View {
    @ObservedObject var labelingStore: LabelingRuleStore
    @ObservedObject var scanHistory: ScanHistoryService
    @Binding var selectedScanEntry: ScanEntry?
    @ObservedObject var additiveStore: AdditiveStore

    @State private var selectedFeedType: LabelingFeedType?
    @State private var detectionResult: LabelingFeedTypeDetector.DetectionResult?
    @State private var ambiguousCandidates: [LabelingFeedTypeDetector.DetectionResult] = []
    @State private var needsManualSelection = false
    @State private var checkResult: LabelingCheckResult?
    @State private var isChecking = false
    @State private var checkError: String?
    @State private var isResultPresented = false

    /// Combined control session (basis document + comparison). Lives entirely
    /// in this view — no new storage path, no new OCR workflow.
    @StateObject private var controlSession = LabelingControlSession()

    private let detector = LabelingFeedTypeDetector()

    var body: some View {
        NavigationStack {
            Form {
                databaseSection
                controlBasisSection
                loadedScanSection
                feedTypeSection
                actionSection
                controlComparisonSection
                historySection
            }
            .navigationTitle("Kennzeichnung")
            .toolbar {
                if let dbInfo = labelingStore.dbInfo {
                    ToolbarItem(placement: .topBarTrailing) {
                        Text("v\(dbInfo.version)")
                            .font(.caption2)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .sheet(isPresented: $isResultPresented) {
                if let result = checkResult {
                    LabelingResultView(
                        result: result,
                        additiveStore: additiveStore
                    ) {
                        needsManualSelection = true
                        selectedFeedType = nil
                    }
                }
            }
            .onAppear {
                if let entry = selectedScanEntry {
                    applyScanEntry(entry)
                }
            }
            .onChange(of: selectedScanEntry) { _, entry in
                guard let entry else { return }
                applyScanEntry(entry)
            }
            .task { await labelingStore.load() }
        }
    }

    // MARK: - Sections

    private var databaseSection: some View {
        Section("Regeldatenbank") {
            if let dbInfo = labelingStore.dbInfo {
                LabeledContent("Quelle", value: dbInfo.regulation)
                LabeledContent("Regelversion", value: dbInfo.version)
                LabeledContent("Datenstand", value: formattedDataDate(dbInfo.createdAt))
                LabeledContent("Regeln", value: "\(dbInfo.totalRuleCount)")
            } else if let error = labelingStore.loadError {
                Text(error).font(.caption).foregroundStyle(.red)
            } else {
                HStack {
                    ProgressView()
                    Text("Regeldatenbank wird geladen…").foregroundStyle(.secondary)
                }
            }

            if labelingStore.isUpdating {
                VStack(alignment: .leading, spacing: 8) {
                    Text(labelingStore.updateDetail ?? "Wird aktualisiert")
                        .font(.caption).foregroundStyle(.secondary)
                    if let p = labelingStore.updateProgress { ProgressView(value: p) }
                    else { ProgressView() }
                }
            } else {
                Button {
                    Task { await labelingStore.updateFromRemote() }
                } label: {
                    Label(
                        labelingStore.updateAvailable ? "Regeldatenbank aktualisieren" : "Regeldaten prüfen",
                        systemImage: "arrow.down.circle"
                    )
                }
            }
        }
    }

    @ViewBuilder
    private var loadedScanSection: some View {
        Section {
            if let entry = selectedScanEntry {
                LabeledContent("Scan",
                               value: entry.timestamp.formatted(date: .abbreviated, time: .shortened))
                LabeledContent("Bilder", value: "\(entry.imageCount)")

                if let result = entry.analysisResult {
                    let areas = result.labelingAreas.detectedNames
                    if !areas.isEmpty {
                        LabeledContent("Erkannte Bereiche", value: areas.joined(separator: ", "))
                    }
                    if !result.detectedSpeciesHints.isEmpty {
                        LabeledContent("Tierart",
                                       value: result.detectedSpeciesHints.joined(separator: ", "))
                    }
                    ForEach(result.qualityWarnings, id: \.self) { warning in
                        Label(warning, systemImage: "exclamationmark.triangle")
                            .font(.caption).foregroundStyle(.orange)
                    }
                }

                if !entry.ocrText.isEmpty {
                    DisclosureGroup("Erkannter Text (\(entry.ocrText.count) Zeichen)") {
                        Text(entry.ocrText)
                            .font(.footnote)
                            .textSelection(.enabled)
                    }
                }

                Button(role: .destructive) { resetCheck() } label: {
                    Label("Scan entfernen", systemImage: "xmark.circle")
                        .font(.caption)
                }
            } else {
                VStack(spacing: 8) {
                    Image(systemName: "doc.text.magnifyingglass")
                        .font(.largeTitle)
                        .foregroundStyle(.secondary)
                    Text("Kein Scan geladen")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text("Scanne ein Etikett im Scan-Tab oder lade einen vorhandenen Scan aus der Scan-Historie.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
            }
        } header: {
            Text("Geladener Scan")
        }
    }

    private var feedTypeSection: some View {
        Section("Futtermittelart") {
            if selectedScanEntry == nil || selectedScanEntry?.ocrText.isEmpty == true {
                Text("Bitte zuerst einen Scan laden.")
                    .foregroundStyle(.secondary)
                    .font(.caption)
            } else if let detection = detectionResult, !needsManualSelection {
                HStack {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(detection.feedType.displayName).font(.subheadline)
                        Text("Automatisch erkannt · \(Int(detection.confidence * 100)) %")
                            .font(.caption)
                            .foregroundStyle(detection.confidence < 0.6 ? .orange : .secondary)
                    }
                    Spacer()
                    Button("Ändern") { needsManualSelection = true }.font(.caption)
                }
                if detection.confidence < 0.6 {
                    Label(
                        "Niedrige Erkennungssicherheit – bitte Futtermittelart manuell bestätigen.",
                        systemImage: "exclamationmark.triangle"
                    )
                    .font(.caption).foregroundStyle(.orange)
                }
            } else {
                if !ambiguousCandidates.isEmpty && detectionResult == nil {
                    Label(
                        "Mehrere Futtermittelarten erkannt – bitte auswählen.",
                        systemImage: "exclamationmark.triangle"
                    )
                    .font(.caption).foregroundStyle(.orange)
                }
                Picker("Futtermittelart", selection: $selectedFeedType) {
                    Text("Auswählen…").tag(Optional<LabelingFeedType>.none)
                    ForEach(labelingStore.feedTypes.filter { $0.id != "all" && $0.id != "unknown" }) { ft in
                        Text(ft.displayName).tag(Optional(ft))
                    }
                }
                .pickerStyle(.menu)
            }
        }
    }

    @ViewBuilder
    private var actionSection: some View {
        Section {
            if let error = checkError {
                Text(error).foregroundStyle(.red).font(.caption)
            }

            Button {
                Task { await runCheck() }
            } label: {
                if isChecking {
                    HStack { ProgressView(); Text("Prüfung läuft…") }
                } else {
                    Label("Kennzeichnung prüfen", systemImage: "checkmark.shield")
                }
            }
            .disabled(!canCheck || isChecking)
        }

        if let result = checkResult {
            Section {
                Button {
                    isResultPresented = true
                } label: {
                    HStack {
                        Image(systemName: result.overallStatus.icon)
                            .foregroundStyle(overallColor(result.overallStatus))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(result.overallStatus.rawValue)
                                .fontWeight(.semibold)
                                .foregroundStyle(overallColor(result.overallStatus))
                            Text("\(result.ruleResults.count) relevante Regeln geprüft · Ergebnis anzeigen")
                                .font(.caption).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Image(systemName: "chevron.right").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    // MARK: - Kontrollgrundlage

    @ViewBuilder
    private var controlBasisSection: some View {
        Section {
            Picker("Dokumenttyp", selection: $controlSession.basisDocumentType) {
                ForEach(BasisDocumentType.allCases) { type in
                    Label(type.displayName, systemImage: type.systemImage).tag(type)
                }
            }
            .pickerStyle(.menu)

            if let basis = controlSession.basisScan {
                LabeledContent("Grundlage", value: basis.timestamp.formatted(
                    date: .abbreviated, time: .shortened))
                if controlSession.isAnalyzingBasis {
                    HStack { ProgressView(); Text("Analysiere…").foregroundStyle(.secondary) }
                } else if controlSession.hasSuggestions {
                    DisclosureGroup(
                        "Erkannte Anforderungen (\(controlSession.requirementSuggestions.count))"
                    ) {
                        ForEach(controlSession.requirementSuggestions) { s in
                            RequirementSuggestionRow(suggestion: s)
                        }
                    }
                } else {
                    Label("Keine kennzeichnungsrelevanten Angaben erkannt.",
                          systemImage: "info.circle")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Button(role: .destructive) {
                    controlSession.resetBasis()
                } label: {
                    Label("Grundlage entfernen", systemImage: "xmark.circle")
                        .font(.caption)
                }
            } else {
                NavigationLink {
                    ScanHistoryPickerView(
                        service: scanHistory,
                        title: "Grundlage auswählen"
                    ) { entry in
                        LabelingScanEntryPreview(
                            entry: entry,
                            image: scanHistory.thumbnail(for: entry)
                        )
                        .onAppear {
                            controlSession.setBasisScan(entry)
                        }
                    }
                } label: {
                    Label("Grundlage aus Scan-Historie laden",
                          systemImage: "doc.text.magnifyingglass")
                }
            }
        } header: {
            Text("Kontrollgrundlage")
        } footer: {
            Text("Optional: Partieprotokoll, Rezeptur oder Analysebericht scannen, um die Verpackungsangaben automatisch abzugleichen.")
                .font(.caption2)
        }
    }

    // MARK: - Abgleich

    @ViewBuilder
    private var controlComparisonSection: some View {
        if let comparison = controlSession.comparisonResult {
            Section {
                // Summary row
                HStack(spacing: 12) {
                    Image(systemName: comparison.hasIssues
                          ? "exclamationmark.triangle.fill" : "checkmark.shield.fill")
                        .foregroundStyle(comparison.hasIssues ? .orange : .green)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(comparison.hasIssues ? "Abweichungen gefunden" : "Kein Auffälligkeit")
                            .fontWeight(.semibold)
                        Text([
                            comparison.matchedCount > 0 ? "\(comparison.matchedCount) ✅" : nil,
                            comparison.mismatchCount > 0 ? "\(comparison.mismatchCount) ⚠️" : nil,
                            comparison.missingCount > 0 ? "\(comparison.missingCount) ❌" : nil,
                            comparison.notCheckableCount > 0 ? "\(comparison.notCheckableCount) 🔍" : nil,
                        ].compactMap { $0 }.joined(separator: "  "))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                }
                .padding(.vertical, 4)

                ForEach(comparison.entries) { entry in
                    ComparisonEntryRow(entry: entry)
                }
            } header: {
                Text("Abgleich Grundlage ↔ Verpackung")
            } footer: {
                Text("Automatischer Abgleich auf Basis erkannter OCR-Daten. Kein Ersatz für eine amtliche Kontrolle.")
                    .font(.caption2)
            }
        }
    }

    private var historySection: some View {
        Section("Scan-Historie") {
            NavigationLink {
                ScanHistoryPickerView(service: scanHistory, title: "Kennzeichnungs-Scans") { entry in
                    LabelingScanEntryPreview(entry: entry, image: scanHistory.thumbnail(for: entry))
                        .onAppear {
                            selectedScanEntry = entry
                            applyScanEntry(entry)
                        }
                }
            } label: {
                Label("Aus Scan-Historie laden", systemImage: "clock.arrow.circlepath")
            }

            if let latest = scanHistory.entries.first {
                Button {
                    selectedScanEntry = latest
                    applyScanEntry(latest)
                } label: {
                    Label("Letzten Scan laden", systemImage: "arrow.clockwise")
                }
            }
        }
    }

    // MARK: - Logic

    private var activeFeedType: LabelingFeedType? {
        selectedFeedType ?? detectionResult?.feedType
    }

    private var canCheck: Bool {
        guard let entry = selectedScanEntry else { return false }
        let text = entry.ocrText
        return !text.isEmpty && text.count >= LabelingCheckService.minOCRLength && activeFeedType != nil
    }

    private func applyScanEntry(_ entry: ScanEntry) {
        detectionResult = nil
        selectedFeedType = nil
        needsManualSelection = false
        checkResult = nil
        checkError = nil
        updateFeedTypeDetection(for: entry)
    }

    private func updateFeedTypeDetection(for entry: ScanEntry) {
        let text = entry.ocrText
        guard !text.isEmpty else {
            detectionResult = nil
            ambiguousCandidates = []
            return
        }
        let candidates = detector.detectAmbiguous(in: text, feedTypes: labelingStore.feedTypes)
        ambiguousCandidates = candidates
        detectionResult = nil
        needsManualSelection = false
        if let unambiguous = detector.detect(in: text, feedTypes: labelingStore.feedTypes) {
            detectionResult = unambiguous
        } else if !candidates.isEmpty {
            needsManualSelection = true
        }
    }

    private func resetCheck() {
        selectedScanEntry = nil
        detectionResult = nil
        selectedFeedType = nil
        needsManualSelection = false
        checkResult = nil
        checkError = nil
    }

    private func runCheck() async {
        guard let entry = selectedScanEntry,
              let feedType = activeFeedType else { return }
        isChecking = true
        checkResult = nil
        checkError = nil
        defer { isChecking = false }

        let rules = await labelingStore.rules(forFeedType: feedType.id)
        let feedConfidence = selectedFeedType != nil ? 1.0 : (detectionResult?.confidence ?? 0)
        let mergedText = entry.ocrText

        // Coverage: use pre-computed result if available; fall back to imageItems
        let notCheckablePrefixes: Set<String>
        if let prefixes = entry.analysisResult?.imageCoverage.forcedNotCheckableRulePrefixes {
            notCheckablePrefixes = Set(prefixes)
        } else if let items = entry.imageItems, !items.isEmpty {
            let covered = Set(items.map(\.imageType))
            notCheckablePrefixes = LabelCoverageAnalyzer.forcedNotCheckableRulePrefixes(
                coveredTypes: covered,
                imageCount: items.count
            )
        } else {
            notCheckablePrefixes = []
        }

        // Parse structured additive declarations (offline, no network)
        let declarations = AdditiveDeclarationParser.parse(
            text: mergedText,
            additives: additiveStore.additives
        )

        let result = LabelingCheckService.check(
            ocrText: mergedText,
            feedType: feedType,
            feedTypeConfidence: feedConfidence,
            rules: rules,
            dbInfo: labelingStore.dbInfo,
            forcedNotCheckableRulePrefixes: notCheckablePrefixes,
            imageItems: entry.imageItems,
            additiveDeclarations: declarations
        )
        checkResult = result
        isResultPresented = true

        // Automatically run comparison when a basis scan is loaded
        if controlSession.hasBasis {
            controlSession.runComparison(
                packagingCheckResult: result,
                packagingOCRText: mergedText
            )
        }
    }

    private func overallColor(_ status: LabelingOverallStatus) -> Color {
        switch status {
        case .keineAuffaelligkeit: return .green
        case .auffaellig: return .red
        case .unklar: return .orange
        case .nichtPruefbar: return .gray
        }
    }

    private func formattedDataDate(_ value: String) -> String {
        let isoFrac = ISO8601DateFormatter()
        isoFrac.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime]
        guard let date = isoFrac.date(from: value) ?? iso.date(from: value) else { return value }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
}

// MARK: - Labeling Scan Entry Preview

private struct LabelingScanEntryPreview: View {
    let entry: ScanEntry
    let image: UIImage?

    var body: some View {
        List {
            Section("Bild") {
                if let image {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFit()
                        .frame(maxHeight: 240)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                }
                LabeledContent("Scan", value: entry.timestamp.formatted(date: .abbreviated, time: .shortened))
                if let items = entry.imageItems, !items.isEmpty {
                    LabeledContent("Bilder", value: "\(items.count)")
                    LabeledContent("Bereiche", value: items.map(\.imageType.displayName).joined(separator: ", "))
                }
            }

            Section("Gelesener Text") {
                Text(entry.ocrText)
                    .font(.footnote)
                    .textSelection(.enabled)
            }
        }
        .navigationTitle("Scan geladen")
    }
}

// MARK: - Requirement Suggestion Row

private struct RequirementSuggestionRow: View {
    let suggestion: LabelingRequirementSuggestion

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: statusIcon)
                .foregroundStyle(statusColor)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 4) {
                    Text(suggestion.category.displayName)
                        .font(.caption)
                        .fontWeight(.semibold)
                    if let nv = suggestion.normalizedValue, !nv.displayString.isEmpty {
                        Text("– \(nv.displayString)")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                Text(suggestion.extractedText)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .padding(.vertical, 2)
    }

    private var statusIcon: String {
        switch suggestion.status {
        case .mustDeclare:      return "checkmark.circle"
        case .shouldReview:     return "questionmark.circle"
        case .notLabelRelevant: return "minus.circle"
        case .unclear:          return "exclamationmark.circle"
        }
    }

    private var statusColor: Color {
        switch suggestion.status {
        case .mustDeclare:      return .blue
        case .shouldReview:     return .orange
        case .notLabelRelevant: return .secondary
        case .unclear:          return .orange
        }
    }
}

// MARK: - Comparison Entry Row

private struct ComparisonEntryRow: View {
    let entry: ComparisonEntry

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: entry.packagingStatus.icon)
                .foregroundStyle(statusColor)
                .frame(width: 18)
            VStack(alignment: .leading, spacing: 2) {
                Text(entry.suggestion.category.displayName)
                    .font(.subheadline)
                    .fontWeight(.medium)
                if let pkgText = entry.packagingText {
                    Text(pkgText)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                if let note = entry.note {
                    Text(note)
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
            }
            Spacer()
            Text(entry.packagingStatus.displayName)
                .font(.caption2)
                .foregroundStyle(statusColor)
        }
        .padding(.vertical, 2)
    }

    private var statusColor: Color {
        switch entry.packagingStatus {
        case .matched:            return .green
        case .missingOnPackaging: return .red
        case .mismatch:           return .orange
        case .notCheckable:       return .gray
        case .unclear:            return .orange
        case .notRequired:        return .secondary
        }
    }
}
