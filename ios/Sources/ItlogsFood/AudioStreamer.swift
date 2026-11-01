import AVFoundation
import Foundation
import os

/// Microphone to 24 kHz 16-bit mono PCM chunks (about 80 ms each), for the server-side
/// transcriber. With the glasses connected, iOS routes the Bluetooth microphone here.
@MainActor
final class AudioStreamer {
    private let log = Logger(subsystem: "food.itlogs", category: "audio")
    private let engine = AVAudioEngine()
    private var converter: AVAudioConverter?
    private let target = AVAudioFormat(commonFormat: .pcmFormatInt16, sampleRate: 24_000, channels: 1, interleaved: true)!
    private var started = Date()

    func start(_ sink: @escaping @Sendable (Data, Int) -> Void) throws {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playAndRecord, mode: .measurement, options: [.duckOthers, .allowBluetooth])
        try session.setActive(true, options: .notifyOthersOnDeactivation)
        let input = engine.inputNode
        let inFormat = input.outputFormat(forBus: 0)
        guard let converter = AVAudioConverter(from: inFormat, to: target) else {
            throw NSError(domain: "food.itlogs", code: 20, userInfo: [NSLocalizedDescriptionKey: "No audio converter"])
        }
        self.converter = converter
        started = Date()
        let startedAt = started
        let target = self.target
        input.installTap(onBus: 0, bufferSize: 2048, format: inFormat) { [log] buffer, _ in
            let ratio = target.sampleRate / inFormat.sampleRate
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
        engine.prepare()
        try engine.start()
        log.info("audio streaming at 24 kHz mono from \(inFormat.sampleRate, privacy: .public) Hz")
    }

    func stop() {
        engine.stop()
        engine.inputNode.removeTap(onBus: 0)
        converter = nil
    }
}
