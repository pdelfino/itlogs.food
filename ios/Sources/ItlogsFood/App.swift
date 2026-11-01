import SwiftUI

@main
struct ItlogsFoodApp: App {
    @State private var session = SessionController()

    init() { GlassesSource.configure() }

    var body: some Scene {
        WindowGroup {
            SessionView(session: session)
        }
    }
}
