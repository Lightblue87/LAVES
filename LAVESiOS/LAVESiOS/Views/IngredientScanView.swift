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
