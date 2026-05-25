import PhotosUI
import SwiftUI
import UIKit

// MARK: - IngredientScanView

/// The central Scan tab: captures 1–5 images, runs OCR per image, merges the text,
/// analyses the result once, saves to history, then provides buttons to jump to
/// the Zusatzstoffe or Kennzeichnung tab.
///
/// The check modules (Zusatzstoffe, Kennzeichnung) are **pure consumers** of the
/// `ScanEntry` produced here — they do not run their own OCR or image capture.
struct IngredientScanView: View {
    @ObservedObject var scanHistory: ScanHistoryService
    @ObservedObject var labelingStore: LabelingRuleStore
    @Binding var selectedTab: AppTab
    @Binding var selectedAdditiveScan: ScanEntry?
    @Binding var selectedLabelingScan: ScanEntry?

    @StateObject private var session = MultiImageOCRSession()
    @State private var analysisResult: ScanAnalysisResult?
    @State private var savedEntry: ScanEntry?
    @State private var isAnalysing = false
    @State private var analyseError: String?
    @State private var isAddImagePresented = false

    var body: some View {
        NavigationStack {
            Form {
                imageStripSection
                historySection
                if isAnalysing {
                    analysisProgressSection
                } else if let analyseError {
                    errorSection(analyseError)
                } else if let result = analysisResult, let entry = savedEntry {
                    analysisResultSection(result: result, entry: entry)
                } else {
                    instructionSection
                }
            }
            .navigationTitle("Scan")
            .sheet(isPresented: $isAddImagePresented) {
                AddImageSheet(
                    defaultType: OCRImageType.suggestedType(forIndex: session.imageCount)
                ) { image, type in
                    Task { await session.addImage(image, type: type) }
                }
            }
        }
    }

    // MARK: - Sections

    private var historySection: some View {
        Section {
            NavigationLink {
                ScanHistoryPickerView(service: scanHistory, title: "Scan-Historie") { entry in
                    CentralScanHistoryEntryView(
                        entry: entry,
                        image: scanHistory.thumbnail(for: entry),
                        feedTypeName: feedTypeName(for: entry.analysisResult?.detectedFeedTypeId),
                        onUseForAdditives: {
                            loadHistoryEntry(entry)
                            selectedTab = .additives
                        },
                        onUseForLabeling: {
                            loadHistoryEntry(entry)
                            selectedTab = .labeling
                        }
                    )
                    .onAppear {
                        loadHistoryEntry(entry)
                    }
                }
            } label: {
                Label("Gespeicherte Scans", systemImage: "clock.arrow.circlepath")
            }

            if let latest = scanHistory.entries.first {
                Button {
                    loadHistoryEntry(latest)
                } label: {
                    Label("Letzten Scan laden", systemImage: "arrow.clockwise")
                }
            }
        } header: {
            Text("Scan-Historie")
        } footer: {
            Text("Ein hier geladener Scan steht anschließend automatisch in Zusatzstoffe und Kennzeichnung zur Verfügung.")
                .font(.caption2)
        }
    }

    private var imageStripSection: some View {
        Section {
            if session.isEmpty {
                VStack(spacing: 10) {
                    Image(systemName: "photo.stack")
                        .font(.largeTitle).foregroundStyle(.secondary)
                    Text("Noch keine Bilder hinzugefügt")
                        .font(.subheadline).foregroundStyle(.secondary)
                    Text("Fotografiere das Etikett von verschiedenen Seiten für eine genaue Analyse.")
                        .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 8)
            } else {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 10) {
                        ForEach(session.images) { img in
                            ImageThumbnailCard(
                                sessionImage: img,
                                onDelete: {
                                    session.remove(img)
                                    clearAnalysis()
                                },
                                onTypeChange: { newType in
                                    session.updateType(for: img, to: newType)
                                    clearAnalysis()
                                }
                            )
                        }
                    }
                    .padding(.vertical, 4).padding(.horizontal, 2)
                }
            }

