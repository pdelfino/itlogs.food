import AVFoundation
import SwiftUI

/// The phone camera reads a barcode (#13, option B): EAN-13, EAN-8, UPC-E or Code 128. The first
/// code seen is handed back and the sheet closes; the server looks the product up and the ear
/// says its name. Works while the glasses stream (their camera is not this one).
struct BarcodeScanView: View {
    var onCode: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var found: String?

    var body: some View {
        ZStack(alignment: .bottom) {
            BarcodeCamera { code in
                guard found == nil else { return }
                found = code
                onCode(code)
                dismiss()
            }
            .ignoresSafeArea()
            VStack(spacing: 10) {
                Text("Point the camera at the barcode on the wrapper.")
                    .font(Theme.sentence(17))
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 28)
                Button("Cancel") { dismiss() }
                    .buttonStyle(PillButtonStyle(fill: Theme.ink))
                    .padding(.horizontal, 18)
            }
            .padding(.bottom, 24)
        }
        .background(Color.black)
    }
}

/// AVCaptureSession with a metadata output; the preview layer fills the view.
private struct BarcodeCamera: UIViewControllerRepresentable {
    var onCode: (String) -> Void

    func makeUIViewController(context: Context) -> BarcodeCameraController {
        let vc = BarcodeCameraController()
        vc.onCode = onCode
        return vc
    }

    func updateUIViewController(_ vc: BarcodeCameraController, context: Context) {}
}

// the delegate is called on the main queue (set below), so the conformance is main-actor isolated
final class BarcodeCameraController: UIViewController, @MainActor AVCaptureMetadataOutputObjectsDelegate {
    var onCode: ((String) -> Void)?
    private let session = AVCaptureSession()
    private var preview: AVCaptureVideoPreviewLayer?
    private let queue = DispatchQueue(label: "food.itlogs.barcode")
    private var delivered = false

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device),
              session.canAddInput(input) else {
            Diag.send("barcode: no camera")
            return
        }
        session.addInput(input)
        let output = AVCaptureMetadataOutput()
        guard session.canAddOutput(output) else { return }
        session.addOutput(output)
        output.setMetadataObjectsDelegate(self, queue: .main)
        output.metadataObjectTypes = [.ean13, .ean8, .upce, .code128].filter {
            output.availableMetadataObjectTypes.contains($0)
        }
        let layer = AVCaptureVideoPreviewLayer(session: session)
        layer.videoGravity = .resizeAspectFill
        layer.frame = view.bounds
        view.layer.addSublayer(layer)
        preview = layer
        queue.async { [session] in session.startRunning() }
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        preview?.frame = view.bounds
    }

    override func viewWillDisappear(_ animated: Bool) {
        super.viewWillDisappear(animated)
        queue.async { [session] in if session.isRunning { session.stopRunning() } }
    }

    func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objects: [AVMetadataObject], from connection: AVCaptureConnection) {
        guard !delivered,
              let code = objects.compactMap({ ($0 as? AVMetadataMachineReadableCodeObject)?.stringValue }).first else { return }
        delivered = true
        Diag.send("barcode: \(code)")
        onCode?(code)
    }
}
