import Foundation

/// What this build is allowed to do, read from the embedded provisioning profile. The glasses
/// camera stream needs the Hotspot Configuration entitlement; a personal Apple team cannot
/// carry it, and starting the stream without it kills the process (issue #10).
enum Entitlements {
    static let hotspot = "com.apple.developer.networking.HotspotConfiguration"

    static var hasHotspot: Bool {
        guard let path = Bundle.main.path(forResource: "embedded", ofType: "mobileprovision"),
              let data = FileManager.default.contents(atPath: path) else { return false }
        // The profile is a signed plist; the entitlements dictionary is plain text inside it.
        let text = String(decoding: data, as: UTF8.self)
        guard let range = text.range(of: "<key>\(hotspot)</key>") else { return false }
        let after = text[range.upperBound...].prefix(40)
        return after.contains("<true/>")
    }
}
