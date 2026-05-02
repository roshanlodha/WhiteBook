//
//  ContentView.swift
//  WhiteBook
//
//  Created by Roshan Lodha on 5/2/26.
//

import SwiftUI
import UIKit

struct ContentView: View {
    @StateObject private var viewModel = ChatViewModel()
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if viewModel.messages.isEmpty {
                    ContentUnavailableView(
                        "Ask WhiteBook",
                        systemImage: "book.closed",
                        description: Text("Clinical context is retrieved from your bundled SQLite database, then answered by Groq.")
                    )
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    ScrollViewReader { proxy in
                        ScrollView {
                            LazyVStack(alignment: .leading, spacing: 4) {
                                ForEach(viewModel.messages) { message in
                                    MessageBubble(message: message)
                                        .id(message.id)
                                }
                            }
                            .frame(maxWidth: 720, alignment: .leading)
                            .padding(.horizontal, 16)
                            .padding(.top, 36)
                            .padding(.bottom, 100)
                        }
                        .scrollDismissesKeyboard(.interactively)
                        .onTapGesture {
                            UIApplication.shared.sendAction(
                                #selector(UIResponder.resignFirstResponder),
                                to: nil,
                                from: nil,
                                for: nil
                            )
                        }
                        .scrollContentBackground(.hidden)
                        .background(AppTheme.background(for: colorScheme))
                        .onChange(of: viewModel.messages.count) { _, _ in
                            if let lastID = viewModel.messages.last?.id {
                                withAnimation(.easeOut(duration: 0.25)) {
                                    proxy.scrollTo(lastID, anchor: .bottom)
                                }
                            }
                        }
                        .onChange(of: viewModel.streamVersion) { _, _ in
                            if let lastID = viewModel.messages.last?.id {
                                proxy.scrollTo(lastID, anchor: .bottom)
                            }
                        }
                    }
                }

                Divider()

                ModeTogglesRow(
                    isToolsModeActive: $viewModel.isToolsModeActive,
                    isThinkingModeActive: $viewModel.isThinkingModeActive
                )
                .padding(.horizontal)
                .padding(.top, 10)
                .padding(.bottom, 6)

                HStack(alignment: .bottom, spacing: 8) {
                    TextField(viewModel.draftPlaceholder, text: $viewModel.draft, axis: .vertical)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 10)
                        .background(AppTheme.composerFieldBackground(for: colorScheme))
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                        .lineLimit(1...5)
                        .disabled(viewModel.isLoading)
                        .foregroundStyle(AppTheme.primaryText(for: colorScheme))

                    Button {
                        Task { await viewModel.send() }
                    } label: {
                        if viewModel.isLoading {
                            ProgressView()
                                .controlSize(.small)
                                .frame(width: 24, height: 24)
                        } else {
                            Image(systemName: "paperplane.fill")
                                .frame(width: 24, height: 24)
                        }
                    }
                    .buttonStyle(.plain)
                    .foregroundStyle(AppTheme.sendButtonForeground(for: colorScheme))
                    .padding(10)
                    .background(AppTheme.sendButtonBackground(for: colorScheme))
                    .clipShape(Circle())
                    .disabled(viewModel.isLoading || viewModel.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                .padding()
                .background(AppTheme.composerBackground(for: colorScheme))
            }
            .background(AppTheme.background(for: colorScheme))
            .navigationTitle("WhiteBook")
            .toolbarBackground(AppTheme.background(for: colorScheme), for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Clear") {
                        viewModel.clear()
                    }
                    .disabled(viewModel.messages.isEmpty || viewModel.isLoading)
                }
            }
            .alert("Request failed", isPresented: $viewModel.showingError, actions: {
                Button("OK", role: .cancel) {}
            }, message: {
                Text(viewModel.errorMessage)
            })
        }
    }
}

// MARK: - Message Bubble

