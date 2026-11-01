import AVFoundation
import Foundation
import Speech

/// Voice out: the server's `say` text in the ear. Voice in: on-device recognition, text to the server.
/// Both use the platform; a Meta speech model can replace recognition later behind the same calls.
@MainActor
final class Voice {
    private let synth = AVSpeechSynthesizer()
    private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))
    private let audio = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?

    func say(_ text: String) {
        let u = AVSpeechUtterance(string: text)
        u.rate = AVSpeechUtteranceDefaultSpeechRate
        synth.speak(u)
    }

    /// Streams final recognized phrases to `onPhrase`. Call `stopListening` to end.
    func startListening(onPhrase: @escaping @Sendable (String) -> Void) async throws {
        guard await SFSpeechRecognizer.hasAuthorizationToRecognize(), let recognizer, recognizer.isAvailable else {
            throw NSError(domain: "food.itlogs", code: 4, userInfo: [NSLocalizedDescriptionKey: "Speech recognition unavailable"])
        }
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers, .allowBluetooth])
        try session.setActive(true, options: .notifyOthersOnDeactivation)
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        self.request = request
        let node = audio.inputNode
        node.installTap(onBus: 0, bufferSize: 1024, format: node.outputFormat(forBus: 0)) { buffer, _ in
            request.append(buffer)
        }
        audio.prepare()
        try audio.start()
        task = recognizer.recognitionTask(with: request) { result, _ in
            if let result, result.isFinal { onPhrase(result.bestTranscription.formattedString) }
        }
    }

    func stopListening() {
        audio.stop()
        audio.inputNode.removeTap(onBus: 0)
        request?.endAudio()
        task?.cancel()
        request = nil
        task = nil
    }
}

private extension SFSpeechRecognizer {
    static func hasAuthorizationToRecognize() async -> Bool {
        await withCheckedContinuation { c in
            requestAuthorization { c.resume(returning: $0 == .authorized) }
        }
    }
}
