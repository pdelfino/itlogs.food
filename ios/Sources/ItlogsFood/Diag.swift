import Foundation
import MWDATCore
import os

/// Phone-side diagnostics the Mac can read: every line goes to os_log (public) and is POSTed
/// to the server's /log, so `make run` shows what the wearer sees. No photos, no audio.
enum Diag {
    private static let log = Logger(subsystem: "food.itlogs", category: "diag")

    static func send(_ line: String) {
        log.notice("\(line, privacy: .public)")
        Telemetry.event("phone_diag", ["line": line])
        guard let ws = UserDefaults.standard.string(forKey: "serverURL") ?? Optional("ws://Pedros-MacBook-Air.local:8000/ws/session"),
              var c = URLComponents(string: ws) else { return }
        c.scheme = (c.scheme == "wss") ? "https" : "http"
        c.path = "/log"
        guard let url = c.url else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["t": Date().timeIntervalSince1970, "line": line])
        URLSession.shared.dataTask(with: req).resume()
    }

    private static let tokens = ListenerTokenBag()

    /// The toolkit's registration state, the devices it knows, their link state and
    /// compatibility, as they change.
    @MainActor static func watchRegistration() {
        Task {
            for await state in Wearables.shared.registrationStateStream() {
                send("registration state: \(String(describing: state))")
            }
        }
        Task {
            for await devices in Wearables.shared.devicesStream() {
                send("devices: \(devices.count)")
                for id in devices { describe(id) }
            }
        }
    }

    /// One line per device now, then a line on every link-state or compatibility change.
    @MainActor static func describe(_ id: DeviceIdentifier) {
        guard let device = Wearables.shared.deviceForIdentifier(id) else {
            send("device \(String(describing: id)): no Device object")
            return
        }
        send("device '\(device.name)' type=\(String(describing: device.deviceType())) compatibility=\(String(describing: device.compatibility()))")
        device.addLinkStateListener { (state: LinkState) in
            send("device '\(device.name)' link=\(String(describing: state))")
        }.store(in: tokens)
        device.addCompatibilityListener { (c: Compatibility) in
            send("device '\(device.name)' compatibility=\(String(describing: c))")
        }.store(in: tokens)
    }
}
