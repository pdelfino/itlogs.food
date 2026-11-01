import Foundation
import MWDATCore
import os

/// "Hey Meta, start itlogs": Meta AI launches or foregrounds the app and sends a LaunchApp
/// invocation (dev and beta channels). We answer it once and start weighing mode. The stream
/// and its tokens must stay stored, or the subscription is released and nothing arrives.
@MainActor
final class VoiceInvocations {
    private let log = Logger(subsystem: "food.itlogs", category: "voice-invocations")
    private var stream: VoiceInvocationsStream?
    private var invocationToken: (any AnyListenerToken)?
    private var errorToken: (any AnyListenerToken)?
    private var devicesTask: Task<Void, Never>?
    private let onLaunch: @MainActor () async -> Void

    init(onLaunch: @escaping @MainActor () async -> Void) {
        self.onLaunch = onLaunch
    }

    /// Listen on every connected pair of glasses, now and as they connect.
    func start() {
        let wearables = Wearables.shared
        for device in wearables.devices { listen(on: device) }
        devicesTask = Task { [weak self] in
            for await devices in wearables.devicesStream() {
                guard let self else { return }
                if let device = devices.first { self.listen(on: device) }
            }
        }
    }

    private func listen(on device: DeviceIdentifier) {
        do {
            let stream = try VoiceInvocationsStream(wearables: Wearables.shared)
            invocationToken = stream.invocationsPublisher.listen { [weak self] (invocation: any VoiceInvocation) in
                guard let launch = invocation as? LaunchApp else { return }
                Task { @MainActor in
                    _ = await launch.responseHandle.sendSuccess(actionOutput: nil)
                    await self?.onLaunch()
                }
            }
            errorToken = stream.errorPublisher.listen { [log] (error: VoiceInvocationError) in
                log.error("voice invocation error: \(String(describing: error), privacy: .public)")
            }
            try stream.start(deviceIdentifier: device)
            self.stream = stream
            log.info("listening for voice invocations")
        } catch {
            log.error("voice invocations unavailable: \(error.localizedDescription, privacy: .public)")
        }
    }
}
