import SwiftUI

/// The weighing screen, direction A: the number the glasses just read, huge, in the digital face;
/// the food under it; the ear's sentence, readable at arm's length; the meal as a ledger; one pill
/// button. Everything else is behind the gear (SettingsView). The meal's table and Apple Health
/// are the review sheet.
struct SessionView: View {
    @Bindable var session: SessionController
    @State private var showSettings = false
    @State private var bigPreview = false

    @State private var now = Date()
    private let clock = Timer.publish(every: 1, on: .main, in: .common).autoconnect()

    var body: some View {
        ZStack {
            // a soft wash at the top, the paper below (identity v2, #20)
            LinearGradient(colors: [Theme.wash, Theme.paper], startPoint: .top, endPoint: .center)
                .ignoresSafeArea()
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
                .font(Theme.body(13))
                .foregroundStyle(Theme.mute)
            Spacer()
            if let img = session.preview {
                Button { bigPreview = true } label: {
                    Image(uiImage: img)
                        .resizable().scaledToFill()
                        .frame(width: 44, height: 66)
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.white, lineWidth: 2))
                        .shadow(color: Theme.ink.opacity(0.18), radius: 6, y: 2)
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
        VStack(spacing: 8) {
            HStack(alignment: .lastTextBaseline, spacing: 6) {
                if let g = session.lastRead?.grams, g > 0 {
                    Text(g.formatted(.number.precision(.fractionLength(0))))
                        .font(Theme.digits(88))
                        .foregroundStyle(Theme.ink)
                        .contentTransition(.numericText())
                    Text("g").font(Theme.body(22)).foregroundStyle(Theme.mute)
                } else {
                    Text("---")
                        .font(Theme.digits(88))
                        .foregroundStyle(Theme.mute.opacity(0.35))
                }
            }
            .frame(maxWidth: .infinity)
            .padding(.top, 10)
            Text(foodLine)
                .font(Theme.sentence(22, weight: .semibold))
                .foregroundStyle(Theme.ink)
            // the instruction: the second thing read after the number (was 13 pt, #20)
            Text(stateLine)
                .font(Theme.sentence(17))
                .foregroundStyle(session.error == nil ? Theme.accent : .red)
                .multilineTextAlignment(.center)
                .lineSpacing(3)
                .padding(.horizontal, 28)
                .padding(.top, 4)
            if let q = session.question {
                Text(q.text).font(Theme.sentence(17, weight: .semibold)).foregroundStyle(Theme.ink).padding(.top, 6)
            }
            if !session.lastHeard.isEmpty {
                Text("heard: \(session.lastHeard)").font(Theme.body(12)).foregroundStyle(Theme.mute)
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
        if session.finishing { return "Finishing the last reading…" }
        if session.starting { return "Starting…" }
        if session.running && !session.cameraLive { return "The camera is starting. Wait for \"Ready\"." }
        if session.watching { return "Watching the scale. Weigh at your pace." }
        if session.running { return "Ready." }
        if !session.entries.isEmpty { return "Meal weighed. Check it below, or start again." }
        return "Glasses on, scale on. Tap Start."
    }

    private var ledger: some View {
        VStack(spacing: 0) {
            if session.entries.isEmpty {
                Rectangle().fill(Theme.line).frame(height: 1)
                Text(session.running ? "Foods land here as the scale settles." : "")
                    .font(Theme.body(13)).foregroundStyle(Theme.mute)
                    .frame(maxWidth: .infinity, minHeight: 44)
            } else {
                Rectangle().fill(Theme.line).frame(height: 1)
                ForEach(session.entries) { e in
                    HStack(alignment: .firstTextBaseline) {
                        Text(e.food).font(Theme.body(15))
                        Spacer(minLength: 8)
                        Text("\(e.grams.formatted(.number.precision(.fractionLength(0)))) g")
                            .font(Theme.digits(15, weight: .semibold))
                            .foregroundStyle(Theme.ink)
                        Text(e.nutrients.map { "\(Int($0.kcal.rounded())) kcal" } ?? "?")
                            .font(Theme.body(12)).foregroundStyle(Theme.mute)
                            .frame(width: 64, alignment: .trailing)
                    }
                    .padding(.vertical, 10)
                    Rectangle().fill(Theme.line).frame(height: 1)
                }
                if let t = session.totals {
                    HStack {
                        Text("total").font(Theme.body(13)).foregroundStyle(Theme.mute)
                        Spacer()
                        Text("\(Int(t.kcal.rounded())) kcal · \(Int(t.protein_g.rounded())) g protein")
                            .font(Theme.body(13)).foregroundStyle(Theme.mute)
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
                    .buttonStyle(PillButtonStyle(fill: Theme.accent))
                    .disabled(left > 0 || session.finishing)
                    .opacity(left > 0 || session.finishing ? 0.6 : 1)
                Button("Log it now") { session.capture() }
                    .font(Theme.body(14)).foregroundStyle(Theme.mute)
            } else {
                Button(session.starting ? "Starting…" : "Start") { Task { await session.start() } }
                    .buttonStyle(PillButtonStyle(fill: Theme.ink))
                    .disabled(session.starting)
                if !session.entries.isEmpty {
                    Button("Check the meal") { session.reviewing = true }
                        .font(Theme.sentence(15)).foregroundStyle(Theme.accent)
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
