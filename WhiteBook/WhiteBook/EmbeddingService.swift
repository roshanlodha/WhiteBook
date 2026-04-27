//
//  EmbeddingService.swift
//  WhiteBook
//

import CoreML
import Foundation

final class EmbeddingService {
    static let shared = EmbeddingService()

    enum EmbeddingError: LocalizedError {
        case modelNotFound
        case invalidModelInput(String)
        case predictionFailed(String)
        case outputMissing(String)

        var errorDescription: String? {
            switch self {
            case .modelNotFound:
                return "WhiteBookEmbedder.mlpackage was not found in Bundle.main."
            case .invalidModelInput(let detail):
                return "Invalid model input: \(detail)"
            case .predictionFailed(let detail):
                return "Embedding model prediction failed: \(detail)"
            case .outputMissing(let name):
                return "Expected model output '\(name)' was not found or was not an MLMultiArray."
            }
        }
    }

    private let model: MLModel
    private let inputShape: [NSNumber]
    private let sequenceLength: Int
    private let vocab: [String: Int32]?
    private let inputFeatureName = "input_ids"
    private let attentionFeatureName = "attention_mask"
    private let outputFeatureName = "embeddings"

    private init() {
        do {
            guard let modelURL = Bundle.main.url(forResource: "WhiteBookEmbedder", withExtension: "mlpackage") else {
                throw EmbeddingError.modelNotFound
            }

            let configuration = MLModelConfiguration()
            configuration.computeUnits = .all
            self.model = try MLModel(contentsOf: modelURL, configuration: configuration)
            let inputSpec = EmbeddingService.resolveInputSpec(from: model)
            self.inputShape = inputSpec.shape
            self.sequenceLength = inputSpec.sequenceLength
            self.vocab = EmbeddingService.loadVocabFromBundle()
        } catch {
            fatalError(error.localizedDescription)
        }
    }

    func embed(query: String) throws -> [Float32] {
        let normalizedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalizedQuery.isEmpty else {
            return []
        }

        let tokens = tokenize(query: normalizedQuery, maxLength: sequenceLength)
        let inputIDs = try makeInt32MultiArray(values: tokens.inputIDs, featureName: inputFeatureName)
        let attentionMask = try makeInt32MultiArray(values: tokens.attentionMask, featureName: attentionFeatureName)

        let provider = try MLDictionaryFeatureProvider(dictionary: [
            inputFeatureName: MLFeatureValue(multiArray: inputIDs),
            attentionFeatureName: MLFeatureValue(multiArray: attentionMask)
        ])

        let output: MLFeatureProvider
        do {
            output = try model.prediction(from: provider)
        } catch {
            throw EmbeddingError.predictionFailed(error.localizedDescription)
        }

        guard let embeddingArray = output.featureValue(for: outputFeatureName)?.multiArrayValue else {
            throw EmbeddingError.outputMissing(outputFeatureName)
        }

        return flattenAndPoolEmbedding(embeddingArray, attentionMask: tokens.attentionMask)
    }

    private static func resolveInputSpec(from model: MLModel) -> (shape: [NSNumber], sequenceLength: Int) {
        guard
            let input = model.modelDescription.inputDescriptionsByName["input_ids"],
            let constraint = input.multiArrayConstraint,
            let shape = constraint.shape as? [NSNumber],
            let last = shape.last
        else {
            return ([1, 512], 512)
        }

        let candidate = last.intValue
        return (shape, max(candidate, 8))
    }

    private static func loadVocabFromBundle() -> [String: Int32]? {
        guard let vocabURL = Bundle.main.url(forResource: "vocab", withExtension: "txt") else {
            return nil
        }

        guard let raw = try? String(contentsOf: vocabURL), !raw.isEmpty else {
            return nil
        }

        var table: [String: Int32] = [:]
        for (index, token) in raw.split(whereSeparator: \.isNewline).map(String.init).enumerated() {
            table[token] = Int32(index)
        }

        return table.isEmpty ? nil : table
    }

    private func tokenize(query: String, maxLength: Int) -> (inputIDs: [Int32], attentionMask: [Int32]) {
        let clsToken: Int32 = 101
        let sepToken: Int32 = 102
        let unkToken: Int32 = 100
        let padToken: Int32 = 0

        let words = basicTokens(from: query)

        let payloadCount = max(0, maxLength - 2)
        let tokenIDs = wordsToTokenIDs(words, unkTokenID: unkToken)
        let trimmedTokenIDs = tokenIDs.prefix(payloadCount)

        var inputIDs: [Int32] = [clsToken]
        inputIDs.reserveCapacity(maxLength)

        inputIDs.append(contentsOf: trimmedTokenIDs)

        inputIDs.append(sepToken)

        if inputIDs.count < maxLength {
            inputIDs.append(contentsOf: Array(repeating: padToken, count: maxLength - inputIDs.count))
        } else if inputIDs.count > maxLength {
            inputIDs = Array(inputIDs.prefix(maxLength))
            inputIDs[maxLength - 1] = sepToken
        }

        let attentionMask: [Int32] = inputIDs.map { $0 == padToken ? 0 : 1 }
        return (inputIDs, attentionMask)
    }

