import Foundation
import MWDATCamera
import MWDATCore
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
    private var session: DeviceSession?
    private var camera: Camera?
    private var started = Date()
    private var lastSent = Date.distantPast
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
        let config = StreamConfiguration(videoCodec: VideoCodec.hvc1, resolution: StreamingResolution.low, frameRate: streamFps)
        guard let camera = try session.addCamera(config: config) else {
            throw NSError(domain: "food.itlogs", code: 11, userInfo: [NSLocalizedDescriptionKey: "Could not create the glasses camera"])
        }
        self.camera = camera
        started = Date()
        camera.stream.videoFramePublisher.listen { [weak self] (frame: VideoFrame) in
            guard let self else { return }
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
        log.info("glasses stream started at \(self.streamFps) fps, sending \(self.fps) fps")
    }

    func stop() async {
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
