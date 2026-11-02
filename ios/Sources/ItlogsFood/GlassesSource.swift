import Foundation
import MWDATCamera
import MWDATCore
import MWDATSpeech
import UIKit
import os

/// Frames from the Ray-Ban Meta glasses through the Wearables Device Access Toolkit.
/// Lifecycle (from the toolkit's CameraAccess sample): configure at launch, register the app
/// with the glasses once (Developer Mode in the Meta AI app, no review), create a session,
/// start it, check or request the camera permission (this round-trips through the Meta AI
/// app), add a camera with a StreamConfiguration, listen to the video frames.
final class GlassesSource: FrameSource, @unchecked Sendable {
    private let log = Logger(subsystem: "food.itlogs", category: "glasses")
    private let tokens = ListenerTokenBag()
    private let photoTokens = ListenerTokenBag()  // the photo listeners, cleared on a retry
    private var session: DeviceSession?
    private var camera: Camera?
    private var speech: Speech?
    private var photo: Photo?
    private var photoReady = false
    private var photoInFlight = false
    private var photoTimer: Task<Void, Never>?
    private var sink: (@Sendable (Data, FrameMeta) -> Void)?
    /// Stills instead of the video stream: one photo every ``photoEveryMs`` over Bluetooth, no
    /// Wi-Fi handoff. The default when this build cannot carry the Hotspot entitlement (#10).
    var useStills = !Entitlements.hasHotspot
    var photoEveryMs: UInt64 = 2500
    /// Final transcriptions from the glasses' own recognizer (dev and beta channels). When this
    /// runs, the phone keeps no HFP microphone open, so the ear keeps A2DP quality for speech out.
    var onPhrase: (@Sendable (String) -> Void)?
    private(set) var hearsThroughGlasses = false
    private var started = Date()
    private var lastSent = Date.distantPast
    private var frames = 0
    var fps: Double = 10
    var streamFps: UInt = 24

    static func configure() {
        do { try Wearables.configure() } catch {
            Logger(subsystem: "food.itlogs", category: "glasses").error("configure failed: \(error.localizedDescription, privacy: .public)")
        }
    }

    /// One-time pairing of this app with the glasses; opens the Meta AI app and comes back.
    static func register() async throws {
        try await Wearables.shared.startRegistration()
    }

    func start(_ sink: @escaping @Sendable (Data, FrameMeta) -> Void) async throws {
        let wearables = Wearables.shared
        Diag.send("glasses: creating session; devices=\(wearables.devices.count)")
        for id in wearables.devices { await Diag.describe(id) }
        // Meta's BirdSpotter sample selects the device by identifier; AutoDeviceSelector threw
        // noEligibleDevice here with the glasses connected and compatible (2026-11-01 19:10).
        let selector: DeviceSelector
        if let id = wearables.devices.first {
            selector = SpecificDeviceSelector(device: id)
        } else {
            selector = AutoDeviceSelector(wearables: wearables)
        }
        let session = try wearables.createSession(deviceSelector: selector)
        self.session = session
        // Subscribe before start() so no transition or error is missed (Meta's CameraAccess sample).
        session.statePublisher.listen { (state: DeviceSessionState) in
            Diag.send("glasses: session state \(String(describing: state))")
        }.store(in: tokens)
        session.errorPublisher.listen { (error: DeviceSessionError) in
            Diag.send("glasses: session error \(String(describing: error)) / \(error.localizedDescription)")
        }.store(in: tokens)
        try session.start()
        try await waitForStarted(session)
        Diag.send("glasses: session started")
        if try await wearables.checkPermissionStatus(.camera) != .granted {
            guard try await wearables.requestPermission(.camera) == .granted else {
                throw NSError(domain: "food.itlogs", code: 10, userInfo: [NSLocalizedDescriptionKey: "Glasses camera permission denied"])
            }
        }
        self.sink = sink
        // raw (420v pixel buffers): `frame.makeUIImage()` works on these and returns nil on hvc1, which is why
        // the first streaming run (2026-NOVEMBER-02 18:04, 1600 frames on the phone) sent nothing to the Mac.
        // Raw frames only arrive in the foreground; the demo keeps the app open. hvc1 + a decoder is the
        // background-capable path (Meta's CameraAccess sample has VideoFrameDecoder.swift).
        let config = StreamConfiguration(videoCodec: VideoCodec.raw, resolution: StreamingResolution.low, frameRate: streamFps)
        guard let camera = try session.addCamera(config: config) else {
            throw NSError(domain: "food.itlogs", code: 11, userInfo: [NSLocalizedDescriptionKey: "Could not create the glasses camera"])
        }
        self.camera = camera
        started = Date()
        if useStills {
            // Stream and Photo compete for the camera: stills only, no stream (#2 option B).
            Diag.send("glasses: stills mode (no Hotspot entitlement: \(!Entitlements.hasHotspot)); one photo every \(photoEveryMs) ms")
            try await startPhotosWithRetry(session, first: camera, config: config)
            await attachSpeech(to: session, wearables: wearables)
            return
        }
        if !Entitlements.hasHotspot {
            Diag.send("glasses: no Hotspot entitlement in this build; starting the stream anyway")
        }
        camera.stream.statePublisher.listen { state in
            Diag.send("glasses: stream state \(String(describing: state))")
        }.store(in: tokens)
        camera.stream.videoFramePublisher.listen { [weak self] (frame: VideoFrame) in
            guard let self else { return }
            self.frames += 1
            if self.frames == 1 || self.frames % 200 == 0 { Diag.send("glasses: frame \(self.frames) received") }
            let now = Date()
            guard now.timeIntervalSince(self.lastSent) >= 1 / self.fps else { return }
            self.lastSent = now
            guard let image = frame.makeUIImage(), let jpeg = image.jpegData(compressionQuality: 0.6) else { return }
            let meta = FrameMeta(t_ms: Int(now.timeIntervalSince(self.started) * 1000),
                                 width: Int(image.size.width * image.scale), height: Int(image.size.height * image.scale))
            sink(jpeg, meta)
        }.store(in: tokens)
        camera.stream.errorPublisher.listen { (error: StreamError) in
            Diag.send("glasses: stream error \(String(describing: error))")
        }.store(in: tokens)
        camera.stream.start()
        Diag.send("glasses: stream start requested")
        await attachSpeech(to: session, wearables: wearables)
        log.info("glasses stream started at \(self.streamFps) fps, sending \(self.fps) fps")
    }

