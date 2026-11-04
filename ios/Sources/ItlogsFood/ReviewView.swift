import SwiftUI

/// After Stop, direction A: a white sheet, the meal as a table (grams, protein, carbs, fat, kcal),
/// a totals row, one ink button that sends it to Apple Health. Nothing reaches Health without
/// that tap (#3). Sodium goes to Health without a column.
struct ReviewView: View {
    @Bindable var session: SessionController
    @Environment(\.dismiss) private var dismiss

    private var totals: Nutrients? { session.totals }
    private let fmt0: FloatingPointFormatStyle<Double> = .number.precision(.fractionLength(0))
    private let fmt1: FloatingPointFormatStyle<Double> = .number.precision(.fractionLength(1))

    var body: some View {
        ZStack {
            Theme.card.ignoresSafeArea()
            VStack(alignment: .leading, spacing: 0) {
                Text("Check the meal")
                    .font(Theme.sentence(22, weight: .semibold))
                    .foregroundStyle(Theme.ink)
                    .padding(.top, 22)
                    .padding(.bottom, 14)
                table
                Spacer(minLength: 16)
                if let today = session.healthToday {
                    Text(today).font(Theme.body(12)).foregroundStyle(Theme.mute).padding(.bottom, 8)
                }
                if let msg = session.healthMessage {
                    Text(msg).font(Theme.sentence(14)).foregroundStyle(session.healthSaved ? .green : Theme.accent).padding(.bottom, 8)
                }
                Button {
                    Task { await session.saveToHealth() }
                } label: {
                    Label(session.healthSaved ? "Saved to Apple Health" : "Send to Apple Health", systemImage: "heart.fill")
                }
                .buttonStyle(PillButtonStyle(fill: session.healthSaved ? Theme.mute : Theme.ink))
                .disabled(session.healthSaved || session.healthSaving)
                Button("Not now") { dismiss() }
                    .font(Theme.body(14)).foregroundStyle(Theme.mute)
                    .frame(maxWidth: .infinity)
                    .padding(.top, 12)
                    .padding(.bottom, 6)
            }
            .padding(.horizontal, 20)
        }
        .foregroundStyle(Theme.text)
        .presentationDetents([.large])
        .presentationCornerRadius(22)
        .task { await session.refreshHealthToday() }
    }

    private var table: some View {
        Grid(alignment: .trailing, horizontalSpacing: 10, verticalSpacing: 0) {
            GridRow {
                Text("Food").gridColumnAlignment(.leading)
                Text("g"); Text("P"); Text("C"); Text("F"); Text("kcal")
            }
            .font(Theme.body(11)).foregroundStyle(Theme.mute)
            .padding(.bottom, 6)
            ForEach(session.entries) { e in
                Rectangle().fill(Theme.line).frame(height: 1).gridCellColumns(6)
                GridRow {
                    Text(e.food).font(Theme.body(14)).gridColumnAlignment(.leading).lineLimit(2)
                    Text(e.grams, format: fmt0).font(Theme.digits(13, weight: .regular))
                    if let n = e.nutrients {
                        Text(n.protein_g, format: fmt1).font(Theme.digits(13, weight: .regular))
                        Text(n.carbs_g, format: fmt1).font(Theme.digits(13, weight: .regular))
                        Text(n.fat_g, format: fmt1).font(Theme.digits(13, weight: .regular))
                        Text(n.kcal, format: fmt0).font(Theme.digits(13, weight: .regular))
                    } else {
                        ForEach(0..<4, id: \.self) { _ in Text("?").foregroundStyle(Theme.mute) }
                    }
                }
                .padding(.vertical, 9)
            }
            if let t = totals {
                Rectangle().fill(Theme.ink).frame(height: 2).gridCellColumns(6)
                GridRow {
                    Text("Total").font(Theme.body(14, weight: .semibold)).gridColumnAlignment(.leading)
                    Text(session.entries.reduce(0) { $0 + $1.grams }, format: fmt0).font(Theme.digits(13, weight: .semibold))
                    Text(t.protein_g, format: fmt1).font(Theme.digits(13, weight: .semibold))
                    Text(t.carbs_g, format: fmt1).font(Theme.digits(13, weight: .semibold))
                    Text(t.fat_g, format: fmt1).font(Theme.digits(13, weight: .semibold))
                    Text(t.kcal, format: fmt0).font(Theme.digits(13, weight: .semibold))
                }
                .padding(.vertical, 9)
            }
        }
    }
}
