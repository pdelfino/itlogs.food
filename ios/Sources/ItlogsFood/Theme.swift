import SwiftUI

/// Identity v2, "Blueberry" (picked by Pedro 2026-NOVEMBER-03, #20): the structure of direction A
/// (#14) stays, the number is still the hero in a digital face; the palette is a cool paper, a
/// blueberry ink and one berry-blue accent, the type is rounded everywhere. The same tokens as the
/// site (paper #f4f3fb, ink #17173a, accent #5848e5) so the app and itlogs.food read as one thing.
enum Theme {
    static let paper = Color(red: 0.957, green: 0.953, blue: 0.984)   // #f4f3fb
    static let wash = Color(red: 0.969, green: 0.953, blue: 1.0)      // #f7f3ff, the top of the weighing screen
    static let ink = Color(red: 0.090, green: 0.090, blue: 0.227)     // #17173a
    static let text = Color(red: 0.153, green: 0.153, blue: 0.353)    // #27275a
    static let mute = Color(red: 0.463, green: 0.463, blue: 0.596)    // #767698
    static let line = Color(red: 0.090, green: 0.090, blue: 0.227).opacity(0.10)
    static let accent = Color(red: 0.345, green: 0.282, blue: 0.898)  // #5848e5
    static let warn = Color(red: 0.898, green: 0.282, blue: 0.302)    // #e5484d, the display is blocked
    static let card = Color.white

    /// The digital face for numbers: rounded, bold, tabular digits.
    static func digits(_ size: CGFloat, weight: Font.Weight = .bold) -> Font {
        .system(size: size, weight: weight, design: .rounded).monospacedDigit()
    }

    /// A sentence the user acts on (the ear's line, the food name, a title): rounded, medium.
    static func sentence(_ size: CGFloat = 17, weight: Font.Weight = .medium) -> Font {
        .system(size: size, weight: weight, design: .rounded)
    }

    /// Everything else: rows, labels, notes.
    static func body(_ size: CGFloat, weight: Font.Weight = .regular) -> Font {
        .system(size: size, weight: weight, design: .rounded)
    }
}

/// The one button: full width, 54 pt, a pill. Ink by default, the accent when it is Stop.
struct PillButtonStyle: ButtonStyle {
    var fill: Color = Theme.ink
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(Theme.sentence(17, weight: .semibold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 54)
            .background(fill.opacity(configuration.isPressed ? 0.85 : 1), in: Capsule())
    }
}
