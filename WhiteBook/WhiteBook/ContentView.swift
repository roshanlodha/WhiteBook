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
                let pages = Array(Set(sources.compactMap { $0.pageStart })).sorted()
                let pagesText = pages.isEmpty ? "" : " (p. \(pages.map { String($0) }.joined(separator: ", ")))"
                Text("Show Source\(pagesText)")
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

// MARK: - Sources Sheet (Direct PDF Viewer)

private struct SourcesSheet: View {
    let sources: [RetrievedChunk]
    @State private var currentIndex = 0
    @Environment(\.dismiss) private var dismiss
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                let currentSource = sources.isEmpty ? nil : sources[currentIndex]

                if let pageNumber = currentSource?.pageStart {
                    PDFKitView(pageNumber: pageNumber)
                        .id(pageNumber)
                } else {
                    VStack(spacing: 12) {
                        Image(systemName: "doc.text")
                            .font(.system(size: 48))
                            .foregroundStyle(.tertiary)
                        Text("No page available for this source.")
                            .foregroundStyle(.secondary)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .background(AppTheme.background(for: colorScheme))
                }

                if sources.count > 1 {
                    Divider()
                    HStack {
                        Button {
                            withAnimation { currentIndex -= 1 }
                        } label: {
                            Image(systemName: "chevron.left")
                                .font(.system(size: 16, weight: .semibold))
                                .frame(width: 44, height: 44)
                        }
                        .disabled(currentIndex == 0)

                        Spacer()

                        VStack(spacing: 2) {
                            Text("Source \(currentIndex + 1) of \(sources.count)")
                                .font(.system(size: 13, weight: .semibold))
                            if let pageStart = currentSource?.pageStart {
                                Text("Page \(pageStart)")
                                    .font(.system(size: 11))
                                    .foregroundStyle(.secondary)
                            }
                        }

                        Spacer()

                        Button {
                            withAnimation { currentIndex += 1 }
                        } label: {
                            Image(systemName: "chevron.right")
                                .font(.system(size: 16, weight: .semibold))
                                .frame(width: 44, height: 44)
                        }
                        .disabled(currentIndex == sources.count - 1)
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 8)
                    .background(AppTheme.metaBlockBackground(for: colorScheme))
                }
            }
            .navigationTitle(sources.count <= 1 ? "Source Document" : "Source Viewer")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
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
