import Foundation

enum ChatRole {
    case user
    case assistant
}

struct RetrievedChunk: Identifiable {
    let id: String
    let headingContext: String?
    let textContent: String
    let pageStart: Int?
    let pageEnd: Int?
}

struct ChatMessage: Identifiable {
    let id = UUID()
    let role: ChatRole
    let text: String
    let sources: [RetrievedChunk]
}
