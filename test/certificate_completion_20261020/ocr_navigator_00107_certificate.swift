import Foundation
import Vision
import ImageIO

let pattern = "^nav00107_cert_ocr_[0-9]+\\.jpg$"
let files = try FileManager.default.contentsOfDirectory(atPath: "/tmp")
    .filter { $0.range(of: pattern, options: .regularExpression) != nil }
    .sorted()
var result: [[String: Any]] = []
for file in files {
    let url = URL(fileURLWithPath: "/tmp/\(file)")
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["ru-RU", "en-US"]
    request.usesLanguageCorrection = false
    request.minimumTextHeight = 0.003
    let handler = VNImageRequestHandler(url: url)
    try handler.perform([request])
    let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    let page = file.replacingOccurrences(of: "nav00107_cert_ocr_", with: "").replacingOccurrences(of: ".jpg", with: "")
    result.append(["page": Int(page) ?? 0, "lines": lines])
}
let data = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
let out = URL(fileURLWithPath: "test/certificate_completion_20261020/navigator_00107_certificate_ocr_20261022.json")
try data.write(to: out)
print(String(data: data, encoding: .utf8) ?? "[]")
