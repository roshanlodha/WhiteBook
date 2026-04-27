//
//  AssistantViewModel.swift
//  WhiteBook
//

import Foundation
import Combine

@MainActor
final class AssistantViewModel: ObservableObject {
    @Published var query = ""
    @Published var answerText = ""
    @Published var contextChunks: [Chunk] = []
    @Published var isGenerating = false
    @Published var isPreparingModel = false
    @Published var isDownloadingModel = false
    @Published var downloadProgress: Double = 0
    @Published var modelStatus = "Preparing on-device model..."

    private let searchService: SearchService
    private let llmService: LLMService
    private var prepareTask: Task<Void, Never>?

    init(searchService: SearchService? = nil, llmService: LLMService? = nil) {
        self.searchService = searchService ?? .shared
        self.llmService = llmService ?? .shared
    }

    func startPreparingModelIfNeeded() {
        guard prepareTask == nil else {
            return
        }

        prepareTask = Task { [weak self] in
            guard let self else { return }
            await self.prepareModelIfNeeded()
            self.prepareTask = nil
        }
    }

    func cancelModelDownload() {
        prepareTask?.cancel()
        prepareTask = nil
        isPreparingModel = false
        isDownloadingModel = false
        modelStatus = "Model download canceled"
    }

    func prepareModelIfNeeded() async {
        guard !isPreparingModel else {
            return
        }

        isPreparingModel = true
        isDownloadingModel = true
        downloadProgress = 0
        modelStatus = "Preparing on-device model..."

        do {
            try await llmService.prepareModelIfNeeded { [weak self] progress in
                guard let self else { return }
                self.downloadProgress = progress
                self.modelStatus = "Downloading model: \(Int((progress * 100).rounded()))%"
            }
            modelStatus = "Model ready"
            downloadProgress = 1
        } catch is CancellationError {
            modelStatus = "Model download canceled"
        } catch {
            modelStatus = "Model setup failed: \(error.localizedDescription)"
        }

        isDownloadingModel = false
        isPreparingModel = false
    }

    func ask() async {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            return
        }

        if !isPreparingModel {
            await prepareModelIfNeeded()
        }

        guard modelStatus == "Model ready" else {
            return
        }

        isGenerating = true
        answerText = ""

        contextChunks = await searchService.searchAsync(query: trimmed)

        let stream = llmService.generate(query: trimmed, context: contextChunks)
        for await token in stream {
            answerText += token
        }

        isGenerating = false
    }
}
