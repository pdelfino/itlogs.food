import Foundation
import Testing
@testable import ItlogsFood

@Suite struct ProtocolTests {
    @Test func serverMessagesDecodeLikeThePythonSide() throws {
        let json = #"{"kind":"entry","entry":{"index":1,"food":"cooked white rice","grams":87.0,"status":"agreed","reads":[{"food":"cooked white rice","grams":87.0,"confidence":0.9}],"nutrients":{"kcal":113.1,"protein_g":2.35,"carbs_g":24.53,"fat_g":0.26,"fiber_g":0.35,"sodium_mg":0.9},"t_ms":2000}}"#
        let msg = try JSONDecoder().decode(ServerMessage.self, from: Data(json.utf8))
        #expect(msg.kind == "entry")
        #expect(msg.entry?.grams == 87)
        #expect(msg.entry?.nutrients?.kcal == 113.1)
    }

    @Test func clientCaptureMessageEncodesOnlyWhatIsSet() throws {
        let data = try JSONEncoder().encode(ClientMessage(kind: "capture", capture: CaptureMeta(t_ms: 50)))
        let text = String(decoding: data, as: UTF8.self)
        #expect(text.contains(#""kind":"capture""#))
        #expect(!text.contains("voice"))
    }

    @MainActor @Test func controllerAppliesAskEntryAndStateMessages() {
        let c = SessionController()
        c.handle(ServerMessage(kind: "ask", ask: Question(text: "rice: 81 or 87 grams?", foods: ["rice"], grams: [81, 87])))
        #expect(c.question?.text == "rice: 81 or 87 grams?")
        c.handle(ServerMessage(kind: "entry", entry: Entry(index: 1, food: "rice", grams: 81, status: "corrected", t_ms: 3000)))
        #expect(c.entries.count == 1 && c.question == nil)
        c.handle(ServerMessage(kind: "state", entries: []))
        #expect(c.entries.isEmpty)
    }
}
