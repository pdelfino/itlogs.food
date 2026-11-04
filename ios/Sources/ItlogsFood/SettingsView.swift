import SwiftUI

/// Everything that is not the weighing itself: the server, the camera choice, the glasses
/// pairing, the experiments. Behind the gear so the main screen stays the display and one button.
struct SettingsView: View {
    @Bindable var session: SessionController
    @Environment(\.dismiss) private var dismiss
    @State private var urlText = ""

    var body: some View {
        NavigationStack {
            Form {
                Section("Camera") {
                    Picker("Camera", selection: $session.useGlasses) {
                        Text("Meta glasses").tag(true)
                        Text("This phone").tag(false)
                    }
                    .pickerStyle(.segmented)
                    if !session.useGlasses {
                        Label("Prop the phone on a stand or a tripod so the camera sees the scale's display with the grams, and keep this app open. The small picture on the main screen shows what it sees.", systemImage: "camera.on.rectangle")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                }
                Section("Glasses") {
                    Button("Connect this app to the glasses (once)") { Task { await session.registerGlasses() } }
                    Button("Forget and reconnect the glasses") { Task { await session.reconnectGlasses() } }
                    // always visible: the toolkit app on the glasses can be stale without the session saying so (#2)
                    Button("Install or update the glasses app (Meta AI)") { Task { await session.updateGlassesApp() } }
                }
                Section("Server") {
                    TextField("ws://host:8000/ws/session", text: $urlText)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .onSubmit { if let u = URL(string: urlText) { session.serverURL = u } }
                }
                Section("Experiments") {
                    Toggle("Video stream (off: stills)", isOn: $session.useStream)
                    Toggle("Recognize speech on the phone (fallback)", isOn: $session.useDeviceSpeech)
                    Toggle("Ask me after each food", isOn: $session.askEachFood)
                }
                Section {
                    Text(SessionView.versionLine).font(.caption).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Settings")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
            .onAppear { urlText = session.serverURL.absoluteString }
            // Done with no Return kept the old address, and Start then blamed the network
            .onDisappear { if let u = URL(string: urlText), u != session.serverURL { session.serverURL = u } }
        }
    }
}
