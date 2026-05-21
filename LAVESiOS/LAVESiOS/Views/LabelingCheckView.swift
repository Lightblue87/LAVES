import SwiftUI

struct LabelingCheckView: View {
    @ObservedObject var labelingStore: LabelingRuleStore
    @ObservedObject var scanHistory: ScanHistoryService
    @Binding var selectedScanEntry: ScanEntry?

    @State private var selectedImage: UIImage?
    @State private var ocrText = ""
    @State private var selectedFeedType: LabelingFeedType?
    @State private var detectionResult: LabelingFeedTypeDetector.DetectionResult?
    @State private var ambiguousCandidates: [LabelingFeedTypeDetector.DetectionResult] = []
    @State private var needsManualSelection = false
    @State private var checkResult: LabelingCheckResult?
    @State private var isChecking = false
    @State private var checkError: String?
    @State private var isResultPresented = false

    private let detector = LabelingFeedTypeDetector()

    var body: some View {
        NavigationStack {
            Form {
                databaseSection
                imageSection
                feedTypeSection
                actionSection
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
                    LabelingResultView(result: result)
                }
            }
            .onAppear {
                if let selectedScanEntry, ocrText.isEmpty {
                    applyScanEntry(selectedScanEntry)
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
                LabeledContent("CELEX", value: dbInfo.celex)
                LabeledContent("Regelversion", value: dbInfo.version)
                LabeledContent("Datenstand", value: formattedDataDate(dbInfo.createdAt))
                LabeledContent("Regeln", value: "\(dbInfo.ruleCount)")
            } else if let error = labelingStore.loadError {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
            } else {
                HStack {
                    ProgressView()
                    Text("Regeldatenbank wird geladen…")
                        .foregroundStyle(.secondary)
                }
            }

            if labelingStore.isUpdating {
                VStack(alignment: .leading, spacing: 8) {
                    Text(labelingStore.updateDetail ?? "Kennzeichnungsdaten werden aktualisiert")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    if let progress = labelingStore.updateProgress {
                        ProgressView(value: progress)
                    } else {
                        ProgressView()
                    }
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
    private var imageSection: some View {
        Section("Scan-Historie") {
            if let selectedScanEntry {
                HStack(spacing: 12) {
                    if let image = scanHistory.thumbnail(for: selectedScanEntry) {
                        Image(uiImage: image)
                            .resizable()
                            .scaledToFill()
                            .frame(width: 48, height: 48)
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                    } else {
                        Image(systemName: "photo")
                            .frame(width: 48, height: 48)
                            .foregroundStyle(.secondary)
                    }

                    VStack(alignment: .leading, spacing: 3) {
                        Text("Aktueller Scan geladen")
                            .font(.subheadline)
                        Text(selectedScanEntry.timestamp.formatted(date: .abbreviated, time: .shortened))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            NavigationLink {
                ScanHistoryPickerView(service: scanHistory, title: "Kennzeichnungs-Scans") { entry in
                    LabelingScanEntryPreview(entry: entry, image: scanHistory.thumbnail(for: entry))
                        .onAppear {
                            selectedScanEntry = entry
                            applyScanEntry(entry)
                        }
                }
            } label: {
                Label("Gespeicherte Scans", systemImage: "clock.arrow.circlepath")
            }

            if let latest = scanHistory.entries.first {
                Button {
                    applyScanEntry(latest)
                } label: {
                    Label("Letzten Scan laden", systemImage: "arrow.clockwise")
                }
            }
        }

        Section("Etikett") {
            if let img = selectedImage {
                Image(uiImage: img)
                    .resizable()
                    .scaledToFit()
                    .frame(maxHeight: 200)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }

            if !ocrText.isEmpty {
                DisclosureGroup("Erkannter Text (\(ocrText.count) Zeichen)") {
                    Text(ocrText)
                        .font(.footnote)
                        .textSelection(.enabled)
                }
            }

            if let error = checkError {
                Text(error).foregroundStyle(.red).font(.caption)
            }

            if ocrText.isEmpty {
                Text("Bitte zuerst im Scan-Reiter ein Bild erfassen und danach hier aus der Historie laden.")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var feedTypeSection: some View {
        Section("Futtermittelart") {
            if !ocrText.isEmpty {
                if let detection = detectionResult, !needsManualSelection {
                    HStack {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(detection.feedType.displayName)
                                .font(.subheadline)
                            Text("Automatisch erkannt · \(Int(detection.confidence * 100)) %")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button("Ändern") {
                            needsManualSelection = true
                        }
                        .font(.caption)
                    }
                } else if needsManualSelection || detectionResult == nil {
                    if !ambiguousCandidates.isEmpty && detectionResult == nil {
                        Label("Mehrere Futtermittelarten erkannt – bitte auswählen.", systemImage: "exclamationmark.triangle")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                    Picker("Futtermittelart", selection: $selectedFeedType) {
                        Text("Auswählen…").tag(Optional<LabelingFeedType>.none)
                        ForEach(labelingStore.feedTypes.filter { $0.id != "all" && $0.id != "unknown" }) { ft in
                            Text(ft.displayName).tag(Optional(ft))
                        }
                    }
                    .pickerStyle(.menu)
                }
            } else {
                Text("Bitte zuerst im Scan-Reiter ein Bild erfassen und danach hier aus der Historie laden.")
                    .foregroundStyle(.secondary)
                    .font(.caption)
            }
        }
    }

    @ViewBuilder
    private var actionSection: some View {
        Section {
            Button {
                Task { await runCheck() }
            } label: {
                if isChecking {
                    HStack {
                        ProgressView()
                        Text("Prüfung läuft…")
                    }
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
                            Text("\(result.ruleResults.count) Regeln geprüft · Ergebnis anzeigen")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                        Image(systemName: "chevron.right")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
        }
    }

    // MARK: - Logic

    private var activeFeedType: LabelingFeedType? {
        selectedFeedType ?? detectionResult?.feedType
    }

    private var canCheck: Bool {
        !ocrText.isEmpty && ocrText.count >= LabelingCheckService.minOCRLength && activeFeedType != nil
    }

    private func applyScanEntry(_ entry: ScanEntry) {
        selectedImage = scanHistory.thumbnail(for: entry)
        ocrText = entry.ocrText
        detectionResult = nil
        selectedFeedType = nil
        needsManualSelection = false
        checkResult = nil
        checkError = nil

        let candidates = detector.detectAmbiguous(in: entry.ocrText, feedTypes: labelingStore.feedTypes)
        ambiguousCandidates = candidates

        if let unambiguous = detector.detect(in: entry.ocrText, feedTypes: labelingStore.feedTypes) {
            detectionResult = unambiguous
        } else if !candidates.isEmpty {
            needsManualSelection = true
        }
    }

    private func runCheck() async {
        guard let feedType = activeFeedType else { return }
        isChecking = true
        checkResult = nil
        defer { isChecking = false }

        let rules = await labelingStore.rules(forFeedType: feedType.id)
        let feedConfidence = selectedFeedType != nil ? 1.0 : (detectionResult?.confidence ?? 0)

        checkResult = LabelingCheckService.check(
            ocrText: ocrText,
            feedType: feedType,
            feedTypeConfidence: feedConfidence,
            rules: rules,
            dbInfo: labelingStore.dbInfo
        )
        isResultPresented = true
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
