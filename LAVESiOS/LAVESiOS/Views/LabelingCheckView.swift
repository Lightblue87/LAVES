import PhotosUI
import SwiftUI
import UIKit

struct LabelingCheckView: View {
    @ObservedObject var labelingStore: LabelingRuleStore
    @ObservedObject var scanHistory: ScanHistoryService
    @Binding var selectedScanEntry: ScanEntry?

    @StateObject private var session = MultiImageOCRSession()

    @State private var selectedFeedType: LabelingFeedType?
    @State private var detectionResult: LabelingFeedTypeDetector.DetectionResult?
    @State private var ambiguousCandidates: [LabelingFeedTypeDetector.DetectionResult] = []
    @State private var needsManualSelection = false
    @State private var checkResult: LabelingCheckResult?
    @State private var isChecking = false
    @State private var checkError: String?
    @State private var isResultPresented = false
    @State private var isAddImagePresented = false
    @State private var savedEntry: ScanEntry?

    private let detector = LabelingFeedTypeDetector()

    var body: some View {
        NavigationStack {
            Form {
                databaseSection
                imageStripSection
                feedTypeSection
                actionSection
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
                    LabelingResultView(result: result) {
                        needsManualSelection = true
                        selectedFeedType = nil
                    }
                }
            }
            .sheet(isPresented: $isAddImagePresented) {
                AddImageSheet(
                    defaultType: OCRImageType.suggestedType(forIndex: session.imageCount)
                ) { image, type in
                    Task { await addImage(image, type: type) }
                }
            }
            .onAppear {
                if let entry = selectedScanEntry, session.isEmpty {
                    applyScanEntry(entry)
                }
            }
            .onChange(of: selectedScanEntry) { _, entry in
                guard let entry else { return }
                applyScanEntry(entry)
            }
            .onChange(of: session.imageCount) { _, _ in
                updateFeedTypeDetection()
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

    private var imageStripSection: some View {
        Section {
            // Thumbnail strip or empty state
            if session.isEmpty {
                VStack(spacing: 10) {
                    Image(systemName: "photo.stack")
                        .font(.largeTitle)
                        .foregroundStyle(.secondary)
                    Text("Noch keine Bilder hinzugefügt")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text("Fotografiere das Etikett aus verschiedenen Winkeln für eine genaue Prüfung.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 10) {
                        ForEach(session.images) { img in
                            ImageThumbnailCard(
                                sessionImage: img,
                                onDelete: { session.remove(img) },
                                onTypeChange: { newType in session.updateType(for: img, to: newType) }
                            )
                        }
                    }
                    .padding(.vertical, 4)
                    .padding(.horizontal, 2)
                }
            }

            // Progress + add button row
            HStack {
                if !session.isEmpty {
                    Text("\(session.imageCount) von \(MultiImageOCRSession.maxImages) Bildern")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } else {
                    Text("Bis zu \(MultiImageOCRSession.maxImages) Bilder möglich")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if session.canAddMore {
                    Button {
                        isAddImagePresented = true
                    } label: {
                        Label("Bild hinzufügen", systemImage: "plus.circle.fill")
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.small)
                }
            }

            // OCR scanning indicator
            if session.isScanning {
                HStack(spacing: 8) {
                    ProgressView()
                    Text("Texterkennung läuft…").foregroundStyle(.secondary)
                }
                .font(.subheadline)
            }

            if let error = session.scanError {
                Text(error).foregroundStyle(.red).font(.caption)
            }

            // Merged OCR text disclosure
            if !session.isEmpty && !session.mergedOCRText.isEmpty {
                DisclosureGroup("Erkannter Text (\(session.mergedOCRText.count) Zeichen)") {
                    Text(session.mergedOCRText)
                        .font(.footnote)
                        .textSelection(.enabled)
                }
            }

            if session.isEmpty {
                Text("Oder lade einen vorhandenen Scan aus der Scan-Historie (unten).")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

        } header: {
            Text("Etikett-Bilder")
        } footer: {
            if !session.isEmpty {
                Button(role: .destructive) {
                    resetSession()
                } label: {
                    Label("Neue Prüfung starten", systemImage: "arrow.counterclockwise")
                        .font(.caption)
                }
            }
        }
    }

    private var feedTypeSection: some View {
        Section("Futtermittelart") {
            if session.isEmpty || session.mergedOCRText.isEmpty {
                Text("Bitte zuerst Bilder hinzufügen.")
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
            .disabled(!canCheck || isChecking || session.isScanning)
        }

        if let result = checkResult {
            Section {
                if let saved = savedEntry {
                    Label("Scan in Historie gespeichert (\(saved.imageCount) \(saved.imageCount == 1 ? "Bild" : "Bilder"))", systemImage: "checkmark.circle")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
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
        let text = session.mergedOCRText
        return !text.isEmpty && text.count >= LabelingCheckService.minOCRLength && activeFeedType != nil
    }

    private func addImage(_ image: UIImage, type: OCRImageType) async {
        await session.addImage(image, type: type)
    }

    private func applyScanEntry(_ entry: ScanEntry) {
        scanHistory.loadIntoSession(session, from: entry)
        detectionResult = nil
        selectedFeedType = nil
        needsManualSelection = false
        checkResult = nil
        checkError = nil
        savedEntry = nil
        updateFeedTypeDetection()
    }

    private func updateFeedTypeDetection() {
        let merged = session.mergedOCRText
        guard !merged.isEmpty else {
            detectionResult = nil
            ambiguousCandidates = []
            return
        }
        let candidates = detector.detectAmbiguous(in: merged, feedTypes: labelingStore.feedTypes)
        ambiguousCandidates = candidates
        detectionResult = nil
        needsManualSelection = false
        if let unambiguous = detector.detect(in: merged, feedTypes: labelingStore.feedTypes) {
            detectionResult = unambiguous
        } else if !candidates.isEmpty {
            needsManualSelection = true
        }
    }

    private func resetSession() {
        session.reset()
        detectionResult = nil
        selectedFeedType = nil
        needsManualSelection = false
        checkResult = nil
        checkError = nil
        savedEntry = nil
        selectedScanEntry = nil
    }

    private func runCheck() async {
        guard let feedType = activeFeedType else { return }
        isChecking = true
        checkResult = nil
        checkError = nil
        savedEntry = nil
        defer { isChecking = false }

        // Persist to history
        if scanHistory.settings.isHistoryEnabled && !session.isEmpty {
            savedEntry = scanHistory.add(session: session)
        }

        let rules = await labelingStore.rules(forFeedType: feedType.id)
        let feedConfidence = selectedFeedType != nil ? 1.0 : (detectionResult?.confidence ?? 0)
        let mergedText = session.mergedOCRText

        let notCheckablePrefixes = LabelCoverageAnalyzer.forcedNotCheckableRulePrefixes(
            coveredTypes: session.coveredImageTypes,
            imageCount: session.imageCount
        )

        let imageItemsSnapshot = session.images.map { img in
            OCRImageItem(
                id: img.id,
                imageType: img.imageType,
                thumbnailFileName: nil,
                ocrText: img.ocrText,
                capturedAt: img.capturedAt
            )
        }

        checkResult = LabelingCheckService.check(
            ocrText: mergedText,
            feedType: feedType,
            feedTypeConfidence: feedConfidence,
            rules: rules,
            dbInfo: labelingStore.dbInfo,
            forcedNotCheckableRulePrefixes: notCheckablePrefixes,
            imageItems: session.imageCount > 1 ? imageItemsSnapshot : nil
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
        let isoFrac = ISO8601DateFormatter()
        isoFrac.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime]
        guard let date = isoFrac.date(from: value) ?? iso.date(from: value) else { return value }
        return date.formatted(date: .abbreviated, time: .shortened)
    }
}

// MARK: - Image Thumbnail Card

private struct ImageThumbnailCard: View {
    let sessionImage: SessionImage
    let onDelete: () -> Void
    let onTypeChange: (OCRImageType) -> Void

    @State private var isTypePickerPresented = false

    var body: some View {
        VStack(spacing: 5) {
            ZStack(alignment: .topTrailing) {
                thumbnailView
                    .frame(width: 84, height: 84)
                    .clipShape(RoundedRectangle(cornerRadius: 10))

                Button(action: onDelete) {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.white, .red)
                        .font(.title3)
                        .shadow(radius: 1)
                }
                .offset(x: 7, y: -7)
            }

            Button {
                isTypePickerPresented = true
            } label: {
                HStack(spacing: 3) {
                    Image(systemName: sessionImage.imageType.systemImage)
                    Text(sessionImage.imageType.displayName)
                }
                .font(.caption2)
                .lineLimit(1)
            }
            .buttonStyle(.plain)
            .foregroundStyle(.secondary)
        }
        .frame(width: 98)
        .confirmationDialog(
            "Bildtyp wählen",
            isPresented: $isTypePickerPresented,
            titleVisibility: .visible
        ) {
            ForEach(OCRImageType.allCases) { type in
                Button(type.displayName) { onTypeChange(type) }
            }
            Button("Abbrechen", role: .cancel) {}
        }
    }

    @ViewBuilder
    private var thumbnailView: some View {
        if let img = sessionImage.image {
            Image(uiImage: img)
                .resizable()
                .scaledToFill()
        } else {
            RoundedRectangle(cornerRadius: 10)
                .fill(Color.secondary.opacity(0.15))
                .overlay {
                    VStack(spacing: 4) {
                        Image(systemName: "photo.fill").foregroundStyle(.secondary)
                        Text("Kein Bild").font(.caption2).foregroundStyle(.secondary)
                    }
                }
        }
    }
}

// MARK: - Add Image Sheet

private struct AddImageSheet: View {
    @Environment(\.dismiss) private var dismiss

    @State private var selectedPhoto: PhotosPickerItem?
    @State private var capturedImage: UIImage?
    @State private var isCameraPresented = false
    @State private var selectedType: OCRImageType

    let defaultType: OCRImageType
    let onAdd: (UIImage, OCRImageType) -> Void

    init(defaultType: OCRImageType, onAdd: @escaping (UIImage, OCRImageType) -> Void) {
        self.defaultType = defaultType
        self.onAdd = onAdd
        _selectedType = State(initialValue: defaultType)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Bildtyp") {
                    Picker("Typ", selection: $selectedType) {
                        ForEach(OCRImageType.allCases) { type in
                            Label(type.displayName, systemImage: type.systemImage).tag(type)
                        }
                    }
                    .pickerStyle(.menu)
                }

                Section("Aufnahme") {
                    Button {
                        isCameraPresented = true
                    } label: {
                        Label("Foto aufnehmen", systemImage: "camera")
                    }
                    .disabled(!UIImagePickerController.isSourceTypeAvailable(.camera))

                    PhotosPicker(selection: $selectedPhoto, matching: .images) {
                        Label("Bild aus Bibliothek", systemImage: "photo.on.rectangle")
                    }
                }

                if let img = capturedImage {
                    Section("Vorschau") {
                        Image(uiImage: img)
                            .resizable()
                            .scaledToFit()
                            .frame(maxHeight: 220)
                            .clipShape(RoundedRectangle(cornerRadius: 8))

                        Button {
                            onAdd(img, selectedType)
                            dismiss()
                        } label: {
                            Label("Bild hinzufügen", systemImage: "plus.circle.fill")
                        }
                        .bold()
                    }
                }
            }
            .navigationTitle("Bild hinzufügen")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Abbrechen") { dismiss() }
                }
            }
            .onChange(of: selectedPhoto) { _, item in
                Task {
                    guard let item,
                          let data = try? await item.loadTransferable(type: Data.self),
                          let image = UIImage(data: data) else { return }
                    capturedImage = image
                }
            }
            .sheet(isPresented: $isCameraPresented) {
                CameraPicker(image: $capturedImage).ignoresSafeArea()
            }
        }
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
