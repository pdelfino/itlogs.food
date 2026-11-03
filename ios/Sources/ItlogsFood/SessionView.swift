import SwiftUI

struct SessionView: View {
    @Bindable var session: SessionController
    @State private var urlText = ""

    @State private var now = Date()
    private let clock = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        NavigationStack {
            List {
                Section("Server") {
                    TextField("ws://host:8000/ws/session", text: $urlText)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .onSubmit { if let u = URL(string: urlText) { session.serverURL = u } }
                    Picker("Camera", selection: $session.useGlasses) {
                        Text("Meta glasses").tag(true)
                        Text("This phone").tag(false)
                    }
                    .pickerStyle(.segmented)
                    Button("Connect this app to the glasses (once)") { Task { await session.registerGlasses() } }
                    Button("Forget and reconnect the glasses (re-register)") { Task { await session.reconnectGlasses() } }
                    // always visible: the toolkit app on the glasses can be stale without the session saying so (#2)
                    Button("Install or update the glasses app (Meta AI)") { Task { await session.updateGlassesApp() } }
                    Toggle("Video stream instead of stills (experiment)", isOn: $session.useStream)
                    Toggle("Recognize speech on the phone (fallback)", isOn: $session.useDeviceSpeech)
                    Toggle("Ask me after each food", isOn: $session.askEachFood)
                }
                Section("Now") {
                    if let r = session.lastRead {
                        LabeledContent("Read", value: r.grams.map { "\(r.food) · \($0.formatted()) g" } ?? r.food)
                    }
                    if session.finishing {
                        Text("Finishing the last reading…").foregroundStyle(.orange)
                    } else if session.running && !session.cameraLive {
                        Text("Camera starting… wait for \"Ready\" before the first food.").foregroundStyle(.orange)
                    } else if session.watching {
                        Text("Watching the scale. Weigh at your pace; Stop to hear the list.").foregroundStyle(.green)
                    }
                    if let q = session.question { Text(q.text).bold() }
                    if !session.lastHeard.isEmpty { Text("Heard: \(session.lastHeard)").foregroundStyle(.secondary) }
                    if !session.lastSaid.isEmpty { Text("Said: \(session.lastSaid)").italic() }
                    if let e = session.error { Text(e).foregroundStyle(.red) }
                }
                Section("Logged") {
                    ForEach(session.entries) { e in
                        HStack {
                            Text("\(e.index). \(e.food)")
                            Spacer()
                            Text("\(e.grams, format: .number) g").monospacedDigit()
                            if let n = e.nutrients {
                                Text("· \(Int(n.kcal)) kcal · P \(Int(n.protein_g.rounded())) C \(Int(n.carbs_g.rounded())) F \(Int(n.fat_g.rounded()))")
                                    .font(.caption).foregroundStyle(.secondary)
                            }
                            Text(e.status).font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    if let t = session.totals {
                        LabeledContent("Total", value: "\(Int(t.kcal)) kcal · \(Int(t.protein_g)) g protein · \(Int(t.sodium_mg)) mg sodium")
                            .font(.caption)
                    }
                }
            }
            .navigationTitle("itlogs.food")
            .onReceive(clock) { now = $0 }
            .sheet(isPresented: $session.reviewing) { ReviewView(session: session) }
            .safeAreaInset(edge: .bottom) {
                Text(Self.versionLine).font(.caption2).foregroundStyle(.secondary).padding(.bottom, 4)
            }
            .toolbar {
                ToolbarItemGroup(placement: .bottomBar) {
                    if session.running {
                        Button("Log it") { session.capture() }.buttonStyle(.bordered)
                        Spacer()
                        let left = max(0, Int((session.stopAfterSeconds - now.timeIntervalSince(session.startedAt ?? now)).rounded(.up)))
                        Button(session.finishing ? "Finishing…" : (left > 0 ? "Stop (\(left))" : "Stop")) { Task { await session.stop() } }
                            .buttonStyle(.borderedProminent).tint(.orange).disabled(left > 0 || session.finishing)
                    } else {
                        if !session.entries.isEmpty {
                            Button("Review") { session.reviewing = true }.buttonStyle(.bordered)
                            Spacer()
                        }
                        Button(session.starting ? "Starting…" : "Start") { Task { await session.start() } }
                            .disabled(session.starting)
                    }
                }
            }
            .onAppear { urlText = session.serverURL.absoluteString }
        }
    }

    /// "itlogs.food 0.1.0 (57 · 0d29b65)": version, commit count, commit sha, from Info.plist.
    static var versionLine: String {
        let i = Bundle.main.infoDictionary ?? [:]
        let v = i["CFBundleShortVersionString"] as? String ?? "?"
        let b = i["CFBundleVersion"] as? String ?? "?"
        let sha = i["ItlogsGitSHA"] as? String ?? ""
        return "itlogs.food \(v) (\(b)\(sha.isEmpty ? "" : " · " + sha))"
    }
}
