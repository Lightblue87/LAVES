import Foundation
import SQLite3

protocol LabelingRuleRepository {
    func loadFeedTypes(from url: URL) throws -> [LabelingFeedType]
    func loadRules(from url: URL, forFeedType feedTypeId: String) throws -> [LabelingRule]
    func loadDatabaseInfo(from url: URL) throws -> LabelingDatabaseInfo
    func loadFeedMaterials(from url: URL) throws -> [FeedMaterial]
    func loadDlgFeedMaterials(from url: URL) throws -> [DlgFeedMaterial]
}

struct SQLiteLabelingRuleRepository: LabelingRuleRepository {

    func loadFeedTypes(from url: URL) throws -> [LabelingFeedType] {
        let db = try openReadonly(url)
        defer { sqlite3_close(db) }

        let sql = "SELECT id, name_de, description_de, keywords_de FROM labeling_feed_types ORDER BY id"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
            throw LabelingRepositoryError.queryFailed(errorMessage(db))
        }
        defer { sqlite3_finalize(stmt) }

        var result: [LabelingFeedType] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            let id = text(stmt, 0) ?? ""
            let name = text(stmt, 1) ?? id
            let desc = text(stmt, 2)
            let keywords = (text(stmt, 3) ?? "")
                .split(separator: ",")
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }
            result.append(LabelingFeedType(id: id, nameDe: name, descriptionDe: desc, keywordsDe: keywords))
        }
        return result
    }

    func loadRules(from url: URL, forFeedType feedTypeId: String) throws -> [LabelingRule] {
        let db = try openReadonly(url)
        defer { sqlite3_close(db) }

        let sql = """
        SELECT id, regulation_id, feed_type_id, title_de, description_de,
               legal_basis, requirement_type, severity, is_mandatory, display_order
        FROM labeling_rules
        WHERE feed_type_id = 'all' OR feed_type_id = ?
        ORDER BY display_order, id
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
            throw LabelingRepositoryError.queryFailed(errorMessage(db))
        }
        defer { sqlite3_finalize(stmt) }
        sqlite3_bind_text(stmt, 1, (feedTypeId as NSString).utf8String, -1, nil)

        var ruleIds: [String] = []
        var ruleMap: [String: (String, String, String, String, String, String, String, String, Bool, Int)] = [:]

        while sqlite3_step(stmt) == SQLITE_ROW {
            let id = text(stmt, 0) ?? ""
            ruleIds.append(id)
            ruleMap[id] = (
                text(stmt, 1) ?? "",
                text(stmt, 2) ?? "",
                text(stmt, 3) ?? "",
                text(stmt, 4) ?? "",
                text(stmt, 5) ?? "",
                text(stmt, 6) ?? "",
                text(stmt, 7) ?? "info",
                text(stmt, 7) ?? "info",
                sqlite3_column_int(stmt, 8) != 0,
                Int(sqlite3_column_int(stmt, 9))
            )
        }

        guard !ruleIds.isEmpty else { return [] }
        let patterns = try loadPatterns(db: db, ruleIds: ruleIds)

        return ruleIds.compactMap { id in
            guard let t = ruleMap[id] else { return nil }
            let severity = LabelingRuleSeverity(rawValue: t.7) ?? .info
            return LabelingRule(
                id: id, regulationId: t.0, feedTypeId: t.1,
                titleDe: t.2, descriptionDe: t.3, legalBasis: t.4,
                requirementType: t.5, severity: severity,
                isMandatory: t.8, displayOrder: t.9,
                patterns: patterns[id] ?? []
            )
        }
    }

    func loadFeedMaterials(from url: URL) throws -> [FeedMaterial] {
        let db = try openReadonly(url)
        defer { sqlite3_close(db) }

        // Graceful fallback: table may not exist in older DB versions
        guard table("feed_materials", hasColumn: "catalog_number", db: db) else { return [] }

        let sql = """
        SELECT catalog_number, chapter, chapter_name_de, name_de,
               COALESCE(description_de, ''), COALESCE(mandatory_declarations_de, ''),
               COALESCE(restrictions_de, ''), COALESCE(regulation, '68/2013')
        FROM feed_materials
        ORDER BY catalog_number
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
            throw LabelingRepositoryError.queryFailed(errorMessage(db))
        }
        defer { sqlite3_finalize(stmt) }

        var result: [FeedMaterial] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            result.append(FeedMaterial(
                catalogNumber: text(stmt, 0) ?? "",
                chapter: Int(sqlite3_column_int(stmt, 1)),
                chapterNameDe: text(stmt, 2) ?? "",
                nameDe: text(stmt, 3) ?? "",
                descriptionDe: text(stmt, 4) ?? "",
                mandatoryDeclarationsDe: text(stmt, 5) ?? "",
                restrictionsDe: text(stmt, 6) ?? "",
                regulation: text(stmt, 7) ?? "68/2013"
            ))
        }
        return result
    }

    func loadDatabaseInfo(from url: URL) throws -> LabelingDatabaseInfo {
        let db = try openReadonly(url)
        defer { sqlite3_close(db) }

        var meta: [String: String] = [:]
        let sql = "SELECT key, value FROM labeling_metadata"
        var stmt: OpaquePointer?
        if sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK {
            defer { sqlite3_finalize(stmt) }
            while sqlite3_step(stmt) == SQLITE_ROW {
                if let k = text(stmt, 0), let v = text(stmt, 1) { meta[k] = v }
            }
        }

        var ruleCount = 0
        var countStmt: OpaquePointer?
        if sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM labeling_rules", -1, &countStmt, nil) == SQLITE_OK {
            defer { sqlite3_finalize(countStmt) }
            if sqlite3_step(countStmt) == SQLITE_ROW {
                ruleCount = Int(sqlite3_column_int(countStmt, 0))
            }
        }

        return LabelingDatabaseInfo(
            version: meta["labeling_db_version"] ?? "–",
            regulation: meta["labeling_source_regulation"] ?? "VO (EG) Nr. 767/2009",
            celex: meta["labeling_source_celex"] ?? "–",
            versionDate: meta["labeling_source_version_date"] ?? "–",
            createdAt: meta["labeling_created_at"] ?? "–",
            totalRuleCount: ruleCount,
            sha256: meta["labeling_sha256"] ?? "–"
        )
    }

    func loadDlgFeedMaterials(from url: URL) throws -> [DlgFeedMaterial] {
        let db = try openReadonly(url)
        defer { sqlite3_close(db) }

        // Graceful fallback: table may not exist in older DB versions
        guard table("dlg_feed_materials", hasColumn: "number", db: db) else { return [] }

        let sql = """
        SELECT number, group_num, group_name_de, name_de,
               COALESCE(description_de, ''), COALESCE(differentiation_de, ''),
               COALESCE(requirements_de, ''), COALESCE(labeling_de, ''),
               COALESCE(process_de, ''), COALESCE(remarks_de, ''),
               COALESCE(edition, '15')
        FROM dlg_feed_materials
        ORDER BY number
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
            throw LabelingRepositoryError.queryFailed(errorMessage(db))
        }
        defer { sqlite3_finalize(stmt) }

        var result: [DlgFeedMaterial] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            result.append(DlgFeedMaterial(
                number:            text(stmt, 0) ?? "",
                groupNum:          Int(sqlite3_column_int(stmt, 1)),
                groupNameDe:       text(stmt, 2) ?? "",
                nameDe:            text(stmt, 3) ?? "",
                descriptionDe:     text(stmt, 4) ?? "",
                differentiationDe: text(stmt, 5) ?? "",
                requirementsDe:    text(stmt, 6) ?? "",
                labelingDe:        text(stmt, 7) ?? "",
                processDe:         text(stmt, 8) ?? "",
                remarksDe:         text(stmt, 9) ?? "",
                edition:           text(stmt, 10) ?? "15"
            ))
        }
        return result
    }

    // MARK: - Private helpers

    private func loadPatterns(db: OpaquePointer?, ruleIds: [String]) throws -> [String: [LabelingRulePattern]] {
        let placeholders = ruleIds.map { _ in "?" }.joined(separator: ",")
        let hasLanguageColumn = table("labeling_rule_patterns", hasColumn: "pattern_language", db: db)
        let languageColumn = hasLanguageColumn ? "pattern_language" : "'de' AS pattern_language"
        let sql = """
        SELECT id, rule_id, pattern_type, pattern_value, \(languageColumn), confidence_weight, is_negative_pattern
        FROM labeling_rule_patterns
        WHERE rule_id IN (\(placeholders))
        ORDER BY rule_id, is_negative_pattern, pattern_language, confidence_weight DESC
        """
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
            return [:]
        }
        defer { sqlite3_finalize(stmt) }

        for (i, id) in ruleIds.enumerated() {
            sqlite3_bind_text(stmt, Int32(i + 1), (id as NSString).utf8String, -1, nil)
        }

        var result: [String: [LabelingRulePattern]] = [:]
        while sqlite3_step(stmt) == SQLITE_ROW {
            let id = text(stmt, 0) ?? UUID().uuidString
            let ruleId = text(stmt, 1) ?? ""
            let type_ = text(stmt, 2) ?? "keyword"
            let value = text(stmt, 3) ?? ""
            let language = text(stmt, 4) ?? "de"
            let weight = sqlite3_column_double(stmt, 5)
            let isNeg = sqlite3_column_int(stmt, 6) != 0
            let pattern = LabelingRulePattern(
                id: id, ruleId: ruleId, patternType: type_,
                patternValue: value, patternLanguage: language, confidenceWeight: weight,
                isNegativePattern: isNeg
            )
            result[ruleId, default: []].append(pattern)
        }
        return result
    }

    private func table(_ tableName: String, hasColumn columnName: String, db: OpaquePointer?) -> Bool {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, "PRAGMA table_info(\(tableName))", -1, &stmt, nil) == SQLITE_OK else {
            return false
        }
        defer { sqlite3_finalize(stmt) }

        while sqlite3_step(stmt) == SQLITE_ROW {
            if text(stmt, 1) == columnName {
                return true
            }
        }
        return false
    }

    private func openReadonly(_ url: URL) throws -> OpaquePointer? {
        var db: OpaquePointer?
        let flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_URI
        let immutableURI = url.absoluteString + "?immutable=1"

        if sqlite3_open_v2(immutableURI, &db, flags, nil) == SQLITE_OK {
            return db
        }

        let immutableError = errorMessage(db)
        sqlite3_close(db)
        db = nil

        guard sqlite3_open_v2(url.path, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK else {
            let fallbackError = errorMessage(db)
            sqlite3_close(db)
            throw LabelingRepositoryError.openFailed("\(fallbackError) (\(immutableError))")
        }
        return db
    }

    private func text(_ stmt: OpaquePointer?, _ col: Int32) -> String? {
        guard sqlite3_column_type(stmt, col) != SQLITE_NULL,
              let ptr = sqlite3_column_text(stmt, col) else { return nil }
        return String(cString: ptr)
    }

    private func errorMessage(_ db: OpaquePointer?) -> String {
        guard let ptr = sqlite3_errmsg(db) else { return "Unbekannter SQLite-Fehler." }
        return String(cString: ptr)
    }
}

enum LabelingRepositoryError: LocalizedError {
    case openFailed(String)
    case queryFailed(String)

    var errorDescription: String? {
        switch self {
        case .openFailed(let m): return "Kennzeichnungs-Datenbank konnte nicht geöffnet werden: \(m)"
        case .queryFailed(let m): return "Datenbankabfrage fehlgeschlagen: \(m)"
        }
    }
}
