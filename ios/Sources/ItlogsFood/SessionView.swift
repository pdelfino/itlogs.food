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
                    Button("Install or update the glasses app (Meta AI)") { Task { await session.updateGlassesApp() } }
                    Toggle("Recognize speech on the phone (fallback)", isOn: $session.useDeviceSpeech)
                }
                Section("Now") {
                    if let r = session.lastRead {
                        LabeledContent("Read", value: r.grams.map { "\(r.food) · \($0.formatted()) g" } ?? r.food)
                    }
                    if session.watching { Text("Weighing: watching the scale").foregroundStyle(.orange) }
                    if let q = session.question { Text(q.text).bold() }
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
                        Button(session.watching ? "Done" : "Weighing") { session.setWeighing(!session.watching) }
                            .buttonStyle(.bordered).tint(session.watching ? .orange : nil)
                        Button("Log it") { session.capture() }.buttonStyle(.borderedProminent)
                        Spacer()
                        Button("Stop", role: .destructive) { Task { await session.stop() } }
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
