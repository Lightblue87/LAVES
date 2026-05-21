import PhotosUI
import SwiftUI
import UIKit

struct IngredientScanView: View {
    @ObservedObject var store: AdditiveStore

    @State private var selectedPhoto: PhotosPickerItem?
    @State private var selectedImage: UIImage?
    @State private var recognizedText = ""
    @State private var detectedAnimals: [DetectedAnimal] = []
    @State private var matches: [AdditiveMatch] = []
    @State private var isScanning = false
    @State private var scanError: String?
    @State private var isCameraPresented = false
    @State private var selectedMatch: AdditiveMatch?

    private let scanService = IngredientScanService()

    var body: some View {
        NavigationStack {
            Form {
                Section("Bild") {
                    if let selectedImage {
                        Image(uiImage: selectedImage)
                            .resizable()
                            .scaledToFit()
                            .frame(maxHeight: 220)
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

                if let scanError {
                    Section {
                        Text(scanError)
                            .foregroundStyle(.red)
                    }
                }

                if !recognizedText.isEmpty {
                    Section("Erkannte Tierart") {
                        if detectedAnimals.isEmpty {
                            Text("Keine Tierart erkannt")
                                .foregroundStyle(.secondary)
                        } else {
                            Text(detectedAnimals.map(\.label).joined(separator: ", "))
                        }
                    }
                }

                Section("Gefundene Einträge") {
                    if isScanning {
                        ProgressView("Bild wird gelesen")
                    } else if matches.isEmpty {
                        if recognizedText.isEmpty {
                            Text("Noch kein Bild ausgewertet.")
                                .foregroundStyle(.secondary)
                        } else {
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Keine E-Nummern oder Stoffnamen erkannt.")
                                    .foregroundStyle(.secondary)
                                Text("Für eine Prüfung müssen konkrete Zusatzstoffangaben (z. B. E-Nummern) auf dem Etikett stehen.")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    } else {
                        ForEach(matches) { match in
                            Button {
                                selectedMatch = match
                            } label: {
                                HStack {
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
                                    Spacer()
                                    Image(systemName: "chevron.right")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            .padding(.vertical, 4)
                        }
                    }
                }

                if !recognizedText.isEmpty {
                    Section("Gelesener Text") {
                        Text(recognizedText)
                            .font(.footnote)
                            .textSelection(.enabled)
                    }
                }
            }
            .navigationTitle("Scan")
            .onChange(of: selectedPhoto) { _, item in
                Task {
                    await loadPhoto(item)
                }
            }
            .sheet(isPresented: $isCameraPresented) {
                CameraPicker(image: $selectedImage)
                    .ignoresSafeArea()
            }
            .sheet(item: $selectedMatch) { match in
                AdditiveDetailSheet(additive: match.additive)
            }
            .onChange(of: selectedImage) { _, image in
                guard let image else { return }
                Task {
                    await scan(image)
                }
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
        detectedAnimals = []
        matches = []
        defer { isScanning = false }

        do {
            let text = try await scanService.recognizeText(in: image)
            recognizedText = text
            detectedAnimals = scanService.detectedAnimals(in: text)
            matches = scanService.matchAdditives(in: text, additives: store.additives)
        } catch {
            scanError = "Texterkennung fehlgeschlagen: \(error.localizedDescription)"
        }
    }
}

private struct AdditiveDetailSheet: View {
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

private struct CameraPicker: UIViewControllerRepresentable {
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
