import Foundation
import Vision

guard CommandLine.arguments.count == 3 else {
    fputs("usage: ocr_iek_documents.swift <rendered-pages-dir> <output-json>\n", stderr)
    exit(2)
}

let root = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let output = URL(fileURLWithPath: CommandLine.arguments[2])
let fm = FileManager.default
let keys: [URLResourceKey] = [.isRegularFileKey]
var files: [URL] = []
if let enumerator = fm.enumerator(at: root, includingPropertiesForKeys: keys) {
    for case let url as URL in enumerator where url.pathExtension.lowercased() == "png" {
        files.append(url)
    }
}
files.sort { $0.path < $1.path }

var pages: [[String: String]] = []
for (index, url) in files.enumerated() {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["ru-RU", "en-US"]
    request.usesLanguageCorrection = true
    let handler = VNImageRequestHandler(url: url, options: [:])
    try handler.perform([request])
    let text = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
    pages.append(["file": url.lastPathComponent, "text": text])
    if (index + 1) % 10 == 0 {
        print("OCR \(index + 1)/\(files.count)")
    }
}

let data = try JSONSerialization.data(withJSONObject: ["page_count": pages.count, "pages": pages],
                                      options: [.prettyPrinted, .sortedKeys, .fragmentsAllowed])
try data.write(to: output, options: .atomic)
print("OCR complete: \(pages.count) pages -> \(output.path)")
