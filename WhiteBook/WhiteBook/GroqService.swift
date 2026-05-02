import Foundation

enum GroqServiceError: LocalizedError {
    case missingAPIKey
    case invalidResponse
    case upstreamError(String)

    var errorDescription: String? {
        switch self {
        case .missingAPIKey:
            return "Missing Groq API key. Set GROQ_API_KEY in target build settings."
        case .invalidResponse:
            return "Groq returned an invalid response."
        case let .upstreamError(message):
            return message
        }
    }
}

struct GroqService {
    private let apiKey: String
    private let model: String

    init() throws {
        let key = (Bundle.main.object(forInfoDictionaryKey: "GROQ_API_KEY") as? String ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !key.isEmpty else {
            throw GroqServiceError.missingAPIKey
        }
        apiKey = key
        model = (Bundle.main.object(forInfoDictionaryKey: "GROQ_MODEL") as? String ?? "qwen/qwen3-32b")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func complete(userQuestion: String, context: [RetrievedChunk]) async throws -> String {
        let endpoint = URL(string: "https://api.groq.com/openai/v1/chat/completions")!
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")

        let prompt = Self.makeContextPrompt(userQuestion: userQuestion, chunks: context)
        let body = ChatCompletionsRequest(
            model: model,
            messages: [
                .init(role: "system", content: Self.systemPrompt),
                .init(role: "user", content: prompt)
            ],
            temperature: 0.2
        )

        request.httpBody = try JSONEncoder().encode(body)
        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw GroqServiceError.invalidResponse
        }
        guard (200...299).contains(httpResponse.statusCode) else {
            let apiError = try? JSONDecoder().decode(GroqErrorEnvelope.self, from: data)
            throw GroqServiceError.upstreamError(apiError?.error.message ?? "Groq request failed with status \(httpResponse.statusCode).")
        }

        let decoded = try JSONDecoder().decode(ChatCompletionsResponse.self, from: data)
        guard let text = decoded.choices.first?.message.content?.trimmingCharacters(in: .whitespacesAndNewlines), !text.isEmpty else {
            throw GroqServiceError.invalidResponse
        }
        return text
    }

    private static func makeContextPrompt(userQuestion: String, chunks: [RetrievedChunk]) -> String {
        if chunks.isEmpty {
            return """
            Retrieved WhiteBook context: none found.

            User question:
            \(userQuestion)
            """
        }

        let contextText = chunks.enumerated().map { index, chunk in
            let headingLine = chunk.headingContext.map { "Section: \($0)\n" } ?? ""
            return """
            [Chunk \(index + 1)]
            \(headingLine)\(chunk.textContent)
            """
        }.joined(separator: "\n\n")

        return """
        Retrieved WhiteBook context:
        \(contextText)

        User question:
        \(userQuestion)
        """
    }

    private static let systemPrompt = """
    You are WhiteBook, an assistant that answers by prioritizing retrieved MGH WhiteBook excerpts.
    If context is partial or missing, state that clearly and provide a concise best-effort response.
    Keep responses brief, actionable, and in Markdown.
    """
}

private struct ChatCompletionsRequest: Encodable {
    let model: String
    let messages: [ChatCompletionMessage]
    let temperature: Double
}

private struct ChatCompletionMessage: Codable {
    let role: String
    let content: String?
}

private struct ChatCompletionsResponse: Decodable {
    let choices: [Choice]

    struct Choice: Decodable {
        let message: ChatCompletionMessage
    }
}

private struct GroqErrorEnvelope: Decodable {
    let error: GroqErrorDetail
}

private struct GroqErrorDetail: Decodable {
    let message: String
}
