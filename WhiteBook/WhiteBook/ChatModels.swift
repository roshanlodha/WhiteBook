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
    let thinkContent: String?
    let toolResults: [String]
    let sources: [RetrievedChunk]
}

struct ParsedAssistantContent {
    let answer: String
    let think: String?
    let tools: [String]

    static func parse(_ rawText: String) -> ParsedAssistantContent {
        let tags: [(name: String, open: String, close: String)] = [
            ("think", "<think>", "</think>"),
            ("tool", "<tool_result>", "</tool_result>")
        ]

        var remaining = rawText
        var activeTag: String? = nil
        var answer = ""
        var think = ""
        var tools: [String] = []
        var currentTool = ""

        func append(_ text: String, mode: String?) {
            guard !text.isEmpty else { return }
            switch mode {
            case "think":
                think += text
            case "tool":
                currentTool += text
            default:
                answer += text
            }
        }

        while !remaining.isEmpty {
            if activeTag == nil {
                var earliestIndex = remaining.endIndex
                var selectedTag: (name: String, open: String, close: String)?
                for tag in tags {
                    if let idx = remaining.range(of: tag.open)?.lowerBound, idx < earliestIndex {
                        earliestIndex = idx
                        selectedTag = tag
                    }
                }

                guard let tag = selectedTag else {
                    append(remaining, mode: nil)
                    break
                }

                append(String(remaining[..<earliestIndex]), mode: nil)
                let afterOpen = remaining.index(earliestIndex, offsetBy: tag.open.count)
                remaining = String(remaining[afterOpen...])
                activeTag = tag.name
                continue
            }

            guard let tag = tags.first(where: { $0.name == activeTag }) else {
                append(remaining, mode: nil)
                break
            }

            if let closeRange = remaining.range(of: tag.close) {
                append(String(remaining[..<closeRange.lowerBound]), mode: activeTag)
                remaining = String(remaining[closeRange.upperBound...])
                if activeTag == "tool" {
                    let trimmed = currentTool.trimmingCharacters(in: .whitespacesAndNewlines)
                    if !trimmed.isEmpty {
                        tools.append(trimmed)
                    }
                    currentTool = ""
                }
                activeTag = nil
            } else {
                append(remaining, mode: activeTag)
                break
            }
        }

        var answerText = answer.trimmingCharacters(in: .whitespacesAndNewlines)
        answerText = answerText.replacingOccurrences(of: #"^#+\s*(?:\*\*)?(?:Answer)?(?:\*\*)?\s*"#, with: "", options: .regularExpression).trimmingCharacters(in: .whitespacesAndNewlines)
        let thinkText = think.trimmingCharacters(in: .whitespacesAndNewlines)
        let trailingTool = currentTool.trimmingCharacters(in: .whitespacesAndNewlines)
        if !trailingTool.isEmpty {
            tools.append(trailingTool)
        }

        return ParsedAssistantContent(
            answer: answerText,
            think: thinkText.isEmpty ? nil : thinkText,
            tools: tools
        )
    }
}

enum MarkdownNormalizer {
    static func normalize(_ input: String) -> String {
        var text = input
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
            .replacingOccurrences(of: "\u{00A0}", with: " ")

        if text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return ""
        }

        // Preserve fenced code blocks before text rewrites.
        var protectedBlocks: [String] = []
        text = replacingMatches(in: text, pattern: #"(?:```[\s\S]*?```|~~~[\s\S]*?~~~)"#) { match in
            let token = "\u{0000}WBPRO\(protectedBlocks.count)\u{0000}"
            protectedBlocks.append(match)
            return token
        }

        // 1) Inline numbered lists become real list lines.
        text = text.replacingOccurrences(
            of: #"([^\n])\s*(\d{1,2}\.\s+(?=[A-Z(*_]))"#,
            with: "$1\n$2",
            options: .regularExpression
        )
        text = text.replacingOccurrences(
            of: #"([^\n])\s*(#{1,6}\s+)"#,
            with: "$1\n$2",
            options: .regularExpression
        )

