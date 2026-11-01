import MWDATCore
import SwiftUI

@main
struct ItlogsFoodApp: App {
    @State private var session = SessionController()
    @State private var invocations: VoiceInvocations?

    init() { GlassesSource.configure() }

    var body: some Scene {
        WindowGroup {
            SessionView(session: session)
                .task {
                    Diag.send("app launched \(SessionView.versionLine)")
                    Diag.watchRegistration()
                    // "Hey Meta, start itlogs" lands here (dev and beta channels only)
                    let v = VoiceInvocations { [session] in await session.startWeighingFromVoice() }
                    v.start()
                    invocations = v
                }
                // The Meta AI app calls back on itlogsfood://...?metaWearablesAction=... after
                // registration and permission flows; the SDK must see that URL or the flow
                // never completes (toolkit guide, step 4).
                .onOpenURL { url in
                    guard let c = URLComponents(url: url, resolvingAgainstBaseURL: false),
                          c.queryItems?.contains(where: { $0.name == "metaWearablesAction" }) == true
                    else { return }
                    Task { @MainActor in
                        do { _ = try await Wearables.shared.handleUrl(url) }
                        catch { session.error = "Glasses callback: \(error.localizedDescription)" }
                    }
                }
        }
    }
}
