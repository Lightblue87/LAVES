import Foundation
import SQLite3

struct SQLiteAdditiveRepository {
    func loadAdditives(from databaseURL: URL) throws -> [Additive] {
        var database: OpaquePointer?
        guard sqlite3_open_v2(databaseURL.path, &database, SQLITE_OPEN_READONLY, nil) == SQLITE_OK else {
            defer { sqlite3_close(database) }
            throw SQLiteRepositoryError.openFailed(message: errorMessage(database))
        }
        defer { sqlite3_close(database) }

        let query = """
        SELECT kennnummer, name, tierarten, hoechstalter_tage, min_mg_kg, max_mg_kg,
               einheit, rechtsgrundlage, source_file, source_page, tierart_kategorie
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
