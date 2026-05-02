import SwiftUI
import WebKit

// MARK: - Markdown → HTML conversion (pure Swift, no dependencies)

enum MarkdownRenderer {
    /// Convert a markdown string to a styled HTML document suitable for WKWebView.
    static func htmlDocument(from markdown: String, colorScheme: ColorScheme) -> String {
        let html = markdownToHTML(markdown)
        return wrapInDocument(body: html, colorScheme: colorScheme)
    }

    // MARK: – Markdown → HTML

    private static func markdownToHTML(_ input: String) -> String {
        let normalized = input
            .replacingOccurrences(of: "\r\n", with: "\n")
            .replacingOccurrences(of: "\r", with: "\n")
            .replacingOccurrences(of: "\u{00A0}", with: " ")

        // Protect fenced code blocks.
        var protectedBlocks: [String] = []
        let codeBlockPattern = try! NSRegularExpression(pattern: #"```(\w*)\n([\s\S]*?)```"#)
        let nsNormalized = normalized as NSString
        let codeMatches = codeBlockPattern.matches(in: normalized, range: NSRange(location: 0, length: nsNormalized.length))

        var withPlaceholders = normalized
        for match in codeMatches.reversed() {
            guard let fullRange = Range(match.range, in: withPlaceholders),
                  let langRange = Range(match.range(at: 1), in: withPlaceholders),
                  let codeRange = Range(match.range(at: 2), in: withPlaceholders) else { continue }
            let lang = String(withPlaceholders[langRange])
            let code = String(withPlaceholders[codeRange])
                .replacingOccurrences(of: "&", with: "&amp;")
                .replacingOccurrences(of: "<", with: "&lt;")
                .replacingOccurrences(of: ">", with: "&gt;")
            let rendered = "<pre><code class=\"language-\(lang)\">\(code)</code></pre>"
            protectedBlocks.insert(rendered, at: 0)
            let placeholder = "\u{0000}CODEBLOCK\(protectedBlocks.count - 1)\u{0000}"
            withPlaceholders.replaceSubrange(fullRange, with: placeholder)
        }

        // Process line by line.
        let lines = withPlaceholders.split(separator: "\n", omittingEmptySubsequences: false).map(String.init)
        var htmlLines: [String] = []
        var inList = false
        var listType = "" // "ul" or "ol"
        var pendingParagraph: [String] = []

        func flushParagraph() {
            if !pendingParagraph.isEmpty {
                let text = pendingParagraph.joined(separator: " ")
                htmlLines.append("<p>\(inlineMarkdown(text))</p>")
                pendingParagraph.removeAll()
            }
        }

        func closeList() {
            if inList {
                htmlLines.append("</\(listType)>")
                inList = false
                listType = ""
            }
        }

        for line in lines {
            let trimmed = line.trimmingCharacters(in: .whitespaces)

            // Empty line
            if trimmed.isEmpty {
                flushParagraph()
                closeList()
                continue
            }

            // Protected code block placeholder
            if trimmed.hasPrefix("\u{0000}CODEBLOCK") {
                flushParagraph()
                closeList()
                htmlLines.append(trimmed)
                continue
            }

            // Headings
            if let headingMatch = trimmed.prefixHeading() {
                flushParagraph()
                closeList()
                let (level, text) = headingMatch
                htmlLines.append("<h\(level)>\(inlineMarkdown(text))</h\(level)>")
                continue
            }

            // Unordered list items
            if let bulletText = trimmed.prefixBullet() {
                flushParagraph()
                if !inList || listType != "ul" {
                    closeList()
                    htmlLines.append("<ul>")
                    inList = true
                    listType = "ul"
                }
                htmlLines.append("<li>\(inlineMarkdown(bulletText))</li>")
                continue
            }

            // Ordered list items
            if let orderedText = trimmed.prefixOrdered() {
                flushParagraph()
                if !inList || listType != "ol" {
                    closeList()
                    htmlLines.append("<ol>")
                    inList = true
                    listType = "ol"
                }
                htmlLines.append("<li>\(inlineMarkdown(orderedText))</li>")
                continue
            }

            // Horizontal rule
            if trimmed == "---" || trimmed == "***" || trimmed == "___" {
                flushParagraph()
                closeList()
                htmlLines.append("<hr>")
                continue
            }

            // Regular text → accumulate into paragraph
            closeList()
            pendingParagraph.append(trimmed)
        }

        flushParagraph()
        closeList()

        var result = htmlLines.joined(separator: "\n")

        // Restore code blocks
        for (index, block) in protectedBlocks.enumerated() {
            result = result.replacingOccurrences(of: "\u{0000}CODEBLOCK\(index)\u{0000}", with: block)
        }

        return result
    }

    private static func inlineMarkdown(_ text: String) -> String {
        var result = text
            .replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")

        // Bold: **text** or __text__
        result = result.replacingOccurrences(
            of: #"\*\*(.+?)\*\*"#,
            with: "<strong>$1</strong>",
            options: .regularExpression
        )
        result = result.replacingOccurrences(
            of: #"__(.+?)__"#,
            with: "<strong>$1</strong>",
            options: .regularExpression
        )

        // Italic: *text* or _text_ (but not inside words for underscores)
        result = result.replacingOccurrences(
            of: #"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)"#,
            with: "<em>$1</em>",
            options: .regularExpression
        )
        result = result.replacingOccurrences(
            of: #"(?<![a-zA-Z0-9])_(?!_)(.+?)(?<!_)_(?![a-zA-Z0-9])"#,
            with: "<em>$1</em>",
            options: .regularExpression
        )

        // Inline code: `text`
        result = result.replacingOccurrences(
            of: #"`([^`]+)`"#,
            with: "<code>$1</code>",
            options: .regularExpression
        )

        // Links: [text](url)
        result = result.replacingOccurrences(
            of: #"\[([^\]]+)\]\(([^)]+)\)"#,
            with: "<a href=\"$2\">$1</a>",
            options: .regularExpression
        )

        return result
    }

    // MARK: – HTML document wrapper

    private static func wrapInDocument(body: String, colorScheme: ColorScheme) -> String {
        let isDark = colorScheme == .dark
        let bg = isDark ? "#000000" : "#ffffff"
        let fg = isDark ? "#e5e5e5" : "#1a1a1a"
        let fgSecondary = isDark ? "#a0a0a0" : "#555555"
        let codeBg = isDark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.05)"
        let preBg = isDark ? "rgba(255,255,255,0.06)" : "#f6f8fa"
        let borderColor = isDark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.1)"
        let linkColor = isDark ? "#60a5fa" : "#2563eb"
        let hrColor = isDark ? "rgba(255,255,255,0.1)" : "rgba(0,0,0,0.1)"
        let strongColor = isDark ? "#ffffff" : "#000000"

