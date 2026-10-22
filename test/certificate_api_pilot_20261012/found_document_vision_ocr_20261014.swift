import Foundation
import Vision
guard CommandLine.arguments.count == 2 else { exit(2) }
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["ru-RU", "en-US"]
request.usesLanguageCorrection = false
try VNImageRequestHandler(url: url, options: [:]).perform([request])
let observations = request.results ?? []
let text = observations.compactMap { $0.topCandidates(1).first?.string }.joined(separator: "\n")
let data = try JSONSerialization.data(withJSONObject: ["text":text, "lines":observations.count])
print(String(data:data,encoding:.utf8)!)
