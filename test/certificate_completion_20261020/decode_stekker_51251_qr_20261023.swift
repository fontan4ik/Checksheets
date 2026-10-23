import AppKit
import Foundation
import Vision

let path = CommandLine.arguments[1]
guard let image = NSImage(contentsOfFile: path) else { fatalError("cannot_open_image") }
var rect = CGRect(origin: .zero, size: image.size)
guard let cgImage = image.cgImage(forProposedRect: &rect, context: nil, hints: nil) else {
    fatalError("cannot_decode_image")
}
let request = VNDetectBarcodesRequest()
try VNImageRequestHandler(cgImage: cgImage).perform([request])
for item in request.results ?? [] {
    let value = item.payloadStringValue ?? ""
    print("symbology=\(item.symbology.rawValue) value=\(value)")
}
