import Foundation

/// Within-container path migration from the legacy "LAVES" storage paths to
/// the "FeedLabelCheck" paths.  Called early in ScanHistoryService.init() and
/// AdditiveStore.dataDirectory so whichever initialises first does the work;
/// subsequent calls are no-ops.
///
/// **Scope**: This migrates paths *within* the app's own sandbox container.
/// It only fires when a build under the **same bundle identifier** previously
/// wrote data to the old "LAVES/" directory name (e.g. during the development
/// transition period or if the bundle ID is reverted to the pre-rename value
/// `de.lightblue87.laves`).
///
/// **Limitation**: iOS assigns each bundle identifier its own isolated
/// container directory.  Changing `PRODUCT_BUNDLE_IDENTIFIER` from
/// `de.lightblue87.laves` to `com.lightblue.feedlabelcheck` causes the OS to
/// create a fresh container for the new app.  Production users upgrading from
/// the old bundle ID will start from an empty container; this migration is a
/// no-op for them because the "LAVES/" directory never exists in the new
/// container.  Cross-bundle-ID migration on iOS is only possible via a shared
/// App Group entitlement configured in both the old and new app.
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