    /// Standalone photos (dev and beta channels): `camera.photo` is started once, then each
    /// `capturePhoto` lands on `photoDataPublisher` after crossing the Bluetooth link. One
    /// capture in flight at a time (the publisher carries no request id).
    ///
    /// Meta's camera-capture guide: starting the photo capability is the most common failure
    /// (`sessionSetupFailed`, the glasses report their capture service unavailable) and the next
    /// attempt usually succeeds. So: wait for `started` under a timeout, and on failure stop the
    /// camera, add a fresh one (a stopped camera is invalidated) and try once more. Seen on
    /// 2026-NOVEMBER-02 twice in a row at Start. A power cycle of the glasses clears a capture
    /// service that stays stuck.
    private func startPhotosWithRetry(_ session: DeviceSession, first: Camera, config: StreamConfiguration) async throws {
        var camera = first
        for attempt in 1...2 {
            let photo = camera.photo
            self.photo = photo
            listenToPhotos(photo)
            let outcome = await waitForPhotoStarted(photo, timeoutMs: 8000)
            if outcome == "started" {
                Diag.send("glasses: photos ready (attempt \(attempt))")
                startPhotoTimer()
                return
            }
            Diag.send("glasses: photo setup failed on attempt \(attempt): \(outcome)")
            photoTokens.clear()
            photo.stop()
            self.photo = nil
            photoReady = false
            photoInFlight = false
            camera.stop()
            guard attempt == 1 else { break }
            try? await Task.sleep(for: .milliseconds(500))
            guard let fresh = try session.addCamera(config: config) else { break }
            camera = fresh
            self.camera = fresh
            Diag.send("glasses: fresh camera, retrying the photo capability")
        }
        await stop()
        throw NSError(domain: "food.itlogs", code: 14, userInfo: [NSLocalizedDescriptionKey:
            "The glasses camera did not start (capture service unavailable). Turn the glasses off and on, then press Start again."])
    }

    /// The permanent photo listeners: state, errors, and the stills themselves. Registered
    /// before `start()`, as the guide asks; the publishers do not replay.
    private func listenToPhotos(_ photo: Photo) {
        photo.statePublisher.listen { [weak self] (state: PhotoState) in
            Diag.send("glasses: photo state \(String(describing: state))")
            guard let self else { return }
            self.photoReady = state == .started
            if state != .started { self.photoInFlight = false }
        }.store(in: photoTokens)
        photo.errorPublisher.listen { [weak self] error in
            Diag.send("glasses: photo error \(String(describing: error))")
            self?.photoInFlight = false
        }.store(in: photoTokens)
        photo.photoDataPublisher.listen { [weak self] capture in
            guard let self else { return }
            self.photoInFlight = false
            self.frames += 1
            let data = capture.imageData
            if self.frames == 1 || self.frames % 20 == 0 {
                Diag.send("glasses: photo \(self.frames) received, \(data.count) bytes")
            }
            // the server wants JPEG; a HEIC still is re-encoded through UIImage
            let jpeg: Data
            let size: CGSize
            if let image = UIImage(data: data) {
                size = CGSize(width: image.size.width * image.scale, height: image.size.height * image.scale)
                jpeg = image.jpegData(compressionQuality: 0.8) ?? data
            } else {
                size = .zero
                jpeg = data
            }
            let meta = FrameMeta(t_ms: Int(Date().timeIntervalSince(self.started) * 1000),
                                 width: Int(size.width), height: Int(size.height))
            self.sink?(jpeg, meta)
        }.store(in: photoTokens)
    }