            // Progress + add button row
            HStack {
                if !session.isEmpty {
                    Text("\(session.imageCount) von \(MultiImageOCRSession.maxImages) Bildern")
                        .font(.caption).foregroundStyle(.secondary)
                } else {
                    Text("Bis zu \(MultiImageOCRSession.maxImages) Bilder möglich")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                if session.canAddMore {
                    Button {
                        isAddImagePresented = true
                        clearAnalysis()
                    } label: {
                        Label("Bild hinzufügen", systemImage: "plus.circle.fill")
                    }
                    .buttonStyle(.borderedProminent).controlSize(.small)
                }
            }

            if session.isScanning {
                HStack(spacing: 8) {
                    ProgressView()
                    Text("Texterkennung läuft…").foregroundStyle(.secondary)
                }
                .font(.subheadline)
            }

            if let err = session.scanError {
                Text(err).foregroundStyle(.red).font(.caption)
            }

            // Analyse button — only when OCR is done and there are images
            if !session.isEmpty && !session.isScanning && analysisResult == nil {
                Button {
                    Task { await runAnalysis() }
                } label: {
                    Label("Etikett analysieren", systemImage: "wand.and.stars")
                }
                .disabled(session.mergedOCRText.count < 10)
            }

        } header: {
            Text("Etikett-Bilder")
        } footer: {
            if !session.isEmpty {
                Button(role: .destructive) { resetAll() } label: {
                    Label("Neuen Scan starten", systemImage: "arrow.counterclockwise")
                        .font(.caption)
                }
            }
        }
    }

    private var analysisProgressSection: some View {
        Section {
            HStack(spacing: 8) {
                ProgressView()
                Text("Etikett wird analysiert…").foregroundStyle(.secondary)
            }
        }
    }

    private func errorSection(_ message: String) -> some View {
        Section {
            Text(message).foregroundStyle(.red).font(.caption)
        }
    }

    @ViewBuilder
    private func analysisResultSection(
        result: ScanAnalysisResult,
        entry: ScanEntry
    ) -> some View {
        // Summary
        Section("Analyseergebnis") {
            LabeledContent("Bilder", value: "\(entry.imageCount)")

            if let ftId = result.detectedFeedTypeId,
               let ft = labelingStore.feedTypes.first(where: { $0.id == ftId }) {
                LabeledContent("Futtermittelart") {
                    VStack(alignment: .trailing, spacing: 2) {
                        Text(ft.displayName)
                        Text("\(Int(result.feedTypeConfidence * 100)) %")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }
            }

            if !result.detectedSpeciesHints.isEmpty {
                LabeledContent("Tierarten",
                               value: result.detectedSpeciesHints.joined(separator: ", "))
            }

            let areas = result.labelingAreas.detectedNames
            if !areas.isEmpty {
                LabeledContent("Erkannte Bereiche",
                               value: areas.joined(separator: ", "))
            } else {
                Label("Keine Kennzeichnungsbereiche erkannt", systemImage: "exclamationmark.triangle")
                    .font(.caption).foregroundStyle(.orange)
            }
        }

        // Additive hints
        if result.additiveHints.hasAdditiveSection
            || result.additiveHints.hasStructuredDeclarations
        {
            Section("Zusatzstoff-Hinweise") {
                if result.additiveHints.hasStructuredDeclarations {
                    Label("Strukturierte Zusatzstoffangaben erkannt",
                          systemImage: "checkmark.circle")
                        .foregroundStyle(.green)
                    if !result.additiveHints.detectedSubstanceNames.isEmpty {
                        Text(result.additiveHints.detectedSubstanceNames.joined(separator: " · "))
                            .font(.caption).foregroundStyle(.secondary)
                    }
                } else if result.additiveHints.hasAdditiveSection {
                    Label("Zusatzstoff-Abschnitt erkannt",
                          systemImage: "checkmark.circle")
                        .foregroundStyle(.teal)
                }
                if result.additiveHints.hasENumbers {
                    Label("E-Nummern erkannt",
                          systemImage: "e.square").foregroundStyle(.secondary).font(.caption)
                }
            }
        }

        // Warnings
        if !result.qualityWarnings.isEmpty {
            Section("Hinweise") {
                ForEach(result.qualityWarnings, id: \.self) { warning in
                    Label(warning, systemImage: "exclamationmark.triangle")
                        .font(.caption).foregroundStyle(.orange)
                }
            }
        }

        // Navigation buttons
        Section("Prüfen") {
            Button {
                selectedAdditiveScan = entry
                selectedTab = .additives
            } label: {
                Label("Zusatzstoffe prüfen", systemImage: "list.bullet.rectangle")
            }

            Button {
                selectedLabelingScan = entry
                selectedTab = .labeling
            } label: {
                Label("Kennzeichnung prüfen", systemImage: "tag.circle")
            }

            Text("Beide Prüfmodule verwenden denselben Scan – keine erneute OCR.")
                .font(.caption).foregroundStyle(.secondary)
        }

        // OCR text disclosure
        if !entry.ocrText.isEmpty {
            Section {
                DisclosureGroup("Erkannter Text (\(entry.ocrText.count) Zeichen)") {
                    Text(entry.ocrText)
                        .font(.footnote).textSelection(.enabled)
                }
            }
        }
    }

    private var instructionSection: some View {
        Section {
            Text("Hier wird das Etikett erfasst und zentral analysiert. Die Auswertung erfolgt danach in den Tabs Zusatzstoffe und Kennzeichnung – ohne erneute OCR.")
                .font(.caption).foregroundStyle(.secondary)
        }
    }

    // MARK: - Actions

    private func runAnalysis() async {
        guard !session.mergedOCRText.isEmpty else { return }
        isAnalysing = true
        analyseError = nil
        defer { isAnalysing = false }

        let feedTypes = labelingStore.feedTypes
        let mergedText = session.mergedOCRText
        let imageItemsSnapshot = session.images.map { img in
            OCRImageItem(id: img.id, imageType: img.imageType,
                         thumbnailFileName: nil,
                         ocrText: img.ocrText, capturedAt: img.capturedAt)
        }

        let result = ScanAnalysisService.analyze(
            mergedText: mergedText,
            imageItems: session.imageCount > 1 ? imageItemsSnapshot : nil,
            feedTypes: feedTypes
        )
        analysisResult = result

        // Save to history with analysis result attached
        if scanHistory.settings.isHistoryEnabled {
            let entry = scanHistory.add(session: session, analysis: result)
            savedEntry = entry
            // Pre-set both tab bindings so tapping the buttons works immediately
            selectedAdditiveScan = entry
            selectedLabelingScan = entry
        } else {
            // History disabled: create a transient entry for navigation
            let entry = ScanEntry(
                ocrText: mergedText,
                thumbnailFileName: nil,
                imageItems: session.imageCount > 1 ? imageItemsSnapshot : nil,
                analysisResult: result
            )
            savedEntry = entry
            selectedAdditiveScan = entry
            selectedLabelingScan = entry
        }
    }

    private func clearAnalysis() {
        analysisResult = nil
        savedEntry = nil
    }

    private func loadHistoryEntry(_ entry: ScanEntry) {
        selectedAdditiveScan = entry
        selectedLabelingScan = entry
        savedEntry = entry
        if let result = entry.analysisResult {
            analysisResult = result
        } else if !entry.ocrText.isEmpty {
            analysisResult = ScanAnalysisService.analyze(
                mergedText: entry.ocrText,
                imageItems: entry.imageItems,
                feedTypes: labelingStore.feedTypes
            )
        } else {
            analysisResult = nil
        }
        analyseError = nil
    }

    private func feedTypeName(for id: String?) -> String? {
        guard let id else { return nil }
        return labelingStore.feedTypes.first(where: { $0.id == id })?.displayName
    }

    private func resetAll() {
        session.reset()
        analysisResult = nil
        savedEntry = nil
        analyseError = nil
    }
}

