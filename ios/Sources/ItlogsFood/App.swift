import MWDATCore
import SwiftUI

@main
struct ItlogsFoodApp: App {
    @State private var session = SessionController()

    init() { GlassesSource.configure() }

    var body: some Scene {
        WindowGroup {
            SessionView(session: session)
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
