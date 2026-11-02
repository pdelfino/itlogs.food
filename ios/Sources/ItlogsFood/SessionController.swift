import AudioToolbox
import Foundation
import MWDATCore
import Observation
import os

/// Glue: frames and voice up, server messages into view state and the speaker.
@MainActor
@Observable
final class SessionController {
    /// The Mac on the LAN; edited in the UI and remembered between launches.
    var serverURL: URL = {
        if let saved = UserDefaults.standard.string(forKey: "serverURL"), let u = URL(string: saved) { return u }
        return URL(string: "ws://Pedros-MacBook-Air.local:8000/ws/session")!
    }() {
        didSet { UserDefaults.standard.set(serverURL.absoluteString, forKey: "serverURL") }
    }
    var useGlasses = false
    var useDeviceSpeech = false  // fallback: recognize on the phone, send text
    var lastRead: EntryRead?
    var question: Question?
    var entries: [Entry] = []
    var lastSaid = ""
    var error: String?
    var running = false
    var watching = false

    private let log = Logger(subsystem: "food.itlogs", category: "session")
    private let client = StreamClient()
    private let voice = Voice()
    private let audio = AudioStreamer()
    private var source: FrameSource?
    private var started = Date()

    var totals: Nutrients? {
        let known = entries.compactMap(\.nutrients)
        guard !known.isEmpty else { return nil }
        return known.reduce(Nutrients(kcal: 0, protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0, sodium_mg: 0)) { acc, n in
            Nutrients(kcal: acc.kcal + n.kcal, protein_g: acc.protein_g + n.protein_g, carbs_g: acc.carbs_g + n.carbs_g,
                      fat_g: acc.fat_g + n.fat_g, fiber_g: acc.fiber_g + n.fiber_g, sodium_mg: acc.sodium_mg + n.sodium_mg)
        }
    }

    func start() async {
        error = nil
        started = Date()
        Diag.send("start tapped; glasses=\(useGlasses) server=\(serverURL.absoluteString)")
        await client.connect(url: serverURL) { [weak self] msg in
            Task { @MainActor in self?.handle(msg) }
        }
        let source: FrameSource = useGlasses ? GlassesSource() : PhoneCameraSource()
        self.source = source
        do {
            try await source.start { [client] jpeg, meta in
                Task { try? await client.send(frame: jpeg, meta: meta) }
            }
            if useDeviceSpeech {
                try await voice.startListening { [weak self, client] phrase in
                    Task { @MainActor in
                        guard let self else { return }
                        try? await client.send(voice: phrase, tMs: self.nowMs())
                    }
                }
            } else {
                try audio.start { [client] pcm, tMs in
                    Task { try? await client.send(audio: pcm, tMs: tMs) }
                }
            }
            running = true
        } catch {
            self.error = "Start failed: \(String(describing: error))"
            Diag.send("start failed: \(String(describing: error))")
            Telemetry.error(error, ["where": "start"])
        }
    }

    /// The deliberate trigger: read the scale now.
    func capture() { Task { try? await client.capture(tMs: nowMs()) } }

    /// Weighing mode: the server watches the scale and asks after each food.
    func setWeighing(_ on: Bool) { Task { try? await client.watch(on: on, tMs: nowMs()) } }

    /// "Hey Meta, start itlogs": start the session if needed, then weighing mode.
    func startWeighingFromVoice() async {
        if !running { await start() }
        setWeighing(true)
    }

    /// The glasses-side toolkit app is installed or updated from the Meta AI app.
    func updateGlassesApp() async {
        Diag.send("update glasses app tapped")
        do { try await Wearables.shared.openDATGlassesAppUpdate() } catch {
            self.error = "Glasses app update: \(String(describing: error))"
            Diag.send("openDATGlassesAppUpdate threw: \(String(describing: error))")
        }
    }

    /// One-time pairing with the glasses (opens the Meta AI app and returns).
    func registerGlasses() async {
        Diag.send("pair tapped; registration state before: \(String(describing: Wearables.shared.registrationState))")
        if Wearables.shared.registrationState == .registered {
            self.error = nil
            self.lastSaid = "Already connected to the glasses."
            for id in Wearables.shared.devices { Diag.describe(id) }
            return
        }
        do {
            try await GlassesSource.register()
            Diag.send("startRegistration returned without error")
        } catch {
            let detail = String(describing: error)
            self.error = "Pair failed: \(detail)"
            Diag.send("startRegistration threw: \(detail) / \(error.localizedDescription)")
            Telemetry.error(error, ["where": "registration"])
        }
    }

    func stop() async {
        voice.stopListening()
        audio.stop()
        await source?.stop()
        try? await client.endSession()
        await client.disconnect()
        running = false
        watching = false
    }

    func handle(_ msg: ServerMessage) {
        switch msg.kind {
        case "read": lastRead = msg.read
        case "entry":
            if let e = msg.entry { entries.append(e) }
            question = nil
            AudioServicesPlaySystemSound(1057)  // a short tick per logged entry
        case "ask": question = msg.ask
        case "say":
            if let text = msg.say { lastSaid = text; voice.say(text) }
            if msg.say == "Skipped." { question = nil }
        case "state":
            entries = msg.entries ?? entries
            if let w = msg.watching { watching = w }
        default: break
        }
    }

    private func nowMs() -> Int { Int(Date().timeIntervalSince(started) * 1000) }
}