private struct CentralScanHistoryEntryView: View {
    let entry: ScanEntry
    let image: UIImage?
    let feedTypeName: String?
    let onUseForAdditives: () -> Void
    let onUseForLabeling: () -> Void

    var body: some View {
        List {
            Section("Scan") {
                if let image {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFit()
                        .frame(maxHeight: 240)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                }
                LabeledContent("Datum", value: entry.timestamp.formatted(date: .abbreviated, time: .shortened))
                LabeledContent("Bilder", value: "\(entry.imageCount)")
            }

            if let result = entry.analysisResult {
                Section("Erkannte Inhalte") {
                    if let feedTypeName {
                        LabeledContent("Futtermittelart", value: feedTypeName)
                    }
                    if !result.detectedSpeciesHints.isEmpty {
                        LabeledContent("Tierarten", value: result.detectedSpeciesHints.joined(separator: ", "))
                    }
                    let areas = result.labelingAreas.detectedNames
                    if !areas.isEmpty {
                        LabeledContent("Bereiche", value: areas.joined(separator: ", "))
                    }
                    if !result.additiveHints.detectedSubstanceNames.isEmpty {
                        LabeledContent("Zusatzstoffe", value: result.additiveHints.detectedSubstanceNames.joined(separator: ", "))
                    } else if result.additiveHints.hasAdditiveSection {
                        LabeledContent("Zusatzstoffe", value: "Abschnitt erkannt")
                    }
                }
            }

            Section("Verwenden") {
                Button {
                    onUseForAdditives()
                } label: {
                    Label("Für Zusatzstoffe verwenden", systemImage: "list.bullet.rectangle")
                }

                Button {
                    onUseForLabeling()
                } label: {
                    Label("Für Kennzeichnung verwenden", systemImage: "tag.circle")
                }
            }

            if !entry.ocrText.isEmpty {
                Section {
                    DisclosureGroup("Erkannter Text (\(entry.ocrText.count) Zeichen)") {
                        Text(entry.ocrText)
                            .font(.footnote)
                            .textSelection(.enabled)
                    }
                }
            }
        }
        .navigationTitle("Scan")
        .navigationBarTitleDisplayMode(.inline)
    }
}

