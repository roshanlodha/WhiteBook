//
//  DatabaseService.swift
//  WhiteBook
//

import Foundation
import SQLite

final class DatabaseService {
    static let shared = DatabaseService()

    enum DatabaseError: LocalizedError {
        case bundleDatabaseNotFound
        case documentsDirectoryUnavailable
        case copyFailed(underlying: Error)
        case openFailed(underlying: Error)
        case rowDecodingFailed(underlying: Error)
        case notReady

        var errorDescription: String? {
            switch self {
            case .bundleDatabaseNotFound:
                return "staffbook_kb.sqlite was not found in Bundle.main."
            case .documentsDirectoryUnavailable:
                return "The Documents directory could not be resolved."
            case .copyFailed(let underlying):
                return "Failed to copy staffbook_kb.sqlite into Documents: \(underlying.localizedDescription)"
            case .openFailed(let underlying):
                return "Failed to open the SQLite database: \(underlying.localizedDescription)"
            case .rowDecodingFailed(let underlying):
                return "Failed to decode a database row into Chunk: \(underlying.localizedDescription)"
            case .notReady:
                return "The SQLite database connection is not ready."
            }
        }
    }

    let chunks = Table("chunks")
    let id = Expression<String>("id")
    let headingContext = Expression<String>("heading_context")
    let textContent = Expression<String>("text_content")
    let pageStart = Expression<Int>("page_start")
    let pageEnd = Expression<Int>("page_end")
    let imageFilename = Expression<String?>("image_filename")
    let embedding = Expression<Data>("embedding")

    private let databaseFileName = "staffbook_kb.sqlite"
    private let accessQueue = DispatchQueue(label: "com.whitebook.database-service")
    private var connection: Connection?

    private init() {
        do {
            let databaseURL = try Self.prepareDatabaseFile(named: databaseFileName)
            connection = try Connection(databaseURL.path)
        } catch {
            connection = nil
            print(error.localizedDescription)
        }
    }

    func fetchAllChunks() throws -> [Chunk] {
        try withConnection { connection in
            let query = chunks.order(pageStart.asc)
            return try connection.prepare(query).map { row in
                try self.chunk(from: row)
            }
        }
    }

    func fetchChunk(by id: String) throws -> Chunk? {
        try withConnection { connection in
            guard let row = try connection.pluck(chunks.filter(self.id == id)) else {
                return nil
            }
            return try self.chunk(from: row)
        }
    }

    private func withConnection<T>(_ work: (Connection) throws -> T) throws -> T {
        try accessQueue.sync {
            guard let connection else {
                throw DatabaseError.notReady
            }
            return try work(connection)
        }
    }

    private static func prepareDatabaseFile(named fileName: String) throws -> URL {
        guard let bundleURL = Bundle.main.url(forResource: "staffbook_kb", withExtension: "sqlite") else {
            let error = DatabaseError.bundleDatabaseNotFound
            print(error.localizedDescription)
            throw error
        }

        guard let documentsURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else {
            let error = DatabaseError.documentsDirectoryUnavailable
            print(error.localizedDescription)
            throw error
        }

        let destinationURL = documentsURL.appendingPathComponent(fileName, isDirectory: false)
        let fileManager = FileManager.default

        if !fileManager.fileExists(atPath: destinationURL.path) {
            do {
                try fileManager.copyItem(at: bundleURL, to: destinationURL)
            } catch {
                let wrappedError = DatabaseError.copyFailed(underlying: error)
                print(wrappedError.localizedDescription)
                throw wrappedError
            }
        }

        return destinationURL
    }

    private func chunk(from row: Row) throws -> Chunk {
        do {
            return Chunk(
                id: try row.get(id),
                heading_context: try row.get(headingContext),
                text_content: try row.get(textContent),
                page_start: try row.get(pageStart),
                page_end: try row.get(pageEnd),
                image_filename: try row.get(imageFilename),
                embedding: try row.get(embedding)
            )
        } catch {
            let wrappedError = DatabaseError.rowDecodingFailed(underlying: error)
            print(wrappedError.localizedDescription)
            throw wrappedError
        }
    }
}