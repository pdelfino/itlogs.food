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

    /// The best English voice installed on this phone: premium, then enhanced, then the default.
    /// Premium voices are downloaded once in Settings > Accessibility > Spoken Content > Voices.
    private static let chosenVoice: AVSpeechSynthesisVoice? = {
        if let id = UserDefaults.standard.string(forKey: "voiceIdentifier"),
           let v = AVSpeechSynthesisVoice(identifier: id) { return v }
        let english = AVSpeechSynthesisVoice.speechVoices().filter { $0.language.hasPrefix("en") }
        func rank(_ v: AVSpeechSynthesisVoice) -> Int {
            let quality = v.quality == .premium ? 20 : (v.quality == .enhanced ? 10 : 0)
            let locale = v.language == "en-US" ? 2 : (v.language == "en-CA" ? 1 : 0)
            return quality + locale
        }
        return english.max { rank($0) < rank($1) }
    }()

    private var announcedVoice = false
    /// When the ear last heard this app speak: the glasses' microphone hears the glasses' speaker, and
    /// the recognizer sent "Put the first put on the scale" back as the wearer's words (2026-NOVEMBER-02
    /// 18:34). Phrases heard while speaking, or within `echoTailSeconds` after, are the app's own voice.
    private(set) var speakingUntil = Date.distantPast
    let echoTailSeconds: TimeInterval = 1.2

    var isSpeaking: Bool { synth.isSpeaking || Date() < speakingUntil }

    func say(_ text: String) {
        // a rough duration: about 14 characters a second at this rate, plus the tail
        speakingUntil = Date().addingTimeInterval(Double(text.count) / 14.0 + echoTailSeconds)
        let u = AVSpeechUtterance(string: text)
        u.rate = AVSpeechUtteranceDefaultSpeechRate * 0.95
        u.pitchMultiplier = 1.0
        u.prefersAssistiveTechnologySettings = false
        if let v = Self.chosenVoice {
            u.voice = v
            if !announcedVoice {
                announcedVoice = true
                Diag.send("voice: \(v.name) \(v.language) quality=\(v.quality.rawValue)")
            }
        }
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
        let format = node.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else {
            throw NSError(domain: "food.itlogs", code: 22, userInfo: [NSLocalizedDescriptionKey: "No microphone route yet (sample rate 0); try again in a second"])
        }
        // The tap runs on Core Audio's realtime queue: no main-actor state may be touched there
        // (crash report 2026-11-01 19:31). SpeechTap is a plain object that only appends.
        let tap = SpeechTap(request: request)
        node.installTap(onBus: 0, bufferSize: 1024, format: format) { @Sendable buffer, _ in
            tap.handle(buffer)
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

/// The realtime side of on-device recognition: appends buffers to the request. No actor.
final class SpeechTap: @unchecked Sendable {
    private let request: SFSpeechAudioBufferRecognitionRequest
    init(request: SFSpeechAudioBufferRecognitionRequest) { self.request = request }
    func handle(_ buffer: AVAudioPCMBuffer) { request.append(buffer) }
}
