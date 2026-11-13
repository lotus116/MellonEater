import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count == 2 else { fputs("usage: ocr image\n", stderr); exit(2) }
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["zh-Hans", "zh-Hant", "en-US"]
request.usesLanguageCorrection = true
do {
    try VNImageRequestHandler(url: url, options: [:]).perform([request])
    let lines: [[String: Any]] = (request.results ?? []).compactMap { observation in
        guard let top = observation.topCandidates(1).first else { return nil }
        let b = observation.boundingBox
        return ["text": top.string, "confidence": top.confidence,
                "bbox": [b.origin.x, b.origin.y, b.width, b.height]]
    }
    let data = try JSONSerialization.data(withJSONObject: lines, options: [.sortedKeys])
    print(String(data: data, encoding: .utf8)!)
} catch {
    fputs("Local OCR failed: \(error.localizedDescription)\n", stderr); exit(1)
}
