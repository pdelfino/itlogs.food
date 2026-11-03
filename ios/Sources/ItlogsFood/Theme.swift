import SwiftUI

/// Direction A, "The display" (picked by Pedro 2026-NOVEMBER-02): the scale's number is the hero
/// in a digital face, paper background, ink text, one orange. The same palette as the site
/// (paper #fafaf7, ink #111, orange #ff5a1f) so the app and itlogs.food read as one thing.
enum Theme {
    static let paper = Color(red: 0.980, green: 0.980, blue: 0.969)
    static let ink = Color(red: 0.067, green: 0.067, blue: 0.067)
    static let text = Color(red: 0.106, green: 0.106, blue: 0.102)
    static let mute = Color(red: 0.42, green: 0.42, blue: 0.404)
    static let line = Color.black.opacity(0.08)
    static let orange = Color(red: 1.0, green: 0.353, blue: 0.122)
    static let card = Color.white

    /// The digital face for numbers: the system monospaced design, semibold, tabular digits.
    static func digits(_ size: CGFloat, weight: Font.Weight = .semibold) -> Font {
        .system(size: size, weight: weight, design: .monospaced)
    }
}

/// The one button: full width, 54 pt, a pill. Ink by default, orange when it is Stop.
struct PillButtonStyle: ButtonStyle {
    var fill: Color = Theme.ink
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 17, weight: .semibold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 54)
            .background(fill.opacity(configuration.isPressed ? 0.85 : 1), in: Capsule())
    }
}
