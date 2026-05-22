import Foundation

/// One-time data migration from the legacy "LAVES" storage directory to
/// "FeedLabelCheck". Called early in both ScanHistoryService.init() and
/// AdditiveStore.dataDirectory so whichever initialises first performs the
/// migration; subsequent calls are no-ops.
///
/// Migration steps
/// 1. Move ApplicationSupport/LAVES/ → ApplicationSupport/FeedLabelCheck/
/// 2. Within FeedLabelCheck/ rename the individual SQLite cache files that
///    were renamed as part of the app rebrand.
///
/// Only runs when the old directory exists and the new one does NOT yet exist,
/// so it is safe to call from multiple code paths.
enum StorageMigration {
    static func migrateIfNeeded(base appSupport: URL) {
        let fm = FileManager.default
        let oldDir = appSupport.appendingPathComponent("LAVES")
        let newDir = appSupport.appendingPathComponent("FeedLabelCheck")

        // Step 1 — move the directory
        if fm.fileExists(atPath: oldDir.path), !fm.fileExists(atPath: newDir.path) {
            try? fm.moveItem(at: oldDir, to: newDir)
        }

        // Step 2 — rename individual files that changed name during rebrand
        let fileRenames: [(String, String)] = [
            ("laves.sqlite",          "feedlabelcheck.sqlite"),
            ("laves_labeling.sqlite", "labeling.sqlite"),
        ]
        for (oldName, newName) in fileRenames {
            let oldFile = newDir.appendingPathComponent(oldName)
            let newFile = newDir.appendingPathComponent(newName)
            if fm.fileExists(atPath: oldFile.path), !fm.fileExists(atPath: newFile.path) {
                try? fm.moveItem(at: oldFile, to: newFile)
            }
        }
    }
}
