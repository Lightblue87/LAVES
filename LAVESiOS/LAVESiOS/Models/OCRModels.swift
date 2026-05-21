import Foundation

// MARK: - Image Type

enum OCRImageType: String, Codable, CaseIterable, Identifiable {
    case vorderseite
    case rueckseite
    case boden
    case deckel
    case seitenflaeche
    case detailaufnahme

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .vorderseite:    return "Vorderseite"
        case .rueckseite:     return "Rückseite"
        case .boden:          return "Boden"
        case .deckel:         return "Deckel"
        case .seitenflaeche:  return "Seitenfläche"
        case .detailaufnahme: return "Detailaufnahme"
        }
    }

    var systemImage: String {
        switch self {
        case .vorderseite:    return "rectangle.portrait"
        case .rueckseite:     return "rectangle.portrait.rotate"
        case .boden:          return "square.bottomhalf.filled"
        case .deckel:         return "square.tophalf.filled"
        case .seitenflaeche:  return "rectangle.landscape.rotate"
        case .detailaufnahme: return "viewfinder.circle"
        }
    }

    /// Suggested default type for the Nth image added to a session.
    static func suggestedType(forIndex index: Int) -> OCRImageType {
        switch index {
        case 0: return .vorderseite
        case 1: return .rueckseite
        case 2: return .boden
        case 3: return .deckel
        default: return .detailaufnahme
        }
    }
}

// MARK: - OCR Image Item (Codable, stored in ScanEntry and LabelingCheckResult)

struct OCRImageItem: Identifiable, Codable, Hashable {
    let id: UUID
    var imageType: OCRImageType
    /// File name within ScanHistoryImageStore. Nil when thumbnail was deleted or not yet persisted.
    let thumbnailFileName: String?
    /// OCR text extracted from this image alone.
    let ocrText: String
    let capturedAt: Date

    init(
        id: UUID = UUID(),
        imageType: OCRImageType,
        thumbnailFileName: String?,
        ocrText: String,
        capturedAt: Date = Date()
    ) {
        self.id = id
        self.imageType = imageType
        self.thumbnailFileName = thumbnailFileName
        self.ocrText = ocrText
        self.capturedAt = capturedAt
    }
}
