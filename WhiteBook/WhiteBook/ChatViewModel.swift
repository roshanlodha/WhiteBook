import Foundation
import Combine

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var draft: String = ""
    @Published var isLoading = false
    @Published var showingError = false
    @Published var errorMessage = ""

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

    func send() async {
        let question = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty, !isLoading else { return }

        isLoading = true
        draft = ""
        messages.append(ChatMessage(role: .user, text: question, sources: []))

        do {
            guard let knowledgeBase else {
                throw LocalKnowledgeBaseError.databaseNotFound
            }
            guard let groqService else {
                throw GroqServiceError.missingAPIKey
            }

            let chunks = try knowledgeBase.search(question, limit: 5)
            let answer = try await groqService.complete(userQuestion: question, context: chunks)
            messages.append(ChatMessage(role: .assistant, text: answer, sources: chunks))
        } catch {
            errorMessage = error.localizedDescription
            showingError = true
        }

        isLoading = false
    }
}
