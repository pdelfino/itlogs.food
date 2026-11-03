import AVFoundation
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
    var useGlasses = UserDefaults.standard.bool(forKey: "useGlasses") {
        didSet { UserDefaults.standard.set(useGlasses, forKey: "useGlasses") }
    }
    /// Experiment (#2): ask the glasses for the video stream instead of stills. The stream has never
    /// published a state in this app; this switch lets a test say whether it does now.
    var useStream = (UserDefaults.standard.object(forKey: "useStream") as? Bool) ?? true {
        didSet { UserDefaults.standard.set(useStream, forKey: "useStream") }
    }
    var useDeviceSpeech = false  // fallback: recognize on the phone, send text
    var askEachFood = false      // off: log quietly, hear the list at Stop; on: "..., right?" after each food
    var lastRead: EntryRead?
    var question: Question?
    var entries: [Entry] = []
    var lastSaid = ""
    var lastHeard = ""
    var error: String?
    var running = false
    var watching = false
    /// Start was tapped and the glasses session and stream are coming up (about six seconds);
    /// a second tap meanwhile made the toolkit throw sessionAlreadyExists (19:33, three times).
    var starting = false
    /// When Start was tapped; the Stop button stays disabled for `stopAfterSeconds` from here, so a
    /// run cannot end before the loop had a still second to read (runs of 5 to 12 s on
    /// 2026-NOVEMBER-02 all ended with "Nothing logged").
    var startedAt: Date?
    let stopAfterSeconds: TimeInterval = 3  // only against an accidental tap; the loop no longer needs waiting (#12)
    /// Stop was tapped and the server is finishing the last read before it reads the list back.
    var finishing = false
    /// After Stop with entries: the review table is up; Confirm writes to Apple Health (#3).
    var reviewing = false
    var healthSaving = false
    var healthSaved = false
    var healthMessage: String?
    private let health = Health()
    private let chime = Chime()

    func saveToHealth() async {
        healthSaving = true
        defer { healthSaving = false }
        guard Health.available else { healthMessage = "Apple Health is not available on this device."; return }
        guard await health.authorize() else {
            healthMessage = "Apple Health access was not granted. Settings > Health > Data Access & Devices > It Logs Food."
            return
        }
        do {
            let n = try await health.save(entries)
            healthSaved = n > 0
            healthMessage = n == entries.count
                ? "Saved \(n) \(n == 1 ? "food" : "foods") to Apple Health."
                : "Saved \(n) of \(entries.count): foods without a nutrient row have nothing to write yet."
            voice.say(healthMessage ?? "")
        } catch {
            healthMessage = "Apple Health refused: \(error.localizedDescription)"
            Diag.send("health: save threw \(String(describing: error))")
            Telemetry.error(error, ["where": "health"])
        }
    }

    /// The first frame has reached the phone: before this, weighing is pointless (the stream takes
    /// about six seconds to start; on 2026-NOVEMBER-02 19:12 the foods went on before it did).
    var cameraLive = false

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
        guard !starting && !running else { Diag.send("start tapped while \(starting ? "starting" : "running"); ignored"); return }
        starting = true
        defer { starting = false }
        error = nil
        started = Date()
        cameraLive = false
        reviewing = false
        healthSaved = false
        healthMessage = nil
        entries = []  // a run is one meal; the review and the Health write cover this run only
        lastRead = nil
        question = nil
        Diag.send("start tapped; glasses=\(useGlasses) server=\(serverURL.absoluteString)")
        await client.connect(url: serverURL) { [weak self] msg in
            Task { @MainActor in self?.handle(msg) }
        }
        let glasses: GlassesSource? = useGlasses ? GlassesSource() : nil
        glasses?.useStills = !useStream  // the stream works without the Hotspot entitlement (2026-NOVEMBER-02 18:04, build 47)
        glasses?.onPhrase = { [weak self, client] phrase in
            Task { @MainActor in
                guard let self else { return }
                if self.voice.isSpeaking {
                    Diag.send("ignored, our own voice: \"\(phrase)\"")
                    return
                }
                self.lastHeard = phrase
                try? await client.send(voice: phrase, tMs: self.nowMs())
            }
        }
        var source: FrameSource = glasses ?? PhoneCameraSource()
        self.source = source
        do {
            do {
                try await source.start { [weak self, client] jpeg, meta in
                    Task { @MainActor in self?.cameraLive = true }
                    Task { try? await client.send(frame: jpeg, meta: meta) }
                }
            } catch let e as NSError where e.domain == "food.itlogs" && e.code == 13 {
                // glasses video impossible in this build: fall back to the phone camera, keep going
                lastSaid = e.localizedDescription
                Diag.send("falling back to the phone camera: \(e.localizedDescription)")
                source = PhoneCameraSource()
                self.source = source
                try await source.start { [weak self, client] jpeg, meta in
                    Task { @MainActor in self?.cameraLive = true }
                    Task { try? await client.send(frame: jpeg, meta: meta) }
                }
            }
            do {
                if glasses?.hearsThroughGlasses == true {
                    // the glasses transcribe; no HFP on the phone, so the voice out keeps A2DP quality
                    let session = AVAudioSession.sharedInstance()
                    try? session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
                    try? session.setActive(true, options: .notifyOthersOnDeactivation)
                    Diag.send("hearing through the glasses; speaking over A2DP")
                } else if useDeviceSpeech {
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
            } catch {
                // the first streaming run (2026-NOVEMBER-02 18:04) ended here on a phone-mic start error
                // while the video kept flowing; voice is a second input, never the reason to stop
                lastSaid = "Voice input is off this session (the microphone did not start). The Log it button still works."
                Diag.send("voice input unavailable this session: \(String(describing: error))")
                Telemetry.error(error, ["where": "audio"])
            }
            running = true
            startedAt = Date()
            // Start means weighing: the server watches the scale from here until Stop
            try? await client.watch(on: true, tMs: nowMs(), ask: askEachFood)
        } catch {
            self.error = "Start failed: \(String(describing: error))"
            Diag.send("start failed: \(String(describing: error))")
            Telemetry.error(error, ["where": "start"])
        }
    }

    /// The deliberate trigger: read the scale now (in stills mode, take a still first).
    func capture() {
        (source as? GlassesSource)?.takePhoto()
        Task { try? await client.capture(tMs: nowMs()) }
    }

    /// Weighing mode on or off by hand (Start already turns it on).
    func setWeighing(_ on: Bool) { Task { try? await client.watch(on: on, tMs: nowMs(), ask: askEachFood) } }

    /// "Hey Meta, start itlogs": start the session if needed, then weighing mode.
    func startWeighingFromVoice() async {
        if !running { await start() }
        setWeighing(true)
    }

    /// Forget this app's registration with the glasses and register again. Needed when the
    /// glasses drop the app from their manifest (seen 2026-NOVEMBER-02 after another developer-mode
    /// app registered: "This app is no longer registered"), and the clean way to get a registration
    /// record newer than the glasses-app update of NOVEMBER-01 (#2).
    func reconnectGlasses() async {
        Diag.send("reconnect tapped; registration state before: \(String(describing: Wearables.shared.registrationState))")
        if Wearables.shared.registrationState == .registered {
            do {
                try await Wearables.shared.startUnregistration()
                Diag.send("unregistered; state now \(String(describing: Wearables.shared.registrationState))")
            } catch {
                Diag.send("startUnregistration threw: \(String(describing: error))")
            }
        }
        do {
            try await GlassesSource.register()
            Diag.send("startRegistration returned; state now \(String(describing: Wearables.shared.registrationState))")
            self.error = nil
            self.lastSaid = "Reconnecting to the glasses through Meta AI."
        } catch {
            self.error = "Reconnect failed: \(String(describing: error))"
            Diag.send("startRegistration threw: \(String(describing: error))")
        }
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
        guard !finishing else { Diag.send("stop tapped again while finishing; ignored"); return }
        Diag.send("stop tapped after \(nowMs() / 1000) s; entries=\(entries.count)")
        finishing = true
        lastSaid = "Finishing the last reading…"
        voice.stopListening()
        audio.stop()
        await source?.stop()
        finalStateArrived = false
        try? await client.endSession()
        // the server finishes the read in flight, then answers with the list to read back (#12)
        let waited = Date()
        for _ in 0..<80 where !finalStateArrived {  // up to 8 s: reads in flight, then the final look
            try? await Task.sleep(for: .milliseconds(100))
        }
        Diag.send("stop: final state \(finalStateArrived ? "arrived" : "never came") after \(Int(Date().timeIntervalSince(waited) * 1000)) ms; entries=\(entries.count)")
        try? await Task.sleep(for: .milliseconds(500))  // let the last "say" land before the socket closes
        await client.disconnect()
        running = false
        watching = false
        finishing = false
        cameraLive = false
        startedAt = nil
        reviewing = !entries.isEmpty  // the table comes up; Confirm sends it to Apple Health
    }

    private var finalStateArrived = false

    func handle(_ msg: ServerMessage) {
        switch msg.kind {
        case "read": lastRead = msg.read
        case "entry":
            if let e = msg.entry {
                if let i = entries.firstIndex(where: { $0.index == e.index }) {
                    entries[i] = e  // the server corrected a row (same food read again)
                } else {
                    entries.append(e)
                    chime.play()  // the "checked" sound: move on to the next food
                }
            }
            question = nil
        case "ask": question = msg.ask
        case "say":
            if let text = msg.say { lastSaid = text; voice.say(text) }
            if msg.say == "Skipped." { question = nil }
        case "state":
            entries = msg.entries ?? entries
            if let w = msg.watching { watching = w }
            if finishing { finalStateArrived = true }
        default: break
        }
    }

    private func nowMs() -> Int { Int(Date().timeIntervalSince(started) * 1000) }
}
