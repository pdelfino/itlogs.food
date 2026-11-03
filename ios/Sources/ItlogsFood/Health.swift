import Foundation
import HealthKit

/// Apple Health: every confirmed entry becomes one food correlation (`HKCorrelationType.food`)
/// holding six dietary samples: energy, protein, carbohydrates, total fat, fiber, sodium. The food
/// name and the grams ride in the metadata, so the Health app shows "red apple, 112 g" and any
/// reader (Health Auto Export, Pedro's pipeline) can rebuild the entry (#3).
@MainActor
final class Health {
    private let store = HKHealthStore()

    static var available: Bool { HKHealthStore.isHealthDataAvailable() }

    private static let energy = HKQuantityType(.dietaryEnergyConsumed)
    private static let protein = HKQuantityType(.dietaryProtein)
    private static let carbs = HKQuantityType(.dietaryCarbohydrates)
    private static let fat = HKQuantityType(.dietaryFatTotal)
    private static let fiber = HKQuantityType(.dietaryFiber)
    private static let sodium = HKQuantityType(.dietarySodium)
    private static let food = HKCorrelationType(.food)

    private static var writeTypes: Set<HKSampleType> {
        [energy, protein, carbs, fat, fiber, sodium]
    }

    /// Asks once; Health remembers. Returns false when the wearer declined or Health is absent.
    func authorize() async -> Bool {
        guard Self.available else { return false }
        do {
            try await store.requestAuthorization(toShare: Self.writeTypes, read: [])
        } catch {
            Diag.send("health: authorization threw \(String(describing: error))")
            return false
        }
        // sharing status is per type; energy stands for the set
        let status = store.authorizationStatus(for: Self.energy)
        Diag.send("health: authorization \(String(describing: status.rawValue)) (2 = sharing authorized)")
        return status == .sharingAuthorized
    }

    /// Writes the entries that have nutrients; returns how many were saved. Entries without a
    /// nutrient row (unknown food) are skipped: grams alone have no Health type.
    func save(_ entries: [Entry], at date: Date = Date()) async throws -> Int {
        var saved = 0
        for e in entries {
            guard let n = e.nutrients else { continue }
            let when = date.addingTimeInterval(-Double(entries.count - e.index))  // keeps the order
            let meta: [String: Any] = [
                HKMetadataKeyFoodType: e.food,
                "food.itlogs.grams": e.grams,
                "food.itlogs.status": e.status,
            ]
            func q(_ type: HKQuantityType, _ value: Double, _ unit: HKUnit) -> HKQuantitySample {
                HKQuantitySample(type: type, quantity: HKQuantity(unit: unit, doubleValue: value), start: when, end: when)
            }
            let samples: Set<HKSample> = [
                q(Self.energy, n.kcal, .kilocalorie()),
                q(Self.protein, n.protein_g, .gram()),
                q(Self.carbs, n.carbs_g, .gram()),
                q(Self.fat, n.fat_g, .gram()),
                q(Self.fiber, n.fiber_g, .gram()),
                q(Self.sodium, n.sodium_mg, .gramUnit(with: .milli)),
            ]
            let correlation = HKCorrelation(type: Self.food, start: when, end: when, objects: samples, metadata: meta)
            try await store.save(correlation)
            saved += 1
        }
        Diag.send("health: saved \(saved) of \(entries.count) entries")
        return saved
    }
}
