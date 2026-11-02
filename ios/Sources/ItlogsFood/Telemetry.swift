import Foundation
import PostHog
import os

/// PostHog: crashes (Mach exceptions, signals, uncaught NSExceptions, sent on the next launch)
/// and the diagnostic lines, so faults land where the Mac can read them without a cable
/// (issue #9). No session replay, no autocapture of taps, no screen names: only what
/// `Diag.send` already says. Without a token the app runs exactly as before.
enum Telemetry {
    private static let log = Logger(subsystem: "food.itlogs", category: "telemetry")
    nonisolated(unsafe) private(set) static var enabled = false  // written once at launch, read everywhere

    static func setup() {
        let info = Bundle.main.infoDictionary ?? [:]
        let token = (info["PosthogProjectToken"] as? String ?? "").trimmingCharacters(in: .whitespaces)
        let host = (info["PosthogHost"] as? String ?? "").trimmingCharacters(in: .whitespaces)
        guard !token.isEmpty, !host.isEmpty else {
            #if DEBUG
            log.error("POSTHOG_PROJECT_TOKEN variable required by PostHog is missing or un-configured, this causes events to be silently missed. This error stops appearing once POSTHOG_PROJECT_TOKEN is configured")
            #endif
            return
        }
        let config = PostHogConfig(apiKey: token, host: host)
        config.errorTrackingConfig.autoCapture = true
        config.captureApplicationLifecycleEvents = true
        config.captureScreenViews = false
        config.captureElementInteractions = false
        config.sessionReplay = false
        PostHogSDK.shared.setup(config)
        PostHogSDK.shared.register(["app_build": info["CFBundleVersion"] as? String ?? "?",
                                    "git_sha": info["ItlogsGitSHA"] as? String ?? ""])
        enabled = true
    }

    static func event(_ name: String, _ properties: [String: Any] = [:]) {
        guard enabled else { return }
        PostHogSDK.shared.capture(name, properties: properties)
    }

    static func error(_ error: Error, _ properties: [String: Any] = [:]) {
        guard enabled else { return }
        PostHogSDK.shared.captureException(error, properties: properties)
    }
}
