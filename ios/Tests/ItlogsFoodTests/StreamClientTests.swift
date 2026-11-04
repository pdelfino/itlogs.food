import UIKit
import XCTest
@testable import ItlogsFood

/// Against the server on the Mac (skipped when :8000 is not up): forty frames fired at once must
/// keep their meta and bytes paired and the session must still answer end_session. Before
/// 2026-NOVEMBER-03 the second meta killed the session and Stop waited for a state that never came.
final class StreamClientTests: XCTestCase {
    private final class Inbox: @unchecked Sendable {
        private let lock = NSLock()
        private var kinds: [String] = []
        func add(_ k: String) { lock.lock(); kinds.append(k); lock.unlock() }
        var all: [String] { lock.lock(); defer { lock.unlock() }; return kinds }
    }

    private func serverIsUp() async -> Bool {
        guard let (_, r) = try? await URLSession.shared.data(from: URL(string: "http://localhost:8000/health")!) else { return false }
        return (r as? HTTPURLResponse)?.statusCode == 200
    }

    func testFramesStayPairedAndTheSessionEnds() async throws {
        // Opt in: against the live server this test makes real model calls on whatever provider
        // the server runs (a gray frame cost Baseten reads on 2026-NOVEMBER-03) and leaves a
        // recording on the T7.
        guard ProcessInfo.processInfo.environment["ITLOGS_LIVE_WS_TEST"] == "1" else {
            throw XCTSkip("set ITLOGS_LIVE_WS_TEST=1 to run against the server on localhost:8000")
        }
        guard await serverIsUp() else { throw XCTSkip("no server on localhost:8000") }
        let inbox = Inbox()
        let client = StreamClient()
        try await client.connect(url: URL(string: "ws://localhost:8000/ws/session")!, timeout: 5) { inbox.add($0.kind) }
        let jpeg = UIGraphicsImageRenderer(size: CGSize(width: 64, height: 64)).jpegData(withCompressionQuality: 0.5) { ctx in
            UIColor.gray.setFill(); ctx.fill(CGRect(x: 0, y: 0, width: 64, height: 64))
        }
        try await client.watch(on: true, tMs: 0)
        for i in 0..<40 {  // all at once, as the glasses callback does at 7 fps
            try await client.send(frame: jpeg, meta: FrameMeta(t_ms: i * 140, width: 64, height: 64))
        }
        try await client.endSession()
        for _ in 0..<150 where inbox.all.filter({ $0 == "state" }).count < 2 {  // up to 15 s
            try await Task.sleep(for: .milliseconds(100))
        }
        await client.disconnect()
        XCTAssertGreaterThanOrEqual(inbox.all.filter { $0 == "state" }.count, 2, "watch state and final state; got \(inbox.all)")
    }

    /// Set ITLOGS_WS_TEST_URL to a server running the fake provider, so no model is called.
    func testASocketThatDiesIsReportedAndDisconnectIsNot() async throws {
        guard let raw = ProcessInfo.processInfo.environment["ITLOGS_WS_TEST_URL"], let url = URL(string: raw) else {
            throw XCTSkip("set ITLOGS_WS_TEST_URL to a server on the fake provider")
        }
        let inbox = Inbox()
        let client = StreamClient()
        try await client.connect(url: url, timeout: 5, onClose: { inbox.add("closed") }) { inbox.add($0.kind) }
        try await client.endSession()  // the server answers and closes the socket from its side
        for _ in 0..<50 where !inbox.all.contains("closed") {
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTAssertEqual(inbox.all.filter { $0 == "closed" }.count, 1, "got \(inbox.all)")

        let quiet = Inbox()
        let second = StreamClient()
        try await second.connect(url: url, timeout: 5, onClose: { quiet.add("closed") }) { _ in }
        await second.disconnect()
        try await Task.sleep(for: .seconds(1))
        XCTAssertFalse(quiet.all.contains("closed"), "our own disconnect is not a lost socket")
    }

    func testConnectFailsFastWhenNothingListens() async {
        let client = StreamClient()
        do {
            try await client.connect(url: URL(string: "ws://localhost:9/ws/session")!, timeout: 3) { _ in }
            XCTFail("connected to a port with nothing on it")
        } catch {
            XCTAssertFalse((error as? LocalizedError)?.errorDescription?.isEmpty ?? true)
        }
    }
}
