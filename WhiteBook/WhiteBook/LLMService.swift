//
//  LLMService.swift
//  WhiteBook
//

import Foundation
import llama

final class LLMService {
    static let shared = LLMService()

    enum LLMServiceError: LocalizedError {
        case modelNotFound
        case modelLoadFailed
        case contextInitFailed
        case tokenizationFailed
        case decodeFailed
        case modelDownloadFailed(String)

        var errorDescription: String? {
            switch self {
            case .modelNotFound:
                return "No bundled or downloaded GGUF model was found."
            case .modelLoadFailed:
                return "Failed to load the GGUF model."
            case .contextInitFailed:
                return "Failed to initialize the llama context."
            case .tokenizationFailed:
                return "Prompt tokenization failed."
            case .decodeFailed:
                return "Model decode failed."
            case .modelDownloadFailed(let detail):
                return "Model download failed: \(detail)"
            }
        }
    }

    private let engine = LLMEngine()

    private init() {}

    func prepareModelIfNeeded(progress: (@MainActor @Sendable (Double) -> Void)? = nil) async throws {
        let reporter: (@Sendable (Double) -> Void)?
        if let progress {
            reporter = { value in
                Task { @MainActor in
                    progress(value)
                }
            }
        } else {
            reporter = nil
        }

        _ = try await engine.ensureLoaded(progress: reporter)
    }

    func generate(query: String, context: [Chunk]) -> AsyncStream<String> {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)

        return AsyncStream { continuation in
            guard !trimmed.isEmpty else {
                continuation.finish()
                return
            }

            Task.detached(priority: .userInitiated) { [engine] in
                do {
                    let prompt = Self.makePrompt(query: trimmed, context: context)
                    try await engine.generate(prompt: prompt, continuation: continuation)
                } catch {
                    continuation.yield("\n\n[Generation error: \(error.localizedDescription)]")
                    continuation.finish()
                }
            }
        }
    }

    nonisolated private static func makePrompt(query: String, context: [Chunk]) -> String {
        let systemPrompt = "You are an elite emergency medicine assistant. Answer strictly using the provided context chunks. If the context relies on a visual diagram, explicitly state the user should reference the attached image."

        let contextBlock: String
        if context.isEmpty {
            contextBlock = "No context chunks were retrieved."
        } else {
            contextBlock = context.enumerated().map { index, chunk in
                var lines: [String] = []
                lines.append("[Chunk \(index + 1)]")
                lines.append("Heading: \(chunk.heading_context)")
                lines.append("Pages: \(chunk.page_start)-\(chunk.page_end)")
                if let image = chunk.image_filename, !image.isEmpty {
                    lines.append("Image: \(image)")
                }
                lines.append("Content: \(chunk.text_content)")
                return lines.joined(separator: "\n")
            }.joined(separator: "\n\n")
        }

        // Qwen3 chat formatting with an explicit /think suffix to activate the reasoning mode.
        let userPrompt = "Context chunks:\n\(contextBlock)\n\nUser query: \(query)/think"

        return """
<|im_start|>system
\(systemPrompt)
<|im_end|>
<|im_start|>user
\(userPrompt)
<|im_end|>
<|im_start|>assistant
"""
    }
}