private struct MessageBubble: View {
    let message: ChatMessage
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                if message.role == .assistant {
                    Text("WhiteBook")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.secondary)
                    Spacer()
                } else {
                    Spacer()
                    Text("You")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.secondary)
                }
            }

            if message.role == .assistant {
                if let think = message.thinkContent, !think.isEmpty {
                    CollapsibleMetaBlock(title: "thinking...", content: think)
                }

                ForEach(Array(message.toolResults.enumerated()), id: \.offset) { _, toolResult in
                    CollapsibleMetaBlock(title: "calculating...", content: toolResult)
                }

                RichMarkdownBubble(text: message.text)
                    .frame(maxWidth: 680, alignment: .leading)

                if !message.sources.isEmpty {
                    SourcesButton(sources: message.sources)
                        .frame(maxWidth: 680, alignment: .leading)
                }
            } else {
                HStack {
                    Spacer(minLength: 36)
                    Text(message.text)
                        .font(.system(size: 15, weight: .medium))
                        .lineSpacing(2)
                        .padding(.vertical, 11)
                        .padding(.horizontal, 14)
                        .foregroundStyle(AppTheme.userBubbleForeground(for: colorScheme))
                        .background(AppTheme.userBubbleBackground(for: colorScheme))
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                }
            }
        }
        .padding(.bottom, 18)
    }
}

// MARK: - Rich Markdown Bubble (WKWebView-backed)

private struct RichMarkdownBubble: View {
    let text: String
    @State private var webViewHeight: CGFloat = 60
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        let normalized = MarkdownNormalizer.normalize(text)
        MarkdownWebView(
            markdown: normalized,
            colorScheme: colorScheme,
            dynamicHeight: $webViewHeight
        )
        .frame(height: max(webViewHeight, 20))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .padding(14)
        .background(AppTheme.assistantBubbleBackground(for: colorScheme))
        .clipShape(RoundedRectangle(cornerRadius: 12))
    }
}

// MARK: - Sources Button (prominent, always visible)

private struct SourcesButton: View {
    let sources: [RetrievedChunk]
    @State private var showSourceSheet = false
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        Button {
            showSourceSheet = true
        } label: {
            HStack(spacing: 8) {
                Image(systemName: "doc.text.magnifyingglass")
                    .font(.system(size: 14, weight: .semibold))
                Text("Show Sources (\(sources.count))")
                    .font(.system(size: 14, weight: .semibold))
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.tertiary)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .foregroundStyle(AppTheme.sourceButtonForeground(for: colorScheme))
            .background(AppTheme.sourceButtonBackground(for: colorScheme))
            .clipShape(RoundedRectangle(cornerRadius: 12))
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(AppTheme.sourceButtonBorder(for: colorScheme), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        .sheet(isPresented: $showSourceSheet) {
            SourcesSheet(sources: sources)
        }
    }
}

// MARK: - Sources Sheet (full modal with PDF pages)

private struct SourcesSheet: View {
    let sources: [RetrievedChunk]
    @Environment(\.dismiss) private var dismiss
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(spacing: 16) {
                    ForEach(Array(sources.enumerated()), id: \.element.id) { index, source in
                        NavigationLink {
                            if let pageNumber = source.pageStart {
                                PDFPageDetailView(pageNumber: pageNumber)
                            } else {
                                Text("No page number available for this source.")
                                    .padding()
                            }
                        } label: {
                            SourceRow(source: source, index: index + 1)
                        }
                        .buttonStyle(.plain)
                        .disabled(source.pageStart == nil)
                        .opacity(source.pageStart == nil ? 0.7 : 1.0)
                    }
                }
                .padding()
            }
            .background(AppTheme.background(for: colorScheme))
            .navigationTitle("Sources")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

// MARK: - Source Row (in the sources sheet)

private struct SourceRow: View {
    let source: RetrievedChunk
    let index: Int
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        HStack(spacing: 14) {
            // PDF thumbnail
            if let pageNumber = source.pageStart {
                PDFThumbnailView(pageNumber: pageNumber)
                    .frame(width: 70, height: 90)
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .shadow(color: .black.opacity(0.1), radius: 2, y: 1)
            } else {
                RoundedRectangle(cornerRadius: 8)
                    .fill(AppTheme.metaBlockBackground(for: colorScheme))
                    .frame(width: 70, height: 90)
                    .overlay {
                        Image(systemName: "doc.text")
                            .foregroundStyle(.secondary)
                    }
            }

            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text("Source \(index)")
                        .font(.system(size: 13, weight: .bold))

                    Spacer()

                    if let pageStart = source.pageStart {
                        if let pageEnd = source.pageEnd, pageEnd != pageStart {
                            Text("pp. \(pageStart)–\(pageEnd)")
                                .font(.system(size: 12, weight: .medium))
                                .foregroundStyle(.secondary)
                        } else {
                            Text("p. \(pageStart)")
                                .font(.system(size: 12, weight: .medium))
                                .foregroundStyle(.secondary)
                        }
                    }
                }

