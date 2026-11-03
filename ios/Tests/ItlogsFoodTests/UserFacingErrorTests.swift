import Testing
@testable import ItlogsFood

@Suite struct UserFacingErrorTests {
    @Test func everyMessageIsPlainAndCarriesItsCode() {
        for kind in UserFacingError.allCases {
            let m = kind.message
            #expect(!m.contains("Error Domain"))
            #expect(!m.contains("Code="))
            #expect(!m.contains("MWDAT"))
            #expect(!m.contains("Swift."))
            #expect(m.hasSuffix(".") && m.count > 20)
            #expect(kind.code.allSatisfy { $0.isLowercase || $0 == "_" })
            #expect(kind.text.hasSuffix("(ref: \(kind.code))"))
        }
    }

    @Test func theScreenTextIsTheSentenceWithTheCode() {
        // report() itself is not called here: it posts to Diag and telemetry, which a unit test
        // must not do (the first run sent a fake start_failed to the server's phone log)
        let s = UserFacingError.startFailed.text
        #expect(s.hasPrefix("Couldn't start."))
        #expect(s.hasSuffix("(ref: start_failed)"))
    }
}
