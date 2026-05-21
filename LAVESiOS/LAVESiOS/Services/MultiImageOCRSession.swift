import Foundation
import UIKit

// MARK: - Session Image (in-memory, not yet persisted)

/// A single scanned image held in an active multi-image session.
/// The `image` may be nil when the session was restored from history
/// and the thumbnail file was previously deleted.
struct SessionImage: Identifiable {
    let id: UUID
    var imageType: OCRImageType
    /// Live UIImage — nil when loaded from history without a saved thumbnail.
    let image: UIImage?
    let ocrText: String
    let capturedAt: Date

    init(
        id: UUID = UUID(),
        imageType: OCRImageType,
        image: UIImage?,
        ocrText: String,
        capturedAt: Date = Date()
    ) {
        self.id = id
        self.imageType = imageType
        self.image = image
        self.ocrText = ocrText
        self.capturedAt = capturedAt
    }

    func withType(_ newType: OCRImageType) -> SessionImage {
        SessionImage(id: id, imageType: newType, image: image, ocrText: ocrText, capturedAt: capturedAt)
    }
}

// MARK: - Multi-Image OCR Session

/// Manages an active multi-image OCR labeling session.
/// Images are held in memory; they are persisted to `ScanHistoryService` on demand.
@MainActor
final class MultiImageOCRSession: ObservableObject {

    static let maxImages = 5

    @Published private(set) var images: [SessionImage] = []
    @Published private(set) var isScanning = false
    @Published var scanError: String?

    private let scanService = IngredientScanService()

    // MARK: - Computed

    var canAddMore: Bool { images.count < Self.maxImages }
    var isEmpty: Bool { images.isEmpty }
    var imageCount: Int { images.count }
    var coveredImageTypes: Set<OCRImageType> { Set(images.map(\.imageType)) }

    var mergedOCRText: String {
        OCRDocumentAssembler.merge(images.map { ($0.imageType, $0.ocrText) })
    }

    // MARK: - Session management

    /// Adds a new image to the session: runs OCR and appends the result.
    func addImage(_ image: UIImage, type: OCRImageType) async {
        guard canAddMore else { return }
        isScanning = true
        scanError = nil
        defer { isScanning = false }
        do {
            let text = try await scanService.recognizeText(in: image)
            images.append(SessionImage(imageType: type, image: image, ocrText: text))
        } catch {
            scanError = "Texterkennung fehlgeschlagen: \(error.localizedDescription)"
        }
    }

    /// Removes an image from the session.
    func remove(_ sessionImage: SessionImage) {
        images.removeAll { $0.id == sessionImage.id }
    }

    /// Changes the image type label of a session image.
    func updateType(for sessionImage: SessionImage, to newType: OCRImageType) {
        guard let idx = images.firstIndex(where: { $0.id == sessionImage.id }) else { return }
        images[idx] = sessionImage.withType(newType)
    }

    /// Replaces the image content (re-runs OCR) while keeping the same position and type.
    func replaceImage(for sessionImage: SessionImage, with newImage: UIImage) async {
        guard let idx = images.firstIndex(where: { $0.id == sessionImage.id }) else { return }
        isScanning = true
        scanError = nil
        defer { isScanning = false }
        do {
            let text = try await scanService.recognizeText(in: newImage)
            images[idx] = SessionImage(
                id: sessionImage.id,
                imageType: sessionImage.imageType,
                image: newImage,
                ocrText: text,
                capturedAt: Date()
            )
        } catch {
            scanError = "Texterkennung fehlgeschlagen: \(error.localizedDescription)"
        }
    }

    /// Resets the session to an empty state.
    func reset() {
        images = []
        scanError = nil
    }

    // MARK: - History integration

    /// Populates the session from a historical `ScanEntry`.
    /// Multi-image entries restore all per-image data; legacy single-image entries
    /// are represented as a single Vorderseite image.
    func loadFromEntry(_ entry: ScanEntry, imageStore: ScanHistoryImageStore) {
        if let items = entry.imageItems, !items.isEmpty {
            images = items.map { item in
                let img = imageStore.image(fileName: item.thumbnailFileName)
                return SessionImage(
                    id: item.id,
                    imageType: item.imageType,
                    image: img,
                    ocrText: item.ocrText,
                    capturedAt: item.capturedAt
                )
            }
        } else {
            // Legacy single-image entry
            let img = imageStore.image(fileName: entry.thumbnailFileName)
            images = [
                SessionImage(
                    imageType: .vorderseite,
                    image: img,
                    ocrText: entry.ocrText,
                    capturedAt: entry.timestamp
                )
            ]
        }
        scanError = nil
    }

    /// Converts the current session to `OCRImageItem` records suitable for persistence.
    /// The `thumbnailFileName` is set by the caller after storage.
    func makeOCRImageItems(thumbnailFileNames: [UUID: String]) -> [OCRImageItem] {
        images.map { img in
            OCRImageItem(
                id: img.id,
                imageType: img.imageType,
                thumbnailFileName: thumbnailFileNames[img.id],
                ocrText: img.ocrText,
                capturedAt: img.capturedAt
            )
        }
    }
}
