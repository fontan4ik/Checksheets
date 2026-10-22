import Foundation
import Vision
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNDetectBarcodesRequest()
request.symbologies = [.qr]
try VNImageRequestHandler(url: url).perform([request])
for item in request.results ?? [] {
    if let code = item.payloadStringValue { print(code) }
}
