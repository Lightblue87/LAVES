import Foundation
import SQLite3

struct SQLiteAdditiveRepository {
    func loadAdditives(from databaseURL: URL) throws -> [Additive] {
        let database = try openReadonly(databaseURL)
        defer { sqlite3_close(database) }

        // Use null placeholder when the einheit column doesn't exist yet (older DB schema)
        let einheitExpr = hasColumn("einheit", in: "additives", database: database) ? "einheit" : "null"
        let query = """
        SELECT kennnummer, name, tierarten, hoechstalter_tage, min_mg_kg, max_mg_kg,
               \(einheitExpr), rechtsgrundlage, source_file, source_page, tierart_kategorie
        FROM additives
        ORDER BY kennnummer, name, tierarten
        """

        var statement: OpaquePointer?
        guard sqlite3_prepare_v2(database, query, -1, &statement, nil) == SQLITE_OK else {
            throw SQLiteRepositoryError.queryFailed(message: errorMessage(database))
        }
        defer { sqlite3_finalize(statement) }

        var additives: [Additive] = []
        while sqlite3_step(statement) == SQLITE_ROW {
            additives.append(
                Additive(
                    eNumber: string(statement, 0) ?? "",
                    name: string(statement, 1) ?? "",
                    species: string(statement, 2) ?? "Alle Tierarten",
                    maxAgeDays: double(statement, 3),
                    minMgKg: double(statement, 4),
                    maxMgKg: double(statement, 5),
                    unit: string(statement, 6),
                    regulation: string(statement, 7),
                    sourceFile: string(statement, 8),
                    sourcePage: int(statement, 9),
                    animalCategory: string(statement, 10)
                )
            )
        }

        return additives
    }

    private func string(_ statement: OpaquePointer?, _ index: Int32) -> String? {
        guard sqlite3_column_type(statement, index) != SQLITE_NULL,
              let text = sqlite3_column_text(statement, index) else {
            return nil
        }
        return String(cString: text)
    }

    private func double(_ statement: OpaquePointer?, _ index: Int32) -> Double? {
        guard sqlite3_column_type(statement, index) != SQLITE_NULL else {
            return nil
        }
        return sqlite3_column_double(statement, index)
    }

    private func int(_ statement: OpaquePointer?, _ index: Int32) -> Int? {
        guard sqlite3_column_type(statement, index) != SQLITE_NULL else {
            return nil
        }
        return Int(sqlite3_column_int(statement, index))
    }

    private func hasColumn(_ name: String, in table: String, database: OpaquePointer?) -> Bool {
        let pragmaQuery = "PRAGMA table_info(\(table))"
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(database, pragmaQuery, -1, &stmt, nil) == SQLITE_OK else { return false }
        defer { sqlite3_finalize(stmt) }
        while sqlite3_step(stmt) == SQLITE_ROW {
            if let text = sqlite3_column_text(stmt, 1), String(cString: text) == name {
                return true
            }
        }
        return false
    }

    private func openReadonly(_ url: URL) throws -> OpaquePointer? {
        var database: OpaquePointer?
        let flags = SQLITE_OPEN_READONLY | SQLITE_OPEN_URI
        let immutableURI = url.absoluteString + "?immutable=1"

        if sqlite3_open_v2(immutableURI, &database, flags, nil) == SQLITE_OK {
            return database
        }

        let immutableError = errorMessage(database)
        sqlite3_close(database)
        database = nil

        guard sqlite3_open_v2(url.path, &database, SQLITE_OPEN_READONLY, nil) == SQLITE_OK else {
            let fallbackError = errorMessage(database)
            sqlite3_close(database)
            throw SQLiteRepositoryError.openFailed(message: "\(fallbackError) (\(immutableError))")
        }
        return database
    }

    private func errorMessage(_ database: OpaquePointer?) -> String {
        guard let message = sqlite3_errmsg(database) else {
            return "Unbekannter SQLite-Fehler."
        }
        return String(cString: message)
    }
}

enum SQLiteRepositoryError: LocalizedError {
    case openFailed(message: String)
    case queryFailed(message: String)

    var errorDescription: String? {
        switch self {
        case .openFailed(let message):
            return "SQLite-Datenbank konnte nicht geöffnet werden: \(message)"
        case .queryFailed(let message):
            return "SQLite-Abfrage fehlgeschlagen: \(message)"
        }
    }
}
