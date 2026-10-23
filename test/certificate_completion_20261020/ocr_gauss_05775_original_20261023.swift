import AppKit
import Foundation
import PDFKit
import Vision

let input = CommandLine.arguments[1]
let output = CommandLine.arguments[2]
let url = URL(fileURLWithPath: input)
guard let document = PDFDocument(url: url) else { fatalError("cannot_open_pdf") }
var result = "pages=\(document.pageCount)\n"
for index in 0..<document.pageCount {
    guard let page = document.page(at: index) else { fatalError("missing_page_\(index + 1)") }
    let bounds = page.bounds(for: .mediaBox)
    let image = page.thumbnail(of: CGSize(width: bounds.width * 2.5, height: bounds.height * 2.5), for: .mediaBox)
    var rect = CGRect(origin: .zero, size: image.size)
    guard let cgImage = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else {
        fatalError("cannot_render_page_\(index + 1)")
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["ru-RU", "en-US"]
    request.usesLanguageCorrection = true
    try VNImageRequestHandler(cgImage: cgImage).perform([request])
    let observations = (request.results ?? []).sorted {
        if abs($0.boundingBox.midY - $1.boundingBox.midY) > 0.006 {
            return $0.boundingBox.midY > $1.boundingBox.midY
        }
        return $0.boundingBox.minX < $1.boundingBox.minX
    }
    result += "\n--- PAGE \(index + 1) ---\n"
    for observation in observations {
        if let text = observation.topCandidates(1).first?.string { result += text + "\n" }
    }
}
try result.write(toFile: output, atomically: true, encoding: .utf8)
print("ocr_pages=\(document.pageCount) output=\(output)")
