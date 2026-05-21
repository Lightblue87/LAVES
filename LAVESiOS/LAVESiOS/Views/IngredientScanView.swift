import PhotosUI
import SwiftUI
import UIKit

struct IngredientScanView: View {
    @ObservedObject var scanHistory: ScanHistoryService
    @Binding var selectedTab: AppTab
    @Binding var selectedAdditiveScan: ScanEntry?
    @Binding var selectedLabelingScan: ScanEntry?

    @State private var selectedPhoto: PhotosPickerItem?
    @State private var selectedImage: UIImage?
    @State private var recognizedText = ""
    @State private var isScanning = false
    @State private var scanError: String?
    @State private var isCameraPresented = false
    @State private var lastSavedEntry: ScanEntry?

    private let scanService = IngredientScanService()

    var body: some View {
        NavigationStack {
            Form {
                Section("Bild erfassen") {
                    if let selectedImage {
                        Image(uiImage: selectedImage)
                            .resizable()
                            .scaledToFit()
                            .frame(maxHeight: 260)
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                    }

                    Button {
                        isCameraPresented = true
                    } label: {
                        Label("Foto aufnehmen", systemImage: "camera")
                    }
                    .disabled(!UIImagePickerController.isSourceTypeAvailable(.camera))

                    PhotosPicker(selection: $selectedPhoto, matching: .images) {
                        Label("Bild auswählen", systemImage: "photo.on.rectangle")
                    }
                }

                if isScanning {
                    Section {
                        HStack {
                            ProgressView()
                            Text("Bild wird gelesen und gespeichert…")
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                if let scanError {
                    Section {
                        Text(scanError)
                            .foregroundStyle(.red)
                    }
                }

                if let lastSavedEntry {
                    Section("Weiter prüfen") {
                        Label("Scan gespeichert", systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.green)

                        Button {
                            selectedAdditiveScan = lastSavedEntry
                            selectedTab = .additives
                        } label: {
                            Label("Zu Zusatzstoffe", systemImage: "list.bullet.rectangle")
                        }

                        Button {
                            selectedLabelingScan = lastSavedEntry
                            selectedTab = .labeling
                        } label: {
                            Label("Zur Kennzeichnung", systemImage: "tag.circle")
                        }

                        Text("Der Scan ist in beiden Reitern in der Historie verfügbar.")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        if !lastSavedEntry.ocrText.isEmpty {
                            DisclosureGroup("Erkannter Text (\(lastSavedEntry.ocrText.count) Zeichen)") {
                                Text(lastSavedEntry.ocrText)
                                    .font(.footnote)
                                    .textSelection(.enabled)
                            }
                        }
                    }
                } else {
                    Section {
                        Text("Hier wird nur das Bild erfasst. Die Auswertung erfolgt danach in den Reitern Zusatzstoffe oder Kennzeichnung.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle("Scan")
            .onChange(of: selectedPhoto) { _, item in
                Task { await loadPhoto(item) }
            }
            .onChange(of: selectedImage) { _, image in
                guard let image else { return }
                Task { await scan(image) }
            }
            .sheet(isPresented: $isCameraPresented) {
                CameraPicker(image: $selectedImage)
                    .ignoresSafeArea()
            }
        }
    }

    private func loadPhoto(_ item: PhotosPickerItem?) async {
        guard let item else { return }
        do {
            guard let data = try await item.loadTransferable(type: Data.self),
                  let image = UIImage(data: data) else {
                scanError = "Das Bild konnte nicht geladen werden."
                return
            }
            selectedImage = image
        } catch {
            scanError = "Bildauswahl fehlgeschlagen: \(error.localizedDescription)"
        }
    }

    private func scan(_ image: UIImage) async {
        isScanning = true
        scanError = nil
        recognizedText = ""
        lastSavedEntry = nil
        defer { isScanning = false }

        do {
            let text = try await scanService.recognizeText(in: image)
            recognizedText = text
            lastSavedEntry = scanHistory.add(ocrText: text, thumbnail: image)
        } catch {
            scanError = "Texterkennung fehlgeschlagen: \(error.localizedDescription)"
        }
    }
}

struct ScanEntry: Identifiable, Codable, Hashable {
    let id: UUID
    let timestamp: Date
    let ocrText: String
    let thumbnailFileName: String?

    var ocrSnippet: String {
        String(ocrText.prefix(200))
    }

    init(id: UUID = UUID(), timestamp: Date = Date(), ocrText: String, thumbnailFileName: String?) {
        self.id = id
        self.timestamp = timestamp
        self.ocrText = ocrText
        self.thumbnailFileName = thumbnailFileName
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(UUID.self, forKey: .id) ?? UUID()
        timestamp = try container.decodeIfPresent(Date.self, forKey: .timestamp) ?? Date()
        ocrText = try container.decodeIfPresent(String.self, forKey: .ocrText)
            ?? container.decodeIfPresent(String.self, forKey: .legacyOCRSnippet)
            ?? ""
        thumbnailFileName = try container.decodeIfPresent(String.self, forKey: .thumbnailFileName)
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(timestamp, forKey: .timestamp)
        try container.encode(ocrText, forKey: .ocrText)
        try container.encodeIfPresent(thumbnailFileName, forKey: .thumbnailFileName)
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case timestamp
        case ocrText
        case thumbnailFileName
        case legacyOCRSnippet = "ocrSnippet"
    }
}

@MainActor
final class ScanHistoryService: ObservableObject {
    @Published private(set) var entries: [ScanEntry] = []

    private let maxEntries = 30
    private let historyURL: URL
    private let thumbnailDir: URL

    init() {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("LAVES")
        historyURL = base.appendingPathComponent("scan_history.json")
        thumbnailDir = base.appendingPathComponent("thumbnails")
        load()
    }

    @discardableResult
    func add(ocrText: String, thumbnail: UIImage?) -> ScanEntry {
        var thumbnailFileName: String? = nil
        if let thumbnail, let data = thumbnail.jpegData(compressionQuality: 0.62) {
            let fileName = "\(UUID().uuidString).jpg"
            let url = thumbnailDir.appendingPathComponent(fileName)
            try? FileManager.default.createDirectory(at: thumbnailDir, withIntermediateDirectories: true)
            if (try? data.write(to: url)) != nil {
                thumbnailFileName = fileName
            }
        }

        let entry = ScanEntry(
            id: UUID(),
            timestamp: Date(),
            ocrText: ocrText,
            thumbnailFileName: thumbnailFileName
        )
        entries.insert(entry, at: 0)
        trimIfNeeded()
        save()
        return entry
    }

    func delete(at offsets: IndexSet) {
        for idx in offsets {
            removeThumbnail(for: entries[idx])
        }
        entries.remove(atOffsets: offsets)
        save()
    }

    func thumbnail(for entry: ScanEntry) -> UIImage? {
        guard let fn = entry.thumbnailFileName else { return nil }
        guard let data = try? Data(contentsOf: thumbnailDir.appendingPathComponent(fn)) else { return nil }
        return UIImage(data: data)
    }

    private func trimIfNeeded() {
        guard entries.count > maxEntries else { return }
        let removed = entries.suffix(from: maxEntries)
        for old in removed {
            removeThumbnail(for: old)
        }
        entries = Array(entries.prefix(maxEntries))
    }

    private func removeThumbnail(for entry: ScanEntry) {
        if let fn = entry.thumbnailFileName {
            try? FileManager.default.removeItem(at: thumbnailDir.appendingPathComponent(fn))
        }
    }

    private func load() {
        guard let data = try? Data(contentsOf: historyURL),
              let decoded = try? JSONDecoder().decode([ScanEntry].self, from: data) else { return }
        entries = decoded
    }

    private func save() {
        let dir = historyURL.deletingLastPathComponent()
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try? JSONEncoder().encode(entries).write(to: historyURL)
    }
}

struct ScanHistoryPickerView<Destination: View>: View {
    @ObservedObject var service: ScanHistoryService
    let title: String
    let destination: (ScanEntry) -> Destination

    var body: some View {
        List {
            if service.entries.isEmpty {
                ContentUnavailableView(
                    "Keine Scans",
                    systemImage: "clock.arrow.circlepath",
                    description: Text("Scans werden nach dem Erfassen im Scan-Reiter hier angezeigt.")
                )
            } else {
                ForEach(service.entries) { entry in
                    NavigationLink {
                        destination(entry)
                    } label: {
                        ScanEntryRow(entry: entry, thumbnail: service.thumbnail(for: entry))
                    }
                }
                .onDelete { service.delete(at: $0) }
            }
        }
        .navigationTitle(title)
    }
}

struct ScanEntryRow: View {
    let entry: ScanEntry
    let thumbnail: UIImage?

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Group {
                if let img = thumbnail {
                    Image(uiImage: img)
                        .resizable()
                        .scaledToFill()
                } else {
                    Color.secondary.opacity(0.15)
                        .overlay {
                            Image(systemName: "photo")
                                .foregroundStyle(.secondary)
                        }
                }
            }
            .frame(width: 58, height: 58)
            .clipShape(RoundedRectangle(cornerRadius: 8))

            VStack(alignment: .leading, spacing: 4) {
                Text(entry.timestamp.formatted(date: .abbreviated, time: .shortened))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(entry.ocrSnippet.isEmpty ? "Kein OCR-Text" : entry.ocrSnippet)
                    .font(.subheadline)
                    .lineLimit(3)
            }
            .padding(.vertical, 2)
        }
    }
}

struct AdditiveScanResultView: View {
    let entry: ScanEntry
    @ObservedObject var store: AdditiveStore
    @ObservedObject var scanHistory: ScanHistoryService

    @State private var selectedMatch: AdditiveMatch?
    private let scanService = IngredientScanService()

    private var detectedAnimals: [DetectedAnimal] {
        scanService.detectedAnimals(in: entry.ocrText)
    }

    private var matches: [AdditiveMatch] {
        scanService.matchAdditives(in: entry.ocrText, additives: store.additives)
    }

    var body: some View {
        List {
            Section("Bild") {
                if let image = scanHistory.thumbnail(for: entry) {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFit()
                        .frame(maxHeight: 220)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                }
                LabeledContent("Scan", value: entry.timestamp.formatted(date: .abbreviated, time: .shortened))
            }

            Section("Erkannte Tierart") {
                if detectedAnimals.isEmpty {
                    Text("Keine Tierart erkannt")
                        .foregroundStyle(.secondary)
                } else {
                    Text(detectedAnimals.map(\.label).joined(separator: ", "))
                }
            }

            Section("Gefundene Zusatzstoffe") {
                if matches.isEmpty {
                    Text("Keine E-Nummern oder Stoffnamen erkannt.")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(matches) { match in
                        Button {
                            selectedMatch = match
                        } label: {
                            VStack(alignment: .leading, spacing: 6) {
                                Text(match.additive.displayTitle)
                                    .font(.headline)
                                    .foregroundStyle(.primary)
                                Text("Erkannt: \(match.matchedText)")
                                    .foregroundStyle(.secondary)
                                Text("Tierarten: \(match.additive.normalizedSpecies)")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }
            }

            Section("Gelesener Text") {
                Text(entry.ocrText)
                    .font(.footnote)
                    .textSelection(.enabled)
            }
        }
        .navigationTitle("Scan-Auswertung")
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $selectedMatch) { match in
            AdditiveDetailSheet(additive: match.additive)
        }
    }
}

struct AdditiveDetailSheet: View {
    let additive: Additive
    @Environment(\.dismiss) private var dismiss
    @State private var valueText = ""
    @State private var result: EvaluationResult?

    var body: some View {
        NavigationStack {
            Form {
                Section("Zusatzstoff") {
                    LabeledContent("Kennnummer", value: additive.eNumber)
                    LabeledContent("Name", value: additive.name)
                    LabeledContent("Tierarten", value: additive.normalizedSpecies)
                    if let regulation = additive.regulation, !regulation.isEmpty {
                        LabeledContent("Rechtsgrundlage", value: regulation)
                    }
                    if let sourceFile = additive.sourceFile {
                        let page = additive.sourcePage.map { ":S.\($0)" } ?? ""
                        LabeledContent("Quelle", value: "\(sourceFile)\(page)")
                    }
                }

                Section("Grenzwerte") {
                    let unit = additive.unit ?? "mg/kg"
                    if let min = additive.minMgKg {
                        LabeledContent("Mindestwert", value: "\(min.formatted(.number.precision(.fractionLength(0...3)))) \(unit)")
                    }
                    if let max = additive.maxMgKg {
                        LabeledContent("Höchstwert", value: "\(max.formatted(.number.precision(.fractionLength(0...3)))) \(unit)")
                    }
                    if additive.minMgKg == nil && additive.maxMgKg == nil {
                        Text("Keine Grenzwerte hinterlegt")
                            .foregroundStyle(.secondary)
                    }
                }

                Section("Schnellprüfung") {
                    TextField("Laborwert \(additive.unit ?? "mg/kg")", text: $valueText)
                        .keyboardType(.decimalPad)
                    Button("Prüfen") {
                        guard let v = Double(valueText.replacingOccurrences(of: ",", with: ".")) else { return }
                        result = EvaluationService.evaluate(value: v, additive: additive)
                    }
                    .disabled(Double(valueText.replacingOccurrences(of: ",", with: ".")) == nil)
                }

                if let result {
                    ResultSection(result: result)
                }
            }
            .navigationTitle(additive.displayTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Fertig") { dismiss() }
                }
            }
        }
    }
}

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
