import Foundation
import os

/// The WebSocket to the server. Sends a JSON ClientMessage, then the JPEG bytes for frames.
/// Receives JSON ServerMessages and hands them to `onMessage`.
actor StreamClient {
    private let log = Logger(subsystem: "food.itlogs", category: "stream")
    private var task: URLSessionWebSocketTask?
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()
    private var onMessage: (@Sendable (ServerMessage) -> Void)?

    func connect(url: URL, onMessage: @escaping @Sendable (ServerMessage) -> Void) {
        self.onMessage = onMessage
        let task = URLSession.shared.webSocketTask(with: url)
        self.task = task
        task.resume()
        log.info("connected to \(url.absoluteString, privacy: .public)")
        Task { await self.receiveLoop() }
    }

    func disconnect() {
        task?.cancel(with: .normalClosure, reason: nil)
        task = nil
    }

    func send(frame jpeg: Data, meta: FrameMeta) async throws {
        try await send(ClientMessage(kind: "frame", frame: meta))
        try await task?.send(.data(jpeg))
    }

    func send(audio pcm: Data, tMs: Int) async throws {
        try await send(ClientMessage(kind: "audio", audio: AudioMeta(t_ms: tMs)))
        try await task?.send(.data(pcm))
    }

    func send(voice text: String, tMs: Int) async throws {
        try await send(ClientMessage(kind: "voice", voice: VoiceText(t_ms: tMs, text: text)))
    }

    func watch(on: Bool, tMs: Int, ask: Bool = false) async throws { try await send(ClientMessage(kind: "watch", watch: WatchMeta(on: on, t_ms: tMs, ask: ask))) }
    func capture(tMs: Int) async throws { try await send(ClientMessage(kind: "capture", capture: CaptureMeta(t_ms: tMs))) }
    func endSession() async throws { try await send(ClientMessage(kind: "end_session")) }

    private func send(_ msg: ClientMessage) async throws {
        let data = try encoder.encode(msg)
        try await task?.send(.string(String(decoding: data, as: UTF8.self)))
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