                if let heading = source.headingContext, !heading.isEmpty {
                    Text(heading)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(.primary)
                        .lineLimit(2)
                }

                Text(source.textContent)
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if source.pageStart != nil {
                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(12)
        .background(AppTheme.sourceCardBackground(for: colorScheme))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(AppTheme.sourceButtonBorder(for: colorScheme), lineWidth: 0.5)
        )
    }
}

// MARK: - Collapsible Meta Block (thinking/calculating)

private struct CollapsibleMetaBlock: View {
    let title: String
    let content: String
    @State private var isExpanded = false
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        DisclosureGroup(isExpanded: $isExpanded) {
            Text(content)
                .font(.system(size: 13))
                .foregroundStyle(.secondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.top, 4)
                .textSelection(.enabled)
        } label: {
            Text(title)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 9)
        .background(AppTheme.metaBlockBackground(for: colorScheme))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }
}

// MARK: - Mode Toggles

private struct ModeTogglesRow: View {
    @Binding var isToolsModeActive: Bool
    @Binding var isThinkingModeActive: Bool

    var body: some View {
        HStack(spacing: 10) {
            ToggleChip(
                title: "Calculate",
                systemImage: "plus.forwardslash.minus",
                isOn: $isToolsModeActive,
                activeColor: .blue
            )

            ToggleChip(
                title: "Thinking",
                systemImage: "brain.head.profile",
                isOn: $isThinkingModeActive,
                activeColor: .purple
            )

            Spacer(minLength: 0)
        }
    }
}

private struct ToggleChip: View {
    let title: String
    let systemImage: String
    @Binding var isOn: Bool
    let activeColor: Color
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        Button {
            isOn.toggle()
        } label: {
            HStack(spacing: 6) {
                Image(systemName: systemImage)
                    .font(.system(size: 13, weight: .semibold))
                Text(title)
                    .font(.system(size: 13, weight: .semibold))
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 6)
            .foregroundStyle(isOn ? Color.white : Color.secondary)
            .background(
                Capsule()
                    .fill(isOn ? activeColor : AppTheme.chipInactiveBackground(for: colorScheme))
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
        .accessibilityValue(isOn ? "On" : "Off")
    }
}

// MARK: - Theme

private enum AppTheme {
    static func background(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color.black : Color.white
    }

    static func primaryText(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color.white : Color.black
    }

    static func assistantBubbleBackground(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color.white.opacity(0.06) : Color(.secondarySystemBackground)
    }

    static func userBubbleBackground(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color.blue.opacity(0.7) : Color.blue.opacity(0.9)
    }

    static func userBubbleForeground(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color.white : Color.white
    }

    static func metaBlockBackground(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color.white.opacity(0.08) : Color(.tertiarySystemBackground)
    }

    static func sourceCardBackground(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color.white.opacity(0.08) : Color(.tertiarySystemBackground)
    }

    static func chipInactiveBackground(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color.white.opacity(0.12) : Color(.systemGray5)
    }

    static func composerBackground(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color.black : Color.white
    }

    static func composerFieldBackground(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color.white.opacity(0.08) : Color(.systemGray6)
    }

    static func sendButtonBackground(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color.white.opacity(0.14) : Color.black.opacity(0.06)
    }

    static func sendButtonForeground(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color.white : Color.black
    }

    static func sourceButtonBackground(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color.blue.opacity(0.12) : Color.blue.opacity(0.06)
    }

    static func sourceButtonForeground(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color.blue.opacity(0.9) : Color.blue.opacity(0.85)
    }

    static func sourceButtonBorder(for scheme: ColorScheme) -> Color {
        scheme == .dark ? Color.blue.opacity(0.2) : Color.blue.opacity(0.15)
    }
}

#Preview {
    ContentView()
}