        return """
        <!DOCTYPE html>
        <html>
        <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
        <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html, body {
            background: \(bg);
            color: \(fg);
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", system-ui, sans-serif;
            font-size: 15px;
            line-height: 1.65;
            -webkit-text-size-adjust: 100%;
            overflow-x: hidden;
            word-wrap: break-word;
            overflow-wrap: break-word;
        }
        body { padding: 0; }

        h1, h2, h3, h4, h5, h6 {
            color: \(strongColor);
            font-weight: 600;
            margin-top: 1em;
            margin-bottom: 0.4em;
            line-height: 1.3;
        }
        h1 { font-size: 1.4em; }
        h2 { font-size: 1.25em; }
        h3 { font-size: 1.12em; }
        h4 { font-size: 1.05em; }
        h5, h6 { font-size: 1em; }
        h1:first-child, h2:first-child, h3:first-child { margin-top: 0; }

        p {
            margin-bottom: 0.7em;
            line-height: 1.65;
        }
        p:last-child { margin-bottom: 0; }

        strong { color: \(strongColor); font-weight: 600; }
        em { font-style: italic; }

        ul, ol {
            margin: 0.5em 0 0.8em 0;
            padding-left: 1.4em;
        }
        li {
            margin-bottom: 0.35em;
            line-height: 1.55;
        }
        li:last-child { margin-bottom: 0; }
        ul li { list-style-type: disc; }
        ul li li { list-style-type: circle; }
        ol li { list-style-type: decimal; }

        code {
            font-family: "SF Mono", Menlo, Consolas, monospace;
            font-size: 0.88em;
            background: \(codeBg);
            padding: 0.15em 0.35em;
            border-radius: 4px;
        }

        pre {
            background: \(preBg);
            border: 1px solid \(borderColor);
            border-radius: 8px;
            padding: 12px 14px;
            margin: 0.7em 0;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
        }
        pre code {
            background: none;
            padding: 0;
            font-size: 0.85em;
            line-height: 1.5;
        }

        hr {
            border: none;
            border-top: 1px solid \(hrColor);
            margin: 1em 0;
        }

        a {
            color: \(linkColor);
            text-decoration: none;
        }

        table {
            border-collapse: collapse;
            width: 100%;
            margin: 0.7em 0;
            font-size: 0.9em;
        }
        th, td {
            border: 1px solid \(borderColor);
            padding: 6px 10px;
            text-align: left;
        }
        th {
            background: \(codeBg);
            font-weight: 600;
        }

        blockquote {
            border-left: 3px solid \(linkColor);
            margin: 0.7em 0;
            padding: 0.3em 0 0.3em 1em;
            color: \(fgSecondary);
        }
        </style>
        </head>
        <body>
        \(body)
        <script>
        // Post the content height so SwiftUI can size the container.
        function postHeight() {
            const h = document.body.scrollHeight;
            window.webkit.messageHandlers.heightChange.postMessage(h);
        }
        new ResizeObserver(postHeight).observe(document.body);
        window.addEventListener('load', postHeight);
        postHeight();
        </script>
        </body>
        </html>
        """
    }
}

