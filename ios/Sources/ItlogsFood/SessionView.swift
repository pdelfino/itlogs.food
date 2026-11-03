import SwiftUI

/// The weighing screen, direction A: the number the glasses just read, huge, in the digital face;
/// the food under it; one line of state; the meal as a ledger; one pill button. Everything else
/// is behind the gear (SettingsView). The meal's table and Apple Health are the review sheet.
struct SessionView: View {
    @Bindable var session: SessionController
    @State private var showSettings = false
    @State private var bigPreview = false

    @State private var now = Date()
    private let clock = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        ZStack {
            Theme.paper.ignoresSafeArea()
            VStack(spacing: 0) {
                topBar
                ScrollView {
                    VStack(spacing: 0) {
                        hero
                        ledger
                    }
                    .padding(.bottom, 24)
                }
                bottom
            }
        }
        .foregroundStyle(Theme.text)
        .onReceive(clock) { now = $0 }
        .sheet(isPresented: $session.reviewing) { ReviewView(session: session) }
        .sheet(isPresented: $showSettings) { SettingsView(session: session) }
        .sheet(isPresented: $bigPreview) {
            if let img = session.preview {
                Image(uiImage: img).resizable().scaledToFit().padding().presentationDetents([.large])
            }
        }
    }

    // MARK: pieces

    private var topBar: some View {
        HStack(alignment: .center, spacing: 12) {
            Text(sourceLine)
                .font(.system(size: 13))
                .foregroundStyle(Theme.mute)
            Spacer()
            if let img = session.preview {
                Button { bigPreview = true } label: {
                    Image(uiImage: img)
                        .resizable().scaledToFill()
                        .frame(width: 44, height: 66)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white, lineWidth: 2))
                        .shadow(color: .black.opacity(0.18), radius: 6, y: 2)
                }
                .buttonStyle(.plain)
            }
            Button { showSettings = true } label: {
                Image(systemName: "gearshape")
                    .font(.system(size: 17, weight: .medium))
                    .foregroundStyle(Theme.mute)
                    .frame(width: 36, height: 36)
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 18)
        .padding(.top, 8)
        .frame(height: 74)
    }

    private var sourceLine: String {
        let source = session.useGlasses ? "Meta glasses" : "This phone"
        if session.running { return session.cameraLive ? "\(source) · live" : "\(source) · starting" }
        return source
    }

    private var hero: some View {
        VStack(spacing: 6) {
            HStack(alignment: .lastTextBaseline, spacing: 6) {
                if let g = session.lastRead?.grams, g > 0 {
                    Text(g.formatted(.number.precision(.fractionLength(0))))
                        .font(Theme.digits(88))
                        .foregroundStyle(Theme.ink)
                        .contentTransition(.numericText())
                    Text("g").font(.system(size: 22)).foregroundStyle(Theme.mute)
                } else {
                    Text("---")
                        .font(Theme.digits(88))
                        .foregroundStyle(Theme.mute.opacity(0.35))
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.top, 10)
            Text(foodLine)
                .font(.system(size: 19))
                .foregroundStyle(Theme.text)
            Text(stateLine)
                .font(.system(size: 13))
                .foregroundStyle(session.error == nil ? Theme.orange : .red)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 24)
            if let q = session.question {
                Text(q.text).font(.system(size: 16, weight: .semibold)).padding(.top, 6)
            }
            if !session.lastHeard.isEmpty {
                Text("heard: \(session.lastHeard)").font(.system(size: 12)).foregroundStyle(Theme.mute)
            }
        }
        .padding(.bottom, 18)
    }

    private var foodLine: String {
        if let r = session.lastRead, r.food != "none" { return r.food }
        return session.running ? "nothing on the scale" : " "
    }

    private var stateLine: String {
        if let e = session.error { return e }
        if session.finishing { return "finishing the last reading…" }
        if session.starting { return "starting…" }
        if session.running && !session.cameraLive { return "camera starting… wait for \"Ready\"" }
        if session.watching { return "watching the scale · weigh at your pace" }
        if session.running { return "ready" }
        if !session.entries.isEmpty { return "meal weighed · check it below or start again" }
        return "glasses on, scale on · tap Start"
    }

    private var ledger: some View {
        VStack(spacing: 0) {
            if session.entries.isEmpty {
                Rectangle().fill(Theme.line).frame(height: 1)
                Text(session.running ? "foods land here as the scale settles" : "")
                    .font(.system(size: 13)).foregroundStyle(Theme.mute)
                    .frame(maxWidth: .infinity, minHeight: 44)
            } else {
                Rectangle().fill(Theme.line).frame(height: 1)
                ForEach(session.entries) { e in
                    HStack(alignment: .firstTextBaseline) {
                        Text(e.food).font(.system(size: 15))
                        Spacer(minLength: 8)
                        Text("\(e.grams.formatted(.number.precision(.fractionLength(0)))) g")
                            .font(Theme.digits(15))
                            .foregroundStyle(Theme.ink)
                        Text(e.nutrients.map { "\(Int($0.kcal.rounded())) kcal" } ?? "?")
                            .font(.system(size: 12)).foregroundStyle(Theme.mute)
                            .frame(width: 64, alignment: .trailing)
                    }
                    .padding(.vertical, 10)
                    Rectangle().fill(Theme.line).frame(height: 1)
                }
                if let t = session.totals {
                    HStack {
                        Text("total").font(.system(size: 13)).foregroundStyle(Theme.mute)
                        Spacer()
                        Text("\(Int(t.kcal.rounded())) kcal · \(Int(t.protein_g.rounded())) g protein")
                            .font(.system(size: 13)).foregroundStyle(Theme.mute)
                    }
                    .padding(.vertical, 8)
                }
            }
        }
        .padding(.horizontal, 18)
    }

    private var bottom: some View {
        VStack(spacing: 10) {
            if session.running {
                let left = max(0, Int((session.stopAfterSeconds - now.timeIntervalSince(session.startedAt ?? now)).rounded(.up)))
                Button(session.finishing ? "Finishing…" : (left > 0 ? "Stop (\(left))" : "Stop")) { Task { await session.stop() } }
                    .buttonStyle(PillButtonStyle(fill: Theme.orange))
                    .disabled(left > 0 || session.finishing)
                    .opacity(left > 0 || session.finishing ? 0.6 : 1)
                Button("Log it now") { session.capture() }
                    .font(.system(size: 14)).foregroundStyle(Theme.mute)
            } else {
                Button(session.starting ? "Starting…" : "Start") { Task { await session.start() } }
                    .buttonStyle(PillButtonStyle(fill: Theme.ink))
                    .disabled(session.starting)
                if !session.entries.isEmpty {
                    Button("Check the meal") { session.reviewing = true }
                        .font(.system(size: 14, weight: .medium)).foregroundStyle(Theme.orange)
                }
            }
        }
        .padding(.horizontal, 18)
        .padding(.top, 10)
        .padding(.bottom, 8)
        .background(Theme.paper)
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
