import Foundation
import os

/// The WebSocket to the server. One outbound queue, drained in order by one task, so a frame's
/// JSON meta and its JPEG bytes are never split by another message. On 2026-NOVEMBER-03 at 09:27
/// and 09:28 the socket opened seconds after the glasses stream; every frame task had queued its
/// meta ahead of its bytes, the server read a second meta where it expected bytes and dropped
/// the session, and two runs logged nothing. Frames are also dropped while one is still being
/// sent (the newest wins), so a slow link never builds a backlog. `connect` returns only once
/// the handshake is done, or throws, so Start can say that the server is not there.
actor StreamClient {
    enum Failure: LocalizedError {
        case timeout(URL, TimeInterval)
        case unreachable(URL, String)
        case closed(Int)

        var errorDescription: String? {
            switch self {
            case let .timeout(url, s):
                return "The server at \(url.absoluteString) did not answer within \(Int(s)) s. Is make run-live up on the Mac, and is the phone on the same Wi-Fi?"
            case let .unreachable(url, why):
                return "Could not reach the server at \(url.absoluteString): \(why)"
            case let .closed(code):
                return "The server closed the connection (code \(code))."
            }
        }
    }

    private enum Outgoing {
        case text(String)
        case paired(String, Data)  // a meta and its bytes: sent back to back, never split
    }

    private let log = Logger(subsystem: "food.itlogs", category: "stream")
    private var session: URLSession?
    private var task: URLSessionWebSocketTask?
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()
    private var onMessage: (@Sendable (ServerMessage) -> Void)?
    private var queue: [Outgoing] = []
    private var pumping = false

    /// Opens the socket and returns once the server accepted it; throws after `timeout` seconds,
    /// or at once when the connection fails (nothing listening, no route).
    func connect(url: URL, timeout: TimeInterval = 10, onMessage: @escaping @Sendable (ServerMessage) -> Void) async throws {
        self.onMessage = onMessage
        queue.removeAll()
        let handshake = Handshake()
        let session = URLSession(configuration: .default, delegate: handshake, delegateQueue: nil)
        let task = session.webSocketTask(with: url)
        self.session = session
        self.task = task
        let timer = Task {
            try await Task.sleep(for: .seconds(timeout))
            handshake.finish(.failure(Failure.timeout(url, timeout)))
            task.cancel()
        }
        do {
            try await withCheckedThrowingContinuation { (c: CheckedContinuation<Void, Error>) in
                handshake.wait(c)
                task.resume()
            }
        } catch {
            timer.cancel()
            self.task = nil
            session.invalidateAndCancel()
            self.session = nil
            throw (error as? Failure) ?? Failure.unreachable(url, error.localizedDescription)
        }
        timer.cancel()
        log.info("connected to \(url.absoluteString, privacy: .public)")
        Task { await self.receiveLoop() }
    }

    func disconnect() {
        queue.removeAll()
        task?.cancel(with: .normalClosure, reason: nil)
        task = nil
        session?.finishTasksAndInvalidate()
        session = nil
    }

    func send(frame jpeg: Data, meta: FrameMeta) throws {
        let text = try encode(ClientMessage(kind: "frame", frame: meta))
        // one frame waits at most: the newest replaces the one not yet picked up
        if let i = queue.lastIndex(where: { if case .paired = $0 { return true } else { return false } }) {
            queue[i] = .paired(text, jpeg)
        } else {
            queue.append(.paired(text, jpeg))
        }
        pump()
    }

    func send(audio pcm: Data, tMs: Int) throws {
        queue.append(.paired(try encode(ClientMessage(kind: "audio", audio: AudioMeta(t_ms: tMs))), pcm))
        pump()
    }

    func send(voice text: String, tMs: Int) throws {
        queue.append(.text(try encode(ClientMessage(kind: "voice", voice: VoiceText(t_ms: tMs, text: text)))))
        pump()
    }

    func watch(on: Bool, tMs: Int, ask: Bool = false) throws {
        queue.append(.text(try encode(ClientMessage(kind: "watch", watch: WatchMeta(on: on, t_ms: tMs, ask: ask)))))
        pump()
    }

    func capture(tMs: Int) throws {
        queue.append(.text(try encode(ClientMessage(kind: "capture", capture: CaptureMeta(t_ms: tMs)))))
        pump()
    }

    func send(barcode code: String, tMs: Int) throws {
        queue.append(.text(try encode(ClientMessage(kind: "barcode", barcode: BarcodeMeta(t_ms: tMs, code: code)))))
        pump()
    }

    func endSession() throws {
        queue.append(.text(try encode(ClientMessage(kind: "end_session"))))
        pump()
    }

    private func encode(_ msg: ClientMessage) throws -> String {
        String(decoding: try encoder.encode(msg), as: UTF8.self)
    }

    /// One drain loop at a time; it ends when the queue is empty or the socket is gone.
    private func pump() {
        guard !pumping else { return }
        pumping = true
        Task { await self.drain() }
    }

    private func drain() async {
        defer { pumping = false }
        while let task, !queue.isEmpty {
            let item = queue.removeFirst()
            do {
                switch item {
                case let .text(s):
                    try await task.send(.string(s))
                case let .paired(s, d):
                    try await task.send(.string(s))
                    try await task.send(.data(d))
                }
            } catch {
                log.error("send failed: \(error.localizedDescription, privacy: .public)")
                queue.removeAll()  // the socket is gone; nothing queued can go anywhere
                return
            }
        }
    }

    private func receiveLoop() async {
        while let task {
            do {
                let incoming = try await task.receive()
                if case let .string(text) = incoming,
                   let msg = try? decoder.decode(ServerMessage.self, from: Data(text.utf8)) {
                    onMessage?(msg)
                }
            } catch {
                log.error("receive failed: \(error.localizedDescription, privacy: .public)")
                return
            }
        }
    }
}

/// The handshake signal: URLSession tells its delegate when the socket opened, closed, or failed.
/// The continuation is resumed exactly once, whichever comes first (including the timeout).
private final class Handshake: NSObject, URLSessionWebSocketDelegate, @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Void, Error>?

    func wait(_ c: CheckedContinuation<Void, Error>) {
        lock.lock(); continuation = c; lock.unlock()
    }

    func finish(_ result: Result<Void, Error>) {
        lock.lock(); let c = continuation; continuation = nil; lock.unlock()
        c?.resume(with: result)
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didOpenWithProtocol protocol: String?) {
        finish(.success(()))
    }

    func urlSession(_ session: URLSession, webSocketTask: URLSessionWebSocketTask, didCloseWith closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        finish(.failure(StreamClient.Failure.closed(closeCode.rawValue)))
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error { finish(.failure(error)) }
    }
}
