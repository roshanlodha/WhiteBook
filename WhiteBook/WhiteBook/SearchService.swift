//
//  SearchService.swift
//  WhiteBook
//

import Accelerate
import Foundation

final class SearchService {
    static let shared = SearchService()

    private let databaseService: DatabaseService
    private let embeddingService: EmbeddingService
    private let threshold: Float32 = 0.6
    private let topK: Int = 5

    init(databaseService: DatabaseService = .shared, embeddingService: EmbeddingService = .shared) {
        self.databaseService = databaseService
        self.embeddingService = embeddingService
    }

    // Synchronous API requested by the caller. It executes retrieval work in a background Task.
    func search(query: String) -> [Chunk] {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            return []
        }

        let semaphore = DispatchSemaphore(value: 0)
        var output: [Chunk] = []

        Task.detached(priority: .userInitiated) { [weak self] in
            defer { semaphore.signal() }
            guard let self else { return }
            output = await self.searchAsync(query: trimmed)
        }

        semaphore.wait()
        return output
    }

    // Preferred API for UI usage to avoid blocking the caller thread.
    func searchAsync(query: String) async -> [Chunk] {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            return []
        }

        return await Task.detached(priority: .userInitiated) { [databaseService, embeddingService, threshold, topK] in
            let queryEmbedding: [Float32]
            do {
                queryEmbedding = try embeddingService.embed(query: trimmed)
            } catch {
                print(error.localizedDescription)
                return []
            }

            if queryEmbedding.isEmpty {
                return []
            }

            let chunks: [Chunk]
            do {
                chunks = try databaseService.fetchAllChunks()
            } catch {
                print(error.localizedDescription)
                return []
            }

            return SearchService.topKMatches(
                chunks: chunks,
                queryEmbedding: queryEmbedding,
                threshold: threshold,
                topK: topK
            ).map(\.chunk)
        }.value
    }

    static func cosineSimilarity(_ lhs: [Float32], _ rhs: [Float32]) -> Float32 {
        let count = min(lhs.count, rhs.count)
        guard count > 0 else {
            return 0
        }

        var dot: Float32 = 0
        var lhsSquared: Float32 = 0
        var rhsSquared: Float32 = 0

        lhs.withUnsafeBufferPointer { lhsBuffer in
            rhs.withUnsafeBufferPointer { rhsBuffer in
                guard let lhsPtr = lhsBuffer.baseAddress, let rhsPtr = rhsBuffer.baseAddress else {
                    return
                }

                let n = vDSP_Length(count)
                vDSP_dotpr(lhsPtr, 1, rhsPtr, 1, &dot, n)
                vDSP_svesq(lhsPtr, 1, &lhsSquared, n)
                vDSP_svesq(rhsPtr, 1, &rhsSquared, n)
            }
        }

        let denom = sqrt(lhsSquared) * sqrt(rhsSquared)
        return denom > 0 ? (dot / denom) : 0
    }

    private static func topKMatches(
        chunks: [Chunk],
        queryEmbedding: [Float32],
        threshold: Float32,
        topK: Int
    ) -> [ScoredChunk] {
        guard topK > 0 else {
            return []
        }

        var results: [ScoredChunk] = []
        results.reserveCapacity(topK)

        let queryNorm = sqrt(vDSP.sumOfSquares(queryEmbedding))
        if queryNorm == 0 {
            return []
        }

        for chunk in chunks {
            guard let chunkEmbedding = decodeEmbeddingBlob(chunk.embedding), !chunkEmbedding.isEmpty else {
                continue
            }

            let score = cosineSimilarityFast(
                query: queryEmbedding,
                queryNorm: queryNorm,
                candidate: chunkEmbedding
            )

            guard score >= threshold else {
                continue
            }

            let candidate = ScoredChunk(chunk: chunk, score: score)

            if results.count < topK {
                insertSortedDescending(candidate, into: &results)
                continue
            }

            if let tail = results.last, score > tail.score {
                _ = results.popLast()
                insertSortedDescending(candidate, into: &results)
            }
        }

        return results
    }

    private static func cosineSimilarityFast(query: [Float32], queryNorm: Float32, candidate: [Float32]) -> Float32 {
        let count = min(query.count, candidate.count)
        guard count > 0 else {
            return 0
        }

        var dot: Float32 = 0
        var candidateSquared: Float32 = 0

        query.withUnsafeBufferPointer { queryBuffer in
            candidate.withUnsafeBufferPointer { candidateBuffer in
                guard let queryPtr = queryBuffer.baseAddress, let candidatePtr = candidateBuffer.baseAddress else {
                    return
                }

                let n = vDSP_Length(count)
                vDSP_dotpr(queryPtr, 1, candidatePtr, 1, &dot, n)
                vDSP_svesq(candidatePtr, 1, &candidateSquared, n)
            }
        }

        let denom = queryNorm * sqrt(candidateSquared)
        return denom > 0 ? (dot / denom) : 0
    }

    private static func insertSortedDescending(_ item: ScoredChunk, into array: inout [ScoredChunk]) {
        if array.isEmpty {
            array.append(item)
            return
        }

        var low = 0
        var high = array.count

        while low < high {
            let mid = (low + high) / 2
            if item.score > array[mid].score {
                high = mid
            } else {
                low = mid + 1
            }
        }

        array.insert(item, at: low)
    }

    private static func decodeEmbeddingBlob(_ data: Data) -> [Float32]? {
        guard !data.isEmpty, data.count.isMultiple(of: MemoryLayout<Float32>.size) else {
            return nil
        }

        let floatCount = data.count / MemoryLayout<Float32>.size
        var output = Array(repeating: Float32(0), count: floatCount)
        output.withUnsafeMutableBytes { destination in
            data.copyBytes(to: destination)
        }

        return output
    }

    private struct ScoredChunk {
        let chunk: Chunk
        let score: Float32
    }
}
