import SwiftUI

struct SessionView: View {
    @Bindable var session: SessionController
    @State private var urlText = ""

    var body: some View {
        NavigationStack {
            List {
                Section("Server") {
                    TextField("ws://host:8000/ws/session", text: $urlText)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .onSubmit { if let u = URL(string: urlText) { session.serverURL = u } }
                    Toggle("Use the glasses", isOn: $session.useGlasses)
                    Button("Connect this app to the glasses (once)") { Task { await session.registerGlasses() } }
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
                    if session.watching { Text("Weighing: watching the scale. Stop to hear the list.").foregroundStyle(.orange) }
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
                            if let n = e.nutrients { Text("· \(Int(n.kcal)) kcal").foregroundStyle(.secondary) }
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
            .safeAreaInset(edge: .bottom) {
                Text(Self.versionLine).font(.caption2).foregroundStyle(.secondary).padding(.bottom, 4)
            }
            .toolbar {
                ToolbarItemGroup(placement: .bottomBar) {
                    if session.running {
                        Button("Log it") { session.capture() }.buttonStyle(.bordered)
                        Spacer()
                        Button("Stop") { Task { await session.stop() } }.buttonStyle(.borderedProminent).tint(.orange)
                    } else {
                        Button("Start") { Task { await session.start() } }
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
