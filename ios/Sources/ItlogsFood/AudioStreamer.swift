import AVFoundation
import Foundation
import os

/// Microphone to 24 kHz 16-bit mono PCM chunks (about 80 ms each), for the server-side
/// transcriber. With the glasses connected, iOS routes the Bluetooth microphone here.
///
/// The tap block runs on Core Audio's realtime queue, never on the main actor: everything it
/// touches lives in `Tap`, a plain object, so no main-actor state is reached from that queue
/// (the first live run crashed on exactly that isolation check, 2026-11-01 19:25).
@MainActor
final class AudioStreamer {
    private let log = Logger(subsystem: "food.itlogs", category: "audio")
    private let engine = AVAudioEngine()
    private var tap: Tap?

    func start(_ sink: @escaping @Sendable (Data, Int) -> Void) throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers, .allowBluetoothHFP])
        try session.setActive(true, options: .notifyOthersOnDeactivation)
        let input = engine.inputNode
        let inFormat = input.outputFormat(forBus: 0)
        guard inFormat.sampleRate > 0, inFormat.channelCount > 0 else {
            throw NSError(domain: "food.itlogs", code: 21, userInfo: [NSLocalizedDescriptionKey: "No microphone route yet (sample rate 0); try again in a second"])
        }
        let tap = try Tap(inFormat: inFormat, sink: sink)
        self.tap = tap
        input.installTap(onBus: 0, bufferSize: 2048, format: inFormat) { buffer, _ in
            tap.handle(buffer)
        }
        engine.prepare()
        try engine.start()
        log.info("audio streaming at 24 kHz mono from \(inFormat.sampleRate, privacy: .public) Hz")
    }

    func stop() {
        engine.stop()
        engine.inputNode.removeTap(onBus: 0)
        tap = nil
    }
}

/// The realtime side: converts each buffer and hands the bytes to the sink. No actor.
final class Tap: @unchecked Sendable {
    private let converter: AVAudioConverter
    private let target = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 24_000, channels: 1, interleaved: true)!
    private let ratio: Double
    private let startedAt = Date()
    private let sink: @Sendable (Data, Int) -> Void
    private let log = Logger(subsystem: "food.itlogs", category: "audio-tap")

    init(inFormat: AVAudioFormat, sink: @escaping @Sendable (Data, Int) -> Void) throws {
        guard let converter = AVAudioConverter(from: inFormat, to: target) else {
            throw NSError(domain: "food.itlogs", code: 20, userInfo: [NSLocalizedDescriptionKey: "No audio converter"])
        }
        self.converter = converter
        self.ratio = target.sampleRate / inFormat.sampleRate
        self.sink = sink
    }

    func handle(_ buffer: AVAudioPCMBuffer) {
        let frames = AVAudioFrameCount(Double(buffer.frameLength) * ratio) + 16
        guard let out = AVAudioPCMBuffer(pcmFormat: target, frameCapacity: frames) else { return }
        var consumed = false
        var error: NSError?
        converter.convert(to: out, error: &error) { _, status in
            if consumed { status.pointee = .noDataNow; return nil }
            consumed = true
            status.pointee = .haveData
            return buffer
        }
        if let error { log.error("convert: \(error.localizedDescription, privacy: .public)"); return }
        guard out.frameLength > 0, let ch = out.int16ChannelData else { return }
        let data = Data(bytes: ch[0], count: Int(out.frameLength) * 2)
        sink(data, Int(Date().timeIntervalSince(startedAt) * 1000))
    }
}
