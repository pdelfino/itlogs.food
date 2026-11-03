import Foundation

/// What the user reads when something fails (#15): one plain sentence, what happened and what
/// to do next, with a short reference code at the end. The same code heads the Diag line and the
/// telemetry event that carry the full technical error, so a screenshot maps to the log line.
/// Never an error domain, a code number or a type name on the screen.
enum UserFacingError: String, CaseIterable {
    case startFailed = "start_failed"
    case serverUnreachable = "server_unreachable"
    case reconnectFailed = "reconnect_failed"
    case glassesUpdate = "glasses_update"
    case pairFailed = "pair_failed"
    case glassesCallback = "glasses_callback"
    case healthRefused = "health_refused"

    var code: String { rawValue }

    var message: String {
        switch self {
        case .startFailed:
            return "Couldn't start. Check that the glasses are connected in the Meta AI app, then tap Start again."
        case .serverUnreachable:
            return "Couldn't reach the itlogs.food server. Check that the Mac is on the same Wi-Fi and the server is running, then tap Start again."
        case .reconnectFailed:
            return "Couldn't reconnect to the glasses. Open the Meta AI app, check that the glasses are connected, then try again."
        case .glassesUpdate:
            return "Couldn't open the glasses app update. Open the Meta AI app and update from there."
        case .pairFailed:
            return "Couldn't pair with the glasses. Open the Meta AI app, turn on developer mode, then tap Connect again."
        case .glassesCallback:
            return "The glasses sent something this app couldn't handle. Tap Start again; if it repeats, reconnect the glasses in Settings."
        case .healthRefused:
            return "Apple Health didn't accept the meal. Check Settings > Health > Data Access & Devices > It Logs Food, then try again."
        }
    }

    /// The sentence for the screen, with the reference code.
    var text: String { "\(message) (ref: \(code))" }

    /// Logs the technical detail under the code (Diag and telemetry keep everything) and
    /// returns the sentence for the screen.
    @discardableResult
    static func report(_ kind: UserFacingError, _ error: Error) -> String {
        var detail = String(describing: error)
        if let described = (error as? LocalizedError)?.errorDescription, described != detail {
            detail += " / " + described
        }
        Diag.send("\(kind.code): \(detail)")
        Telemetry.error(error, ["where": kind.code, "code": kind.code])
        return kind.text
    }
}
