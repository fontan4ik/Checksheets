import Foundation
import PDFKit
import Vision
import AppKit
let input = URL(fileURLWithPath: CommandLine.arguments[1])
let out = URL(fileURLWithPath: CommandLine.arguments[2])
guard let pdf = PDFDocument(url: input) else { fatalError("PDF load failed") }
var pages: [[String: Any]] = []
for index in 0..<pdf.pageCount {
    guard let page = pdf.page(at: index) else { continue }
    let image = page.thumbnail(of: CGSize(width: 2200, height: 3100), for: .mediaBox)
    var rect = CGRect(origin: .zero, size: image.size)
    guard let cgImage = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else { continue }
    let textRequest = VNRecognizeTextRequest()
    textRequest.recognitionLevel = .accurate
    textRequest.recognitionLanguages = ["ru-RU", "en-US"]
    textRequest.usesLanguageCorrection = false
    try VNImageRequestHandler(cgImage: cgImage).perform([textRequest])
    let lines = (textRequest.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    let qrRequest = VNDetectBarcodesRequest()
    qrRequest.symbologies = [.qr]
    try VNImageRequestHandler(cgImage: cgImage).perform([qrRequest])
    let qr = (qrRequest.results ?? []).compactMap { $0.payloadStringValue }
    pages.append(["page": index + 1, "lines": lines, "qr": qr])
}
let data = try JSONSerialization.data(withJSONObject: pages, options: [.prettyPrinted, .sortedKeys])
try data.write(to: out)
print(String(data: data, encoding: .utf8) ?? "[]")
