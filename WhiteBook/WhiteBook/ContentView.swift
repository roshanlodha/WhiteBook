//
//  ContentView.swift
//  WhiteBook
//
//  Created by Roshan Lodha on 5/2/26.
//

import SwiftUI

struct ContentView: View {
    @StateObject private var viewModel = ChatViewModel()

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if viewModel.messages.isEmpty {
                    ContentUnavailableView(
                        "Ask WhiteBook",
                        systemImage: "book.closed",
                        description: Text("Clinical context is retrieved from your bundled SQLite database, then answered by Groq.")
                    )
                } else {
                    ScrollViewReader { proxy in
                        ScrollView {
                            LazyVStack(alignment: .leading, spacing: 12) {
                                ForEach(viewModel.messages) { message in
                                    MessageBubble(message: message)
                                        .id(message.id)
                                }
                            }
                            .padding()
                        }
                        .onChange(of: viewModel.messages.count) { _, _ in
                            if let lastID = viewModel.messages.last?.id {
                                withAnimation(.easeOut(duration: 0.25)) {
                                    proxy.scrollTo(lastID, anchor: .bottom)
                                }
                            }
                        }
                    }
                }

                Divider()

                HStack(alignment: .bottom, spacing: 8) {
                    TextField("Ask a clinical question", text: $viewModel.draft, axis: .vertical)
                        .textFieldStyle(.roundedBorder)
                        .lineLimit(1...5)
                        .disabled(viewModel.isLoading)

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
                    .buttonStyle(.borderedProminent)
                    .disabled(viewModel.isLoading || viewModel.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
                .padding()
            }
            .navigationTitle("WhiteBook")
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

private struct MessageBubble: View {
    let message: ChatMessage

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                if message.role == .assistant {
                    Text("WhiteBook")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                } else {
                    Spacer()
                    Text("You")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Text(message.text)
                .padding(12)
                .frame(maxWidth: .infinity, alignment: message.role == .assistant ? .leading : .trailing)
                .background(message.role == .assistant ? Color(.secondarySystemBackground) : Color.accentColor.opacity(0.2))
                .clipShape(RoundedRectangle(cornerRadius: 12))

            if message.role == .assistant, !message.sources.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(message.sources) { source in
                            NavigationLink {
                                if let pageNumber = source.pageStart {
                                    PDFPageDetailView(pageNumber: pageNumber)
                                } else {
                                    Text("No page number available for this source.")
                                        .padding()
                                }
                            } label: {
                                SourceCard(source: source)
                            }
                            .buttonStyle(.plain)
                            .disabled(source.pageStart == nil)
                            .opacity(source.pageStart == nil ? 0.7 : 1.0)
                                .frame(width: 220)
                        }
                    }
                }
            }
        }
    }
}

private struct SourceCard: View {
    let source: RetrievedChunk

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let pageNumber = source.pageStart {
                PDFThumbnailView(pageNumber: pageNumber)
                    .frame(height: 90)
                    .clipped()
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            }

            if let heading = source.headingContext, !heading.isEmpty {
                Text(heading)
                    .font(.caption.weight(.semibold))
                    .lineLimit(2)
            }

            if let pageStart = source.pageStart {
                if let pageEnd = source.pageEnd, pageEnd != pageStart {
                    Text("Pages \(pageStart)-\(pageEnd)")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                } else {
                    Text("Page \(pageStart)")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.secondary)
                }
            }

            Text(source.textContent)
                .font(.caption2)
                .lineLimit(4)
        }
        .padding(8)
        .background(Color(.tertiarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 10))
    }
}

#Preview {
    ContentView()
}
