import SwiftUI
import PDFKit

struct PDFThumbnailView: View {
    let pageNumber: Int

    var body: some View {
        if let image = PDFSourceRenderer.thumbnail(forOneBasedPage: pageNumber) {
            Image(uiImage: image)
                .resizable()
                .scaledToFill()
        } else {
            ZStack {
                RoundedRectangle(cornerRadius: 8)
                    .fill(Color(.secondarySystemBackground))
                Image(systemName: "doc.richtext")
                    .font(.title3)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

struct PDFPageDetailView: View {
    let pageNumber: Int

    var body: some View {
        PDFKitView(pageNumber: pageNumber)
            .navigationTitle("Page \(pageNumber)")
            .navigationBarTitleDisplayMode(.inline)
    }
}

struct PDFKitView: UIViewRepresentable {
    let pageNumber: Int

    func makeUIView(context: Context) -> PDFView {
        let view = PDFView()
        view.autoScales = true
        view.displayMode = .singlePageContinuous
        view.displayDirection = .vertical
        return view
    }

    func updateUIView(_ uiView: PDFView, context: Context) {
        guard let document = PDFSourceRenderer.document else { return }
        uiView.document = document
        let index = max(0, pageNumber - 1)
        if let page = document.page(at: index) {
            uiView.go(to: page)
        }
    }
}

enum PDFSourceRenderer {
    static let document: PDFDocument? = {
        guard let url = Bundle.main.url(forResource: "WhiteBook", withExtension: "pdf") else {
            return nil
        }
        return PDFDocument(url: url)
    }()

    static func thumbnail(forOneBasedPage pageNumber: Int) -> UIImage? {
        guard let document,
              let page = document.page(at: max(0, pageNumber - 1))
        else {
            return nil
        }

        let bounds = page.bounds(for: .mediaBox)
        return page.thumbnail(of: CGSize(width: bounds.width * 0.22, height: bounds.height * 0.22), for: .mediaBox)
    }
}
