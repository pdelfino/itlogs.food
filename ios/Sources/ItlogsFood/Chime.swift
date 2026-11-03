import AVFoundation
import Foundation

/// The "checked" sound: a short rising two-note chime (C6 then G6), synthesized, so it needs no
/// asset and plays through whatever the audio session routes to, the glasses included. One per
/// new entry: the cue to move on to the next food.
@MainActor
final class Chime {
    private let engine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var buffer: AVAudioPCMBuffer?

    init() {
        let format = AVAudioFormat(standardFormatWithSampleRate: 44_100, channels: 1)!
        engine.attach(player)
        engine.connect(player, to: engine.mainMixerNode, format: format)
        buffer = Self.render(format: format)
    }

    func play() {
        guard let buffer else { return }
        if !engine.isRunning {
            do { try engine.start() } catch {
                Diag.send("chime: engine failed to start: \(error.localizedDescription)")
                return
            }
        }
        player.stop()
        player.scheduleBuffer(buffer, at: nil, options: [])
        player.play()
    }

    /// Two sine notes with a soft attack and an exponential decay; 0.42 s in all.
    private static func render(format: AVAudioFormat) -> AVAudioPCMBuffer? {
        let sr = format.sampleRate
        let notes: [(hz: Double, start: Double, length: Double)] = [(1046.5, 0.0, 0.22), (1568.0, 0.14, 0.28)]
        let total = 0.42
        let frames = AVAudioFrameCount(total * sr)
        guard let buf = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frames) else { return nil }
        buf.frameLength = frames
        let out = buf.floatChannelData![0]
        for i in 0..<Int(frames) {
            let t = Double(i) / sr
            var v = 0.0
            for n in notes where t >= n.start && t < n.start + n.length {
                let x = t - n.start
                let attack = min(1.0, x / 0.01)
                let decay = exp(-x * 9.0)
                v += sin(2 * .pi * n.hz * x) * attack * decay * 0.35
                v += sin(2 * .pi * n.hz * 2 * x) * attack * decay * 0.08  // a touch of overtone
            }
            out[i] = Float(v)
        }
        return buf
    }
}
