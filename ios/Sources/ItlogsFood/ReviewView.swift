import SwiftUI

/// After Stop: the meal as a table, one row per food (grams, protein, carbs, fat, kcal, sodium),
/// a totals row, and one button that sends it all to Apple Health. Nothing reaches Health
/// without this tap (#3).
struct ReviewView: View {
    @Bindable var session: SessionController
    @Environment(\.dismiss) private var dismiss

    private var totals: Nutrients? { session.totals }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Grid(alignment: .trailing, horizontalSpacing: 10, verticalSpacing: 8) {
                        GridRow {
                            Text("Food").gridColumnAlignment(.leading)
                            Text("g"); Text("P"); Text("C"); Text("F"); Text("kcal"); Text("Na mg")
                        }
                        .font(.caption).foregroundStyle(.secondary)
                        Divider()
                        ForEach(session.entries) { e in
                            GridRow {
                                Text(e.food).gridColumnAlignment(.leading).lineLimit(2)
                                Text(e.grams.formatted(.number.precision(.fractionLength(0))))
                                if let n = e.nutrients {
                                    Text(n.protein_g, format: .number.precision(.fractionLength(1)))
                                    Text(n.carbs_g, format: .number.precision(.fractionLength(1)))
                                    Text(n.fat_g, format: .number.precision(.fractionLength(1)))
                                    Text(n.kcal, format: .number.precision(.fractionLength(0)))
                                    Text(n.sodium_mg, format: .number.precision(.fractionLength(0)))
                                } else {
                                    Text("?"); Text("?"); Text("?"); Text("?"); Text("?")
                                }
                            }
                            .font(.callout.monospacedDigit())
                        }
                        if let t = totals {
                            Divider()
                            GridRow {
                                Text("Total").bold().gridColumnAlignment(.leading)
                                Text(session.entries.reduce(0) { $0 + $1.grams }, format: .number.precision(.fractionLength(0)))
                                Text(t.protein_g, format: .number.precision(.fractionLength(1)))
                                Text(t.carbs_g, format: .number.precision(.fractionLength(1)))
                                Text(t.fat_g, format: .number.precision(.fractionLength(1)))
                                Text(t.kcal, format: .number.precision(.fractionLength(0)))
                                Text(t.sodium_mg, format: .number.precision(.fractionLength(0)))
                            }
                            .font(.callout.monospacedDigit()).bold()
                        }
                    }
                } header: {
                    Text("This meal")
                } footer: {
                    Text("P protein, C carbs, F fat, in grams for the portion. ? means the food is not in the nutrient table yet; its grams are still logged.")
                }
                Section {
                    if let msg = session.healthMessage { Text(msg).foregroundStyle(session.healthSaved ? .green : .orange) }
                    Button(session.healthSaved ? "Saved to Apple Health" : "OK, send to Apple Health") {
                        Task { await session.saveToHealth() }
                    }
                    .disabled(session.healthSaved || session.healthSaving)
                    Button("Not now", role: .cancel) { dismiss() }
                }
            }
            .navigationTitle("Check the meal")
        }
    }
}