    /// `start()` the photo capability and wait for its answer: "started", "stopped", an error,
    /// or a timeout. Temporary listeners, dropped with the bag when this returns.
    private func waitForPhotoStarted(_ photo: Photo, timeoutMs: UInt64) async -> String {
        let once = OSAllocatedUnfairLock(initialState: false)
        let bag = ListenerTokenBag()
        return await withCheckedContinuation { (c: CheckedContinuation<String, Never>) in
            let finish: @Sendable (String) -> Void = { outcome in
                let first = once.withLock { done -> Bool in
                    if done { return false }
                    done = true
                    return true
                }
                if first { c.resume(returning: outcome) }
            }
            photo.statePublisher.listen { (state: PhotoState) in
                if state == .started { finish("started") } else if state == .stopped { finish("stopped") }
            }.store(in: bag)
            photo.errorPublisher.listen { error in
                finish("error \(String(describing: error))")
            }.store(in: bag)
            Task {
                try? await Task.sleep(for: .milliseconds(timeoutMs))
                finish("timeout after \(timeoutMs) ms")
            }
            photo.start()
        }
    }

    /// One still every `photoEveryMs` while weighing; `takePhoto` skips when one is in flight.
    private func startPhotoTimer() {
        photoTimer?.cancel()
        photoTimer = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(self?.photoEveryMs ?? 2500))
                self?.takePhoto()
            }
        }
    }

    /// One still now (the Log it button, or the timer). Ignored while one is crossing the link.
    func takePhoto() {
        guard let photo, photoReady, !photoInFlight else { return }
        photoInFlight = true
        photo.capturePhoto(resolution: PhotoResolution.medium, quality: PhotoQuality.high)
    }

    /// The glasses' on-device speech recognition: text in, no Bluetooth HFP, so the voice out
    /// stays high quality. Needs the microphone permission through the Meta AI app (once).
    private func attachSpeech(to session: DeviceSession, wearables: any WearablesInterface) async {
        do {
            if try await wearables.checkPermissionStatus(.microphone) != .granted {
                Diag.send("glasses: asking for the microphone permission")
                guard try await wearables.requestPermission(.microphone) == .granted else {
                    Diag.send("glasses: microphone permission denied; phone microphone instead")
                    return
                }
            }
            guard let speech = try session.addSpeech() else {
                Diag.send("glasses: this pair reports no on-device speech; phone microphone instead")
                return
            }
            self.speech = speech
            speech.statePublisher.listen { state in
                Diag.send("glasses: speech state \(String(describing: state))")
            }.store(in: tokens)
            speech.errorPublisher.listen { error in
                Diag.send("glasses: speech error \(String(describing: error))")
            }.store(in: tokens)
            speech.transcriptionPublisher.listen { [weak self] (result: TranscriptionResult) in
                guard result.isFinal, let self, let onPhrase = self.onPhrase else { return }
                let text = result.text.trimmingCharacters(in: .whitespaces)
                guard !text.isEmpty else { return }
                Diag.send("glasses: heard \"\(text)\" (confidence \(result.confidence))")
                onPhrase(text)
            }.store(in: tokens)
            speech.start()
            hearsThroughGlasses = true
            Diag.send("glasses: speech started")
        } catch {
            Diag.send("glasses: speech unavailable: \(String(describing: error)); phone microphone instead")
        }
    }

    func stop() async {
        photoTimer?.cancel()
        photoTimer = nil
        photo?.stop()
        photo = nil
        photoTokens.clear()
        speech?.stop()
        speech = nil
        camera?.stop()
        camera = nil
        session?.stop()
        session = nil
        tokens.clear()
    }

    private func waitForStarted(_ session: DeviceSession) async throws {
        if session.state == .started { return }
        let once = OSAllocatedUnfairLock(initialState: false)
        try await withCheckedThrowingContinuation { (c: CheckedContinuation<Void, Error>) in
            session.statePublisher.listen { (state: DeviceSessionState) in
                let first = once.withLock { done -> Bool in
                    if done || (state != .started && state != .stopped) { return false }
                    done = true
                    return true
                }
                guard first else { return }
                if state == .started { c.resume() } else {
                    c.resume(throwing: NSError(domain: "food.itlogs", code: 12, userInfo: [NSLocalizedDescriptionKey: "Glasses session stopped before it started"]))
                }
            }.store(in: tokens)
        }
    }
}
