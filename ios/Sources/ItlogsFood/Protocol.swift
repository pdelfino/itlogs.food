import Foundation

// Mirror of server/itlogs/models.py. Keep the two in sync by hand; both are small.

struct FrameMeta: Codable, Sendable {
    var t_ms: Int
    var width: Int
    var height: Int
}

struct VoiceText: Codable, Sendable {
    var t_ms: Int
    var text: String
}

struct AudioMeta: Codable, Sendable {
    var t_ms: Int
    var encoding: String = "PCM_24KHZ"
}

struct CaptureMeta: Codable, Sendable {
    var t_ms: Int
}

struct WatchMeta: Codable, Sendable {
    var on: Bool
    var t_ms: Int = 0
    var ask: Bool = false
}

struct ClientMessage: Codable, Sendable {
    var kind: String  // frame | audio | voice | capture | watch | end_session
    var frame: FrameMeta? = nil
    var audio: AudioMeta? = nil
    var voice: VoiceText? = nil
    var capture: CaptureMeta? = nil
    var watch: WatchMeta? = nil
}

struct EntryRead: Codable, Sendable, Equatable {
    var food: String
    var grams: Double?
    var confidence: Double
}

struct Nutrients: Codable, Sendable, Equatable {
    var kcal: Double
    var protein_g: Double
    var carbs_g: Double
    var fat_g: Double
    var fiber_g: Double
    var sodium_mg: Double
}

struct Entry: Codable, Sendable, Equatable, Identifiable {
    var index: Int
    var food: String
    var grams: Double
    var status: String  // agreed | confirmed | corrected
    var reads: [EntryRead] = []
    var nutrients: Nutrients?
    var t_ms: Int
    var id: Int { index }
}

struct Question: Codable, Sendable, Equatable {
    var text: String
    var foods: [String]
    var grams: [Double]
}

struct ServerMessage: Codable, Sendable {
    var kind: String  // read | entry | ask | say | state
    var read: EntryRead? = nil
    var entry: Entry? = nil
    var ask: Question? = nil
    var say: String? = nil
    var entries: [Entry]? = nil
    var watching: Bool? = nil
}
