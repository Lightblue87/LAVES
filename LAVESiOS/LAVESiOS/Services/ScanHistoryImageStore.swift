import Foundation
import UIKit

final class ScanHistoryImageStore {
    let thumbnailDir: URL
    private let thumbnailCache = NSCache<NSString, UIImage>()
    private let fileManager: FileManager

    init(thumbnailDir: URL, fileManager: FileManager = .default) {
        self.thumbnailDir = thumbnailDir
        self.fileManager = fileManager
        thumbnailCache.countLimit = 80
    }

    func store(thumbnail: UIImage, settings: ScanHistorySettings) -> String? {
        let storedImage = settings.storeThumbnailsOnly ? thumbnail.lavesResized(maxDimension: 900) : thumbnail
        let compression: CGFloat = settings.compressImages ? 0.62 : 0.86
        guard let data = storedImage.jpegData(compressionQuality: compression) else { return nil }

        let fileName = "\(UUID().uuidString).jpg"
        let url = thumbnailDir.appendingPathComponent(fileName)
        try? fileManager.createDirectory(at: thumbnailDir, withIntermediateDirectories: true)
        guard (try? data.write(to: url)) != nil else { return nil }
        return fileName
    }

    func image(fileName: String?) -> UIImage? {
        guard let fileName else { return nil }
        if let cached = thumbnailCache.object(forKey: fileName as NSString) {
            return cached
        }
        let url = thumbnailDir.appendingPathComponent(fileName)
        guard let data = try? Data(contentsOf: url),
              let image = UIImage(data: data) else {
            return nil
        }
        thumbnailCache.setObject(image, forKey: fileName as NSString)
        return image
    }

    func remove(fileName: String?) {
        guard let fileName else { return }
        try? fileManager.removeItem(at: thumbnailDir.appendingPathComponent(fileName))
        thumbnailCache.removeObject(forKey: fileName as NSString)
    }

    func remove(fileNames: [String]) {
        for fileName in fileNames {
            remove(fileName: fileName)
        }
    }

    func removeOrphans(referencedFileNames: Set<String>) -> Int {
        guard let files = imageFiles() else { return 0 }
        var removed = 0
        for file in files where !referencedFileNames.contains(file.lastPathComponent) {
            try? fileManager.removeItem(at: file)
            thumbnailCache.removeObject(forKey: file.lastPathComponent as NSString)
            removed += 1
        }
        return removed
    }

    func stats(for entries: [ScanEntry]) -> ScanHistoryStats {
        let referenced = Set(entries.flatMap(\.allThumbnailFileNames))
        let files = imageFiles() ?? []
        let totalBytes = files.reduce(Int64(0)) { partial, url in
            partial + fileSize(url)
        }
        let existingImageNames = Set(files.map(\.lastPathComponent))

        return ScanHistoryStats(
            entryCount: entries.count,
            imageCount: files.count,
            totalBytes: totalBytes,
            orphanImageCount: files.filter { !referenced.contains($0.lastPathComponent) }.count,
            missingImageCount: referenced.filter { !existingImageNames.contains($0) }.count
        )
    }

    func totalImageBytes() -> Int64 {
        (imageFiles() ?? []).reduce(Int64(0)) { $0 + fileSize($1) }
    }

    func imageSize(fileName: String?) -> Int64 {
        guard let fileName else { return 0 }
        return fileSize(thumbnailDir.appendingPathComponent(fileName))
    }

    private func imageFiles() -> [URL]? {
        try? fileManager.contentsOfDirectory(
            at: thumbnailDir,
            includingPropertiesForKeys: [.fileSizeKey]
        )
    }

    private func fileSize(_ url: URL) -> Int64 {
        let values = try? url.resourceValues(forKeys: [.fileSizeKey])
        return Int64(values?.fileSize ?? 0)
    }
}

private extension UIImage {
    func lavesResized(maxDimension: CGFloat) -> UIImage {
        let longest = max(size.width, size.height)
        guard longest > maxDimension else { return self }

        let scale = maxDimension / longest
        let targetSize = CGSize(width: size.width * scale, height: size.height * scale)
        let renderer = UIGraphicsImageRenderer(size: targetSize)
        return renderer.image { _ in
            draw(in: CGRect(origin: .zero, size: targetSize))
        }
    }
}
