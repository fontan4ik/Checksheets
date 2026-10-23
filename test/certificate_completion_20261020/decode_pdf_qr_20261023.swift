import AppKit
import Foundation
import PDFKit
import Vision

let input = CommandLine.arguments[1]
guard let document = PDFDocument(url: URL(fileURLWithPath: input)) else {
    fatalError("cannot_open_pdf")
}
for index in 0..<document.pageCount {
    guard let page = document.page(at: index) else { continue }
    let bounds = page.bounds(for: .mediaBox)
    let image = page.thumbnail(of: CGSize(width: bounds.width * 3, height: bounds.height * 3), for: .mediaBox)
    var rect = CGRect(origin: .zero, size: image.size)
    guard let cgImage = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else { continue }
    let request = VNDetectBarcodesRequest()
    try VNImageRequestHandler(cgImage: cgImage).perform([request])
    for code in request.results ?? [] {
        print("page=\(index + 1) type=\(code.symbology.rawValue) value=\(code.payloadStringValue ?? "")")
    }
}