    private func basicTokens(from text: String) -> [String] {
        var tokens: [String] = []
        tokens.reserveCapacity(64)

        let scalarSet = CharacterSet.alphanumerics
        var current = ""

        for scalar in text.lowercased().unicodeScalars {
            if scalarSet.contains(scalar) {
                current.unicodeScalars.append(scalar)
                continue
            }

            if !current.isEmpty {
                tokens.append(current)
                current.removeAll(keepingCapacity: true)
            }

            if !CharacterSet.whitespacesAndNewlines.contains(scalar) {
                tokens.append(String(scalar))
            }
        }

        if !current.isEmpty {
            tokens.append(current)
        }

        return tokens
    }

    private func wordsToTokenIDs(_ words: [String], unkTokenID: Int32) -> [Int32] {
        guard let vocab else {
            return words.map(stableHashTokenID)
        }

        var tokenIDs: [Int32] = []
        tokenIDs.reserveCapacity(words.count)

        for word in words {
            if let id = vocab[word] {
                tokenIDs.append(id)
                continue
            }

            let pieces = wordPieceTokenize(word, vocab: vocab, unkTokenID: unkTokenID)
            tokenIDs.append(contentsOf: pieces)
        }

        return tokenIDs
    }

    private func wordPieceTokenize(_ token: String, vocab: [String: Int32], unkTokenID: Int32) -> [Int32] {
        if token.count > 100 {
            return [unkTokenID]
        }

        var start = token.startIndex
        var pieces: [Int32] = []

        while start < token.endIndex {
            var end = token.endIndex
            var currentID: Int32?
            var nextStart = end

            while start < end {
                let range = start..<end
                let fragment = String(token[range])
                let candidate = (start == token.startIndex) ? fragment : "##\(fragment)"

                if let id = vocab[candidate] {
                    currentID = id
                    nextStart = end
                    break
                }

                end = token.index(before: end)
            }

            guard let id = currentID else {
                return [unkTokenID]
            }

            pieces.append(id)
            start = nextStart
        }

        return pieces
    }

    private func stableHashTokenID(for token: String) -> Int32 {
        // FNV-1a for deterministic IDs across runs.
        var hash: UInt32 = 2_166_136_261
        for byte in token.utf8 {
            hash ^= UInt32(byte)
            hash = hash &* 16_777_619
        }

        // Keep IDs away from small special-token ranges.
        let shifted = 1_000 + (hash % 30_000)
        return Int32(shifted)
    }

    private func makeInt32MultiArray(values: [Int32], featureName: String) throws -> MLMultiArray {
        guard values.count == sequenceLength else {
            throw EmbeddingError.invalidModelInput(
                "\(featureName) length \(values.count) != expected sequence length \(sequenceLength)."
            )
        }

        let array = try MLMultiArray(shape: inputShape, dataType: .int32)
        guard array.count == values.count else {
            throw EmbeddingError.invalidModelInput(
                "\(featureName) MLMultiArray count \(array.count) does not match token count \(values.count)."
            )
        }

        values.withUnsafeBufferPointer { source in
            guard let src = source.baseAddress else { return }
            let dst = array.dataPointer.bindMemory(to: Int32.self, capacity: values.count)
            dst.assign(from: src, count: values.count)
        }

        return array
    }

    private func flattenAndPoolEmbedding(_ array: MLMultiArray, attentionMask: [Int32]) -> [Float32] {
        let shape = array.shape.map(\.intValue)

        if shape.count == 2 {
            return multiArrayToFloat32(array)
        }

        if shape.count == 3 {
            let batch = shape[0]
            let seq = shape[1]
            let dim = shape[2]

            guard batch > 0, seq > 0, dim > 0 else {
                return []
            }

            let flat = multiArrayToFloat32(array)
            guard flat.count >= seq * dim else {
                return flat
            }

            var pooled = Array(repeating: Float32(0), count: dim)
            var validCount: Float32 = 0

            for tokenIndex in 0..<min(seq, attentionMask.count) {
                if attentionMask[tokenIndex] == 0 {
                    continue
                }
                let offset = tokenIndex * dim
                for i in 0..<dim {
                    pooled[i] += flat[offset + i]
                }
                validCount += 1
            }

            if validCount > 0 {
                let inv = Float32(1.0) / validCount
                for i in 0..<pooled.count {
                    pooled[i] *= inv
                }
            }

            return pooled
        }

        return multiArrayToFloat32(array)
    }

    private func multiArrayToFloat32(_ array: MLMultiArray) -> [Float32] {
        let count = array.count

        switch array.dataType {
        case .float32:
            let pointer = array.dataPointer.bindMemory(to: Float32.self, capacity: count)
            return Array(UnsafeBufferPointer(start: pointer, count: count))

        case .double:
            let pointer = array.dataPointer.bindMemory(to: Double.self, capacity: count)
            return Array(UnsafeBufferPointer(start: pointer, count: count)).map(Float32.init)

        case .float16:
            let pointer = array.dataPointer.bindMemory(to: Float16.self, capacity: count)
            return Array(UnsafeBufferPointer(start: pointer, count: count)).map(Float32.init)

        case .int32:
            let pointer = array.dataPointer.bindMemory(to: Int32.self, capacity: count)
            return Array(UnsafeBufferPointer(start: pointer, count: count)).map(Float32.init)

        default:
            return Array(repeating: 0, count: count)
        }
    }
}
