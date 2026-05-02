import Foundation
import SQLite3

private let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

enum LocalKnowledgeBaseError: LocalizedError {
    case databaseNotFound
    case openFailed
    case queryPrepareFailed

    var errorDescription: String? {
        switch self {
        case .databaseNotFound:
            return "Could not find staffbook_kb.sqlite in the app bundle."
        case .openFailed:
            return "Could not open the bundled SQLite database."
        case .queryPrepareFailed:
            return "Could not prepare the local retrieval query."
        }
    }
}

struct LocalKnowledgeBase {
    private let dbPath: String

    init() throws {
        guard let path = Bundle.main.path(forResource: "staffbook_kb", ofType: "sqlite") else {
            throw LocalKnowledgeBaseError.databaseNotFound
        }
        dbPath = path
    }

    func search(_ query: String, limit: Int = 5) throws -> [RetrievedChunk] {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return [] }

        var db: OpaquePointer?
        guard sqlite3_open_v2(dbPath, &db, SQLITE_OPEN_READONLY, nil) == SQLITE_OK, let db else {
            throw LocalKnowledgeBaseError.openFailed
        }
        defer { sqlite3_close(db) }

        // Tokenize query for better text matching
        let words = trimmed.components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { $0.count > 2 }
            .map { $0.lowercased() }
        let searchWords = words.isEmpty ? [trimmed.lowercased()] : words

        var scoreSelects: [String] = []
        var whereClauses: [String] = []
        for _ in searchWords {
            scoreSelects.append("((CASE WHEN lower(text_content) LIKE '%' || ? || '%' THEN 2 ELSE 0 END) + (CASE WHEN lower(heading_context) LIKE '%' || ? || '%' THEN 1 ELSE 0 END))")
            whereClauses.append("(lower(text_content) LIKE '%' || ? || '%' OR lower(heading_context) LIKE '%' || ? || '%')")
        }

        let sql = """
        SELECT id, heading_context, text_content, page_start, page_end, image_filename,
               (\(scoreSelects.joined(separator: " + "))) AS score
        FROM chunks
        WHERE \(whereClauses.joined(separator: " OR "))
        ORDER BY score DESC, rowid DESC
        LIMIT ?
        """

        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK, let stmt else {
            throw LocalKnowledgeBaseError.queryPrepareFailed
        }
        defer { sqlite3_finalize(stmt) }

        var bindIndex: Int32 = 1
        for word in searchWords {
            sqlite3_bind_text(stmt, bindIndex, (word as NSString).utf8String, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(stmt, bindIndex + 1, (word as NSString).utf8String, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(stmt, bindIndex + 2, (word as NSString).utf8String, -1, SQLITE_TRANSIENT)
            sqlite3_bind_text(stmt, bindIndex + 3, (word as NSString).utf8String, -1, SQLITE_TRANSIENT)
            bindIndex += 4
        }
        sqlite3_bind_int(stmt, bindIndex, Int32(limit))

        var rows: [RetrievedChunk] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            let id = String(cString: sqlite3_column_text(stmt, 0))
            let heading = sqlite3_column_text(stmt, 1).flatMap { String(cString: $0) }
            let text = sqlite3_column_text(stmt, 2).flatMap { String(cString: $0) } ?? ""
            let pageStart = sqlite3_column_type(stmt, 3) == SQLITE_NULL ? nil : Int(sqlite3_column_int(stmt, 3))
            let pageEnd = sqlite3_column_type(stmt, 4) == SQLITE_NULL ? nil : Int(sqlite3_column_int(stmt, 4))
            rows.append(
                RetrievedChunk(
                    id: id,
                    headingContext: heading,
                    textContent: text,
                    pageStart: pageStart,
                    pageEnd: pageEnd
                )
            )
        }

        return rows
    }
}
