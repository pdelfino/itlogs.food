import AVFoundation
import Foundation
import UIKit

/// Where frames come from. The product source is the glasses through Meta's Wearables Device
/// Access Toolkit; the phone camera is the fallback for the simulator-free dev loop and the demo
/// plan B. Both deliver JPEGs with a timestamp; everything downstream is the same.
protocol FrameSource: Sendable {
    func start(_ sink: @escaping @Sendable (Data, FrameMeta) -> Void) async throws
    func stop() async
}

/// Back camera at a modest rate, JPEG-compressed on a background queue.
final class PhoneCameraSource: NSObject, FrameSource, AVCaptureVideoDataOutputSampleBufferDelegate, @unchecked Sendable {
    private let session = AVCaptureSession()
    private let queue = DispatchQueue(label: "food.itlogs.camera")
    private var sink: (@Sendable (Data, FrameMeta) -> Void)?
    private var started = Date()
    private var lastSent = Date.distantPast
    var fps: Double = 10

    func start(_ sink: @escaping @Sendable (Data, FrameMeta) -> Void) async throws {
        guard await AVCaptureDevice.requestAccess(for: .video) else {
            throw NSError(domain: "food.itlogs", code: 2, userInfo: [NSLocalizedDescriptionKey: "Camera permission denied"])
        }
        self.sink = sink
        session.beginConfiguration()
        session.sessionPreset = .hd1280x720
        guard let device = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
              let input = try? AVCaptureDeviceInput(device: device), session.canAddInput(input) else {
            throw NSError(domain: "food.itlogs", code: 3, userInfo: [NSLocalizedDescriptionKey: "No back camera"])
        }
        session.addInput(input)
        let output = AVCaptureVideoDataOutput()
        output.alwaysDiscardsLateVideoFrames = true
        output.setSampleBufferDelegate(self, queue: queue)
        if session.canAddOutput(output) { session.addOutput(output) }
        session.commitConfiguration()
        started = Date()
        queue.async { self.session.startRunning() }
    }

    func stop() async {
        queue.async { self.session.stopRunning() }
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        let now = Date()
        guard now.timeIntervalSince(lastSent) >= 1 / fps,
              let buffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        lastSent = now
        let image = CIImage(cvPixelBuffer: buffer)
        let context = CIContext()
        guard let cg = context.createCGImage(image, from: image.extent),
              let jpeg = UIImage(cgImage: cg).jpegData(compressionQuality: 0.6) else { return }
        let meta = FrameMeta(t_ms: Int(now.timeIntervalSince(started) * 1000), width: cg.width, height: cg.height)
        sink?(jpeg, meta)
    }
}
