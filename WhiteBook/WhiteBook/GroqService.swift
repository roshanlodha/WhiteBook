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

    func complete(
        userQuestion: String,
        context: [RetrievedChunk],
        toolsMode: Bool,
        thinkingMode: Bool
    ) async throws -> String {
        var combined = ""
        for try await token in streamCompletion(
            userQuestion: userQuestion,
            context: context,
            toolsMode: toolsMode,
            thinkingMode: thinkingMode
        ) {
            combined += token
        }
        let trimmed = combined.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            throw GroqServiceError.invalidResponse
        }
        return trimmed
    }

    func streamCompletion(
        userQuestion: String,
        context: [RetrievedChunk],
        toolsMode: Bool,
        thinkingMode: Bool
    ) -> AsyncThrowingStream<String, Error> {
        AsyncThrowingStream { continuation in
            Task {
                do {
                    var request = try makeChatRequest(
                        userQuestion: userQuestion,
                        context: context,
                        toolsMode: toolsMode,
                        thinkingMode: thinkingMode,
                        stream: true
                    )
                    request.timeoutInterval = 120
                    let (bytes, response) = try await URLSession.shared.bytes(for: request)
                    guard let httpResponse = response as? HTTPURLResponse else {
                        throw GroqServiceError.invalidResponse
                    }
                    guard (200...299).contains(httpResponse.statusCode) else {
                        var data = Data()
                        for try await byte in bytes {
                            data.append(byte)
                        }
                        let apiError = try? JSONDecoder().decode(GroqErrorEnvelope.self, from: data)
                        throw GroqServiceError.upstreamError(
                            apiError?.error.message ?? "Groq request failed with status \(httpResponse.statusCode)."
                        )
                    }

                    for try await line in bytes.lines {
                        guard line.hasPrefix("data:") else { continue }
                        let payload = String(line.dropFirst(5)).trimmingCharacters(in: .whitespaces)
                        if payload == "[DONE]" {
                            break
                        }
                        guard let data = payload.data(using: .utf8) else { continue }
                        let chunk = try? JSONDecoder().decode(ChatCompletionChunk.self, from: data)
                        if let content = chunk?.choices.first?.delta.content, !content.isEmpty {
                            continuation.yield(content)
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
        }
    }

    private func makeChatRequest(
        userQuestion: String,
        context: [RetrievedChunk],
        toolsMode: Bool,
        thinkingMode: Bool,
        stream: Bool
    ) throws -> URLRequest {
        let endpoint = URL(string: "https://api.groq.com/openai/v1/chat/completions")!
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("Bearer \(apiKey)", forHTTPHeaderField: "Authorization")

        let prompt = Self.makeContextPrompt(userQuestion: userQuestion, chunks: context)
        let body = ChatCompletionsRequest(
            model: model,
            messages: [
                .init(
                    role: "system",
                    content: Self.systemPrompt(
                        toolsMode: toolsMode,
                        thinkingMode: thinkingMode
                    )
                ),
                .init(role: "user", content: prompt)
            ],
            temperature: 0.2,
            stream: stream
        )

        request.httpBody = try JSONEncoder().encode(body)
        return request
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

    private static func systemPrompt(toolsMode: Bool, thinkingMode: Bool) -> String {
        var sections: [String] = [
            "You are WhiteBook, an assistant that answers by prioritizing retrieved MGH WhiteBook excerpts.",
            "If context is partial or missing, state that clearly and provide a concise best-effort response.",
            """
            Formatting rules for every answer:
            - Use clean Markdown with short sections and blank lines between sections.
            - When listing differential diagnoses, causes, or steps, use bullet points (one item per line).
            - Never output run-on lists or glued words; include normal spacing and punctuation.
            - Prefer this structure: concise answer first, then key considerations, then next steps if relevant.
            """
        ]

        if toolsMode {
            sections.append(
                "Calculator tooling is unavailable in this iOS build; if numeric reasoning is requested, provide careful manual calculations and clearly mark any assumptions."
            )
        }

        if thinkingMode {
            sections.append(
                "Add any intermediate reasoning inside <think>...</think> tags. Put only the final user-facing answer outside these tags."
            )
        } else {
            sections.append("Do not emit <think> tags unless explicitly requested by the user.")
        }

        return sections.joined(separator: "\n")
    }
}

private struct ChatCompletionsRequest: Encodable {
    let model: String
    let messages: [ChatCompletionMessage]
    let temperature: Double
    let stream: Bool
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

private struct ChatCompletionChunk: Decodable {
    let choices: [Choice]

    struct Choice: Decodable {
        let delta: Delta
    }

    struct Delta: Decodable {
        let content: String?
    }
}

private struct GroqErrorEnvelope: Decodable {
    let error: GroqErrorDetail
}

private struct GroqErrorDetail: Decodable {
    let message: String
}