private actor LLMEngine {
    private let modelCandidates = [
        "Qwen3-8B-Q4_K_M.gguf",
        "Qwen3-4B-Instruct-Q4_K_M.gguf"
    ]
    private let downloadURL = URL(string: "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/Qwen3-8B-Q4_K_M.gguf?download=true")!

    private var modelPointer: OpaquePointer?
    private var contextPointer: OpaquePointer?
    private var didInitBackend = false

    deinit {
        if let contextPointer {
            llama_free(contextPointer)
        }
        if let modelPointer {
            llama_model_free(modelPointer)
        }
        if didInitBackend {
            llama_backend_free()
        }
    }

    func ensureLoaded(progress: (@Sendable (Double) -> Void)? = nil) async throws -> OpaquePointer {
        if let contextPointer {
            progress?(1.0)
            return contextPointer
        }

        if !didInitBackend {
            setenv("GGML_USE_METAL", "1", 1)
            llama_backend_init()
            didInitBackend = true
        }

        let modelURL = try await ensureModelFile(progress: progress)

        var modelParams = llama_model_default_params()
        modelParams.n_gpu_layers = Int32.max

        let loadedModel: OpaquePointer? = modelURL.path.withCString { cPath in
            llama_model_load_from_file(cPath, modelParams)
        }

        guard let loadedModel else {
            throw LLMService.LLMServiceError.modelLoadFailed
        }

        var contextParams = llama_context_default_params()
        contextParams.n_ctx = 4096
        contextParams.n_batch = 512
        contextParams.n_threads = Int32(max(1, ProcessInfo.processInfo.processorCount - 2))
        contextParams.n_threads_batch = contextParams.n_threads

        guard let loadedContext = llama_init_from_model(loadedModel, contextParams) else {
            llama_model_free(loadedModel)
            throw LLMService.LLMServiceError.contextInitFailed
        }

        modelPointer = loadedModel
        contextPointer = loadedContext
        return loadedContext
    }

    func generate(prompt: String, continuation: AsyncStream<String>.Continuation) async throws {
        let context = try await ensureLoaded()
        guard let model = modelPointer else {
            throw LLMService.LLMServiceError.modelLoadFailed
        }

        guard let vocab = llama_model_get_vocab(model) else {
            throw LLMService.LLMServiceError.tokenizationFailed
        }

        var tokens = Array<llama_token>(repeating: 0, count: 8192)
        let tokenCount = prompt.withCString { cPrompt in
            llama_tokenize(vocab, cPrompt, Int32(strlen(cPrompt)), &tokens, Int32(tokens.count), true, true)
        }

        guard tokenCount > 0 else {
            throw LLMService.LLMServiceError.tokenizationFailed
        }

        var promptTokens = Array(tokens.prefix(Int(tokenCount)))
        let initialBatch = promptTokens.withUnsafeMutableBufferPointer { buffer in
            llama_batch_get_one(buffer.baseAddress, Int32(buffer.count))
        }

        if llama_decode(context, initialBatch) != 0 {
            throw LLMService.LLMServiceError.decodeFailed
        }

        let maxGeneratedTokens = 768

        let samplerChainParams = llama_sampler_chain_default_params()
        let sampler = llama_sampler_chain_init(samplerChainParams)
        defer {
            llama_sampler_free(sampler)
        }

        llama_sampler_chain_add(sampler, llama_sampler_init_temp(0.7))
        llama_sampler_chain_add(sampler, llama_sampler_init_top_k(40))
        llama_sampler_chain_add(sampler, llama_sampler_init_top_p(0.9, 1))
        llama_sampler_chain_add(sampler, llama_sampler_init_dist(UInt32.random(in: UInt32.min...UInt32.max)))

        for _ in 0..<maxGeneratedTokens {
            let token = llama_sampler_sample(sampler, context, -1)
            if llama_vocab_is_eog(vocab, token) {
                break
            }

            let tokenText = tokenToString(token: token, vocab: vocab)
            if !tokenText.isEmpty {
                continuation.yield(tokenText)
            }

            var tokenArray = [token]
            let tokenBatch = tokenArray.withUnsafeMutableBufferPointer { buffer in
                llama_batch_get_one(buffer.baseAddress, 1)
            }
            if llama_decode(context, tokenBatch) != 0 {
                break
            }
        }

        continuation.finish()
    }

    private func tokenToString(token: llama_token, vocab: OpaquePointer) -> String {
        var buffer = Array<CChar>(repeating: 0, count: 512)
        let length = llama_token_to_piece(vocab, token, &buffer, Int32(buffer.count), 0, true)
        guard length > 0 else {
            return ""
        }

        return buffer.withUnsafeBufferPointer { pointer in
            let valid = pointer.prefix(Int(length))
            return String(decoding: valid.map { UInt8(bitPattern: $0) }, as: UTF8.self)
        }
    }

    private func ensureModelFile(progress: (@Sendable (Double) -> Void)? = nil) async throws -> URL {
        let documentsURL = try modelDirectoryURL()
        let fileManager = FileManager.default

        for modelName in modelCandidates {
            let destination = documentsURL.appendingPathComponent(modelName)
            if fileManager.fileExists(atPath: destination.path) {
                progress?(1.0)
                return destination
            }
        }

        for modelName in modelCandidates {
            if let bundledURL = Bundle.main.url(forResource: modelName.replacingOccurrences(of: ".gguf", with: ""), withExtension: "gguf") {
                let destination = documentsURL.appendingPathComponent(modelName)
                if !fileManager.fileExists(atPath: destination.path) {
                    try fileManager.copyItem(at: bundledURL, to: destination)
                }
                progress?(1.0)
                return destination
            }
        }

        let destination = documentsURL.appendingPathComponent(modelCandidates[0])
        do {
            let tempURL = documentsURL.appendingPathComponent("qwen_download.partial")
            let (bytes, response) = try await URLSession.shared.bytes(from: downloadURL)
            if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
                throw LLMService.LLMServiceError.modelDownloadFailed("HTTP \(http.statusCode)")
            }

            let expectedBytes = response.expectedContentLength
            if fileManager.fileExists(atPath: tempURL.path) {
                try fileManager.removeItem(at: tempURL)
            }

            fileManager.createFile(atPath: tempURL.path, contents: nil)
            let fileHandle = try FileHandle(forWritingTo: tempURL)

            var receivedBytes: Int64 = 0
            var buffer = Data()
            buffer.reserveCapacity(64 * 1024)

            do {
                for try await byte in bytes {
                    try Task.checkCancellation()

                    buffer.append(byte)
                    receivedBytes += 1

                    if buffer.count >= 64 * 1024 {
                        try fileHandle.write(contentsOf: buffer)
                        buffer.removeAll(keepingCapacity: true)
                    }

                    if expectedBytes > 0, receivedBytes.isMultiple(of: 32 * 1024) {
                        let fraction = min(1.0, Double(receivedBytes) / Double(expectedBytes))
                        progress?(fraction)
                    }
                }

                if !buffer.isEmpty {
                    try fileHandle.write(contentsOf: buffer)
                }

                try fileHandle.close()
            } catch {
                try? fileHandle.close()
                try? fileManager.removeItem(at: tempURL)
                throw error
            }

            if fileManager.fileExists(atPath: destination.path) {
                try fileManager.removeItem(at: destination)
            }
            try fileManager.moveItem(at: tempURL, to: destination)
            progress?(1.0)
            return destination
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            throw LLMService.LLMServiceError.modelDownloadFailed(error.localizedDescription)
        }
    }

    private func modelDirectoryURL() throws -> URL {
        guard let documents = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first else {
            throw LLMService.LLMServiceError.modelNotFound
        }

        let modelsDirectory = documents.appendingPathComponent("Models", isDirectory: true)
        if !FileManager.default.fileExists(atPath: modelsDirectory.path) {
            try FileManager.default.createDirectory(at: modelsDirectory, withIntermediateDirectories: true)
        }

        return modelsDirectory
    }
}