// MARK: - Image Thumbnail Card (scan capture)

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
                        .font(.title3).shadow(radius: 1)
                }
                .offset(x: 7, y: -7)
            }

            Button { isTypePickerPresented = true } label: {
                HStack(spacing: 3) {
                    Image(systemName: sessionImage.imageType.systemImage)
                    Text(sessionImage.imageType.displayName)
                }
                .font(.caption2).lineLimit(1)
            }
            .buttonStyle(.plain).foregroundStyle(.secondary)
        }
        .frame(width: 98)
        .confirmationDialog("Bildtyp wählen", isPresented: $isTypePickerPresented,
                            titleVisibility: .visible) {
            ForEach(OCRImageType.allCases) { type in
                Button(type.displayName) { onTypeChange(type) }
            }
            Button("Abbrechen", role: .cancel) {}
        }
    }

    @ViewBuilder
    private var thumbnailView: some View {
        if let img = sessionImage.image {
            Image(uiImage: img).resizable().scaledToFill()
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
                        Image(uiImage: img).resizable().scaledToFit()
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

// MARK: - Camera Picker

struct CameraPicker: UIViewControllerRepresentable {
    @Binding var image: UIImage?
    @Environment(\.dismiss) private var dismiss

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let controller = UIImagePickerController()
        controller.sourceType = .camera
        controller.delegate = context.coordinator
        return controller
    }

    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(image: $image, dismiss: dismiss)
    }

    final class Coordinator: NSObject, UINavigationControllerDelegate, UIImagePickerControllerDelegate {
        @Binding private var image: UIImage?
        private let dismiss: DismissAction

        init(image: Binding<UIImage?>, dismiss: DismissAction) {
            _image = image
            self.dismiss = dismiss
        }

        func imagePickerController(
            _ picker: UIImagePickerController,
            didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]
        ) {
            image = info[.originalImage] as? UIImage
            dismiss()
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            dismiss()
        }
    }
}
