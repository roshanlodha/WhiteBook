//
//  ContentView.swift
//  WhiteBook
//
//  Created by Roshan Lodha on 4/27/26.
//

import SwiftUI

struct ContentView: View {
    @StateObject private var viewModel = AssistantViewModel()

    var body: some View {
        NavigationStack {
            VStack(spacing: 12) {
                HStack(alignment: .top, spacing: 10) {
                    TextField("Ask a clinical question", text: $viewModel.query, axis: .vertical)
                        .textFieldStyle(.roundedBorder)
                        .lineLimit(2...6)

                    Button(action: {
                        Task { await viewModel.ask() }
                    }) {
                        if viewModel.isGenerating {
                            ProgressView()
                                .frame(width: 22, height: 22)
                        } else {
                            Image(systemName: "paperplane.fill")
                                .font(.body.weight(.semibold))
                                .frame(width: 22, height: 22)
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(viewModel.query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isPreparingModel || viewModel.isGenerating)
                }

                HStack(spacing: 8) {
                    Text(viewModel.modelStatus)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                    Spacer()
                }

                if viewModel.isDownloadingModel {
                    VStack(alignment: .leading, spacing: 8) {
                        ProgressView(value: viewModel.downloadProgress, total: 1) {
                            Text("Model download")
                        } currentValueLabel: {
                            Text("\(Int((viewModel.downloadProgress * 100).rounded()))%")
                        }

                        HStack {
                            Spacer()
                            Button("Cancel Download") {
                                viewModel.cancelModelDownload()
                            }
                            .buttonStyle(.bordered)
                        }
                    }
                }

                ScrollView {
                    Text(viewModel.answerText.isEmpty ? "Generated answer will appear here." : viewModel.answerText)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(12)
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
                }

                if !viewModel.contextChunks.isEmpty {
                    List(viewModel.contextChunks) { chunk in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(chunk.heading_context)
                                .font(.headline)
                            Text(chunk.text_content)
                                .font(.subheadline)
                            Text("Pages \(chunk.page_start)-\(chunk.page_end)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            if let imageName = chunk.image_filename, !imageName.isEmpty {
                                Text("Image: \(imageName)")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                    .listStyle(.insetGrouped)
                    .frame(maxHeight: 220)
                }
            }
            .padding()
            .navigationTitle("WhiteBook AI")
            .task {
                viewModel.startPreparingModelIfNeeded()
            }
        }
    }
}

#Preview {
    ContentView()
}
