import AppKit
import Foundation
import PDFKit
import Vision

guard CommandLine.arguments.count == 3 else {
    fatalError("usage: ocr_unparsed_iek_pdfs.swift input.json output_dir")
}

let inputURL = URL(fileURLWithPath: CommandLine.arguments[1])
let outputDir = URL(fileURLWithPath: CommandLine.arguments[2], isDirectory: true)
try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)
let inputData = try Data(contentsOf: inputURL)
let rows = try JSONSerialization.jsonObject(with: inputData) as! [[String: Any]]
var results: [[String: Any]] = []

for row in rows {
    guard let identifier = row["ozon_id"],
          let number = row["number"] as? String,
          let path = row["local_pdf"] as? String else { continue }
    let pdfURL = URL(fileURLWithPath: path)
    guard let document = PDFDocument(url: pdfURL) else {
        results.append(["ozon_id": identifier, "number": number, "error": "pdf_open_failed"])
        continue
    }
    var pageTexts: [String] = []
    for pageIndex in 0..<document.pageCount {
        guard let page = document.page(at: pageIndex) else { continue }
        let preview = page.thumbnail(of: CGSize(width: 2400, height: 3200), for: .mediaBox)
        var proposed = CGRect(origin: .zero, size: preview.size)
        guard let image = preview.cgImage(forProposedRect: &proposed, context: nil, hints: nil) else { continue }
        let request = VNRecognizeTextRequest()
        request.recognitionLevel = .accurate
        request.recognitionLanguages = ["ru-RU", "en-US"]
        request.usesLanguageCorrection = false
        request.minimumTextHeight = 0.002
        try VNImageRequestHandler(cgImage: image, options: [:]).perform([request])
        let text = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
        pageTexts.append("--- PAGE \(pageIndex + 1) ---\n\(text)")
    }
    let ocrText = pageTexts.joined(separator: "\n")
    let safeName = String(describing: identifier)
    let textURL = outputDir.appendingPathComponent("\(safeName).txt")
    try ocrText.write(to: textURL, atomically: true, encoding: .utf8)
    results.append(["ozon_id": identifier, "number": number, "pages": document.pageCount,
                    "characters": ocrText.count, "text_file": textURL.path])
    print("OCR \(identifier): \(document.pageCount) pages, \(ocrText.count) chars")
}

let outputURL = outputDir.appendingPathComponent("index.json")
let encoded = try JSONSerialization.data(withJSONObject: results, options: [.prettyPrinted, .sortedKeys])
try encoded.write(to: outputURL, options: .atomic)
print("Saved \(outputURL.path)")
