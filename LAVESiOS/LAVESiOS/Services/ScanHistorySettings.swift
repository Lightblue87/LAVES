import Foundation

struct ScanEntry: Identifiable, Codable, Hashable {
    let id: UUID
    let timestamp: Date
    let ocrText: String
    let thumbnailFileName: String?
    var isPinned: Bool
    var note: String?

    var ocrSnippet: String {
        String(ocrText.prefix(200))
    }

    init(
        id: UUID = UUID(),
        timestamp: Date = Date(),
        ocrText: String,
        thumbnailFileName: String?,
        isPinned: Bool = false,
        note: String? = nil
    ) {
        self.id = id
        self.timestamp = timestamp
        self.ocrText = ocrText
        self.thumbnailFileName = thumbnailFileName
        self.isPinned = isPinned
        self.note = note
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(UUID.self, forKey: .id) ?? UUID()
        timestamp = try container.decodeIfPresent(Date.self, forKey: .timestamp) ?? Date()
        ocrText = try container.decodeIfPresent(String.self, forKey: .ocrText)
            ?? container.decodeIfPresent(String.self, forKey: .legacyOCRSnippet)
            ?? ""
        thumbnailFileName = try container.decodeIfPresent(String.self, forKey: .thumbnailFileName)
        isPinned = try container.decodeIfPresent(Bool.self, forKey: .isPinned) ?? false
        note = try container.decodeIfPresent(String.self, forKey: .note)
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encode(timestamp, forKey: .timestamp)
        try container.encode(ocrText, forKey: .ocrText)
        try container.encodeIfPresent(thumbnailFileName, forKey: .thumbnailFileName)
        try container.encode(isPinned, forKey: .isPinned)
        try container.encodeIfPresent(note, forKey: .note)
    }

    private enum CodingKeys: String, CodingKey {
        case id
        case timestamp
        case ocrText
        case thumbnailFileName
        case isPinned
        case note
        case legacyOCRSnippet = "ocrSnippet"
    }
}

struct ScanHistorySettings: Codable, Equatable {
    var isHistoryEnabled: Bool = true
    var maxEntries: ScanHistoryEntryLimit = .oneHundred
    var maxAge: ScanHistoryAgeLimit = .ninetyDays
    var storageLimit: ScanHistoryStorageLimit = .mb250
    var compressImages: Bool = true
    var storeThumbnailsOnly: Bool = true
    var keepOCRTextWhenDeletingImages: Bool = true
}

enum ScanHistoryEntryLimit: String, Codable, CaseIterable, Identifiable {
    case fifty
    case oneHundred
    case twoHundredFifty
    case unlimited

    var id: String { rawValue }

    var count: Int? {
        switch self {
        case .fifty: return 50
        case .oneHundred: return 100
        case .twoHundredFifty: return 250
        case .unlimited: return nil
        }
    }

    var title: String {
        switch self {
        case .fifty: return "50"
        case .oneHundred: return "100"
        case .twoHundredFifty: return "250"
        case .unlimited: return "Unbegrenzt"
        }
    }
}

enum ScanHistoryAgeLimit: String, Codable, CaseIterable, Identifiable {
    case sevenDays
    case thirtyDays
    case ninetyDays
    case oneYear
    case unlimited

    var id: String { rawValue }

    var interval: TimeInterval? {
        switch self {
        case .sevenDays: return 7 * 24 * 60 * 60
        case .thirtyDays: return 30 * 24 * 60 * 60
        case .ninetyDays: return 90 * 24 * 60 * 60
        case .oneYear: return 365 * 24 * 60 * 60
        case .unlimited: return nil
        }
    }

    var title: String {
        switch self {
        case .sevenDays: return "7 Tage"
        case .thirtyDays: return "30 Tage"
        case .ninetyDays: return "90 Tage"
        case .oneYear: return "1 Jahr"
        case .unlimited: return "Unbegrenzt"
        }
    }
}

enum ScanHistoryStorageLimit: String, Codable, CaseIterable, Identifiable {
    case mb100
    case mb250
    case mb500
    case unlimited

    var id: String { rawValue }

    var bytes: Int64? {
        switch self {
        case .mb100: return 100 * 1_024 * 1_024
        case .mb250: return 250 * 1_024 * 1_024
        case .mb500: return 500 * 1_024 * 1_024
        case .unlimited: return nil
        }
    }

    var title: String {
        switch self {
        case .mb100: return "100 MB"
        case .mb250: return "250 MB"
        case .mb500: return "500 MB"
        case .unlimited: return "Unbegrenzt"
        }
    }
}