// MARK: – String helpers

private extension String {
    func prefixHeading() -> (Int, String)? {
        let trimmed = self.trimmingCharacters(in: .whitespaces)
        var level = 0
        for char in trimmed {
            if char == "#" { level += 1 } else { break }
        }
        guard level >= 1, level <= 6 else { return nil }
        let rest = String(trimmed.dropFirst(level)).trimmingCharacters(in: .whitespaces)
        guard !rest.isEmpty else { return nil }
        return (level, rest)
    }

    func prefixBullet() -> String? {
        let trimmed = self.trimmingCharacters(in: .whitespaces)
        if trimmed.hasPrefix("- ") { return String(trimmed.dropFirst(2)) }
        if trimmed.hasPrefix("* ") { return String(trimmed.dropFirst(2)) }
        if trimmed.hasPrefix("• ") { return String(trimmed.dropFirst(2)) }
        return nil
    }

    func prefixOrdered() -> String? {
        let trimmed = self.trimmingCharacters(in: .whitespaces)
        guard let dotIndex = trimmed.firstIndex(of: "."),
              dotIndex > trimmed.startIndex,
              dotIndex < trimmed.index(before: trimmed.endIndex) else { return nil }
        let prefix = String(trimmed[..<dotIndex])
        guard prefix.allSatisfy(\.isNumber), prefix.count <= 3 else { return nil }
        let afterDot = trimmed.index(after: dotIndex)
        guard trimmed[afterDot] == " " else { return nil }
        return String(trimmed[trimmed.index(after: afterDot)...])
    }
}

// MARK: – WKWebView SwiftUI wrapper

struct MarkdownWebView: UIViewRepresentable {
    let markdown: String
    let colorScheme: ColorScheme
    @Binding var dynamicHeight: CGFloat

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.userContentController.add(context.coordinator, name: "heightChange")

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.backgroundColor = .clear
        webView.scrollView.isScrollEnabled = false
        webView.scrollView.bounces = false
        webView.navigationDelegate = context.coordinator

        // Disable link previews and long-press menus.
        webView.allowsLinkPreview = false

        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        let html = MarkdownRenderer.htmlDocument(from: markdown, colorScheme: colorScheme)
        let currentHash = html.hashValue
        if context.coordinator.lastHTMLHash != currentHash {
            context.coordinator.lastHTMLHash = currentHash
            webView.loadHTMLString(html, baseURL: nil)
        }
    }

    @MainActor
    class Coordinator: NSObject, WKScriptMessageHandler, WKNavigationDelegate {
        let parent: MarkdownWebView
        var lastHTMLHash: Int?

        init(parent: MarkdownWebView) {
            self.parent = parent
        }

        nonisolated func userContentController(
            _ userContentController: WKUserContentController,
            didReceive message: WKScriptMessage
        ) {
            guard let height = message.body as? CGFloat, height > 0 else { return }
            Task { @MainActor in
                if abs(self.parent.dynamicHeight - height) > 1 {
                    self.parent.dynamicHeight = height
                }
            }
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                      decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            if navigationAction.navigationType == .linkActivated, let url = navigationAction.request.url {
                UIApplication.shared.open(url)
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
        }
    }
}
