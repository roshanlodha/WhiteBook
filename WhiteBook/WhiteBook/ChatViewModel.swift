import Foundation
import Combine

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var draft: String = ""
    @Published var isLoading = false
    @Published var showingError = false
    @Published var errorMessage = ""
    @Published var isToolsModeActive = false
    @Published var isThinkingModeActive = false
    @Published var streamVersion = 0

    private let knowledgeBase: LocalKnowledgeBase?
    private let groqService: GroqService?

    init() {
        knowledgeBase = try? LocalKnowledgeBase()
        groqService = try? GroqService()
    }

    func clear() {
        messages.removeAll()
        draft = ""
    }

    var draftPlaceholder: String {
        if isToolsModeActive {
            return "E.g., Calculate the HEART score for a 65F patient..."
        }
        return "Ask the MGH WhiteBook a clinical question..."
    }

    func send() async {
        let question = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty, !isLoading else { return }

        isLoading = true
        draft = ""
        messages.append(
            ChatMessage(
                role: .user,
                text: question,
                thinkContent: nil,
                toolResults: [],
                sources: []
            )
        )

        do {
            guard let knowledgeBase else {
                throw LocalKnowledgeBaseError.databaseNotFound
            }
            guard let groqService else {
                throw GroqServiceError.missingAPIKey
            }

            let chunks = try knowledgeBase.search(question, limit: 5)
            let assistantIndex = messages.count
            messages.append(
                ChatMessage(
                    role: .assistant,
                    text: "",
                    thinkContent: nil,
                    toolResults: [],
                    sources: chunks
                )
            )
            var streamedText = ""
            for try await token in groqService.streamCompletion(
                userQuestion: question,
                context: chunks,
                toolsMode: isToolsModeActive,
                thinkingMode: isThinkingModeActive
            ) {
                streamedText += token
                let parsed = ParsedAssistantContent.parse(streamedText)
                messages[assistantIndex] = ChatMessage(
                    role: .assistant,
                    text: parsed.answer,
                    thinkContent: parsed.think,
                    toolResults: parsed.tools,
                    sources: chunks
                )
                streamVersion &+= 1
            }
        } catch {
            if let last = messages.last, last.role == .assistant, last.text.isEmpty, (last.thinkContent ?? "").isEmpty, last.toolResults.isEmpty {
                messages.removeLast()
            }
            errorMessage = error.localizedDescription
            showingError = true
        }

        isLoading = false
    }
}