        // 2) Mid-line bullets become new bullet lines.
        text = text.replacingOccurrences(
            of: #"([.;:!?])\s*-\s+(?=[A-Z(*_])"#,
            with: "$1\n- ",
            options: .regularExpression
        )
        text = text.replacingOccurrences(
            of: #"([.;:!?])\s*•\s+(?=[A-Z(*_])"#,
            with: "$1\n- ",
            options: .regularExpression
        )
        text = text.replacingOccurrences(
            of: #"([^\n])\s*[•*]\s+(?=[A-Z(*_])"#,
            with: "$1\n- ",
            options: .regularExpression
        )
        text = text.replacingOccurrences(
            of: #"([^\n])\s*(?:-\s+)(?=[A-Z(*_])"#,
            with: "$1\n- ",
            options: .regularExpression
        )

        // 3) Restore missing spaces around sentence boundaries and labels.
        text = text.replacingOccurrences(
            of: #"([)\].!?])(?=(\*\*)?[A-Z(])"#,
            with: "$1 ",
            options: .regularExpression
        )
        text = text.replacingOccurrences(
            of: #"([:;])(?=[A-Z])"#,
            with: "$1 ",
            options: .regularExpression
        )
        text = text.replacingOccurrences(
            of: #"([a-z0-9\)])([A-Z])"#,
            with: "$1 $2",
            options: .regularExpression
        )

        // 4) Add boundaries around bold spans if model glues words together.
        text = text.replacingOccurrences(
            of: #"(\*\*[^*]+\*\*)(?=[A-Za-z0-9(])"#,
            with: "$1 ",
            options: .regularExpression
        )
        text = text.replacingOccurrences(
            of: #"([A-Za-z0-9\)])(?=\*\*[^*]+\*\*)"#,
            with: "$1 ",
            options: .regularExpression
        )

        // 5) If the model dumps a run-on line after a label, split into bullets.
        text = splitRunOnLabelLists(in: text)

        // 6) Cleanup whitespace while preserving markdown indentation.
        text = text.replacingOccurrences(
            of: #"[ \t]{2,}"#,
            with: " ",
            options: .regularExpression
        )
        text = text.replacingOccurrences(
            of: #"\n{3,}"#,
            with: "\n\n",
            options: .regularExpression
        )

        // Restore fenced code blocks.
        for (index, block) in protectedBlocks.enumerated() {
            text = text.replacingOccurrences(of: "\u{0000}WBPRO\(index)\u{0000}", with: block)
        }

        let lines = text.split(separator: "\n", omittingEmptySubsequences: false).map { line in
            line.replacingOccurrences(of: #"[ \t]+$"#, with: "", options: .regularExpression)
        }
        return lines.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func splitRunOnLabelLists(in text: String) -> String {
        let lines = text.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        var rebuilt: [String] = []

        for line in lines {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            guard
                let colonIndex = trimmed.firstIndex(of: ":"),
                colonIndex < trimmed.index(before: trimmed.endIndex)
            else {
                rebuilt.append(line)
                continue
            }

            let label = String(trimmed[..<colonIndex])
            let suffix = String(trimmed[trimmed.index(after: colonIndex)...]).trimmingCharacters(in: .whitespaces)

            // Only rewrite lines that look like run-on lists, not normal prose.
            if label.count < 4 || suffix.count < 24 || suffix.contains("\n") || suffix.contains("- ") || suffix.contains("1.") {
                rebuilt.append(line)
                continue
            }

            let pieces = suffix
                .replacingOccurrences(
                    of: #"([a-z\)])([A-Z])"#,
                    with: "$1\n$2",
                    options: .regularExpression
                )
                .split(separator: "\n")
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }

            if pieces.count >= 3 {
                rebuilt.append("\(label):")
                rebuilt.append(contentsOf: pieces.map { "- \($0)" })
            } else {
                rebuilt.append(line)
            }
        }

        return rebuilt.joined(separator: "\n")
    }

    private static func replacingMatches(
        in source: String,
        pattern: String,
        transform: (String) -> String
    ) -> String {
        guard let regex = try? NSRegularExpression(pattern: pattern, options: []) else {
            return source
        }
        let nsRange = NSRange(source.startIndex..<source.endIndex, in: source)
        let matches = regex.matches(in: source, options: [], range: nsRange)
        guard !matches.isEmpty else { return source }

        var result = source
        for match in matches.reversed() {
            guard let range = Range(match.range, in: result) else { continue }
            let fragment = String(result[range])
            result.replaceSubrange(range, with: transform(fragment))
        }
        return result
    }
}
