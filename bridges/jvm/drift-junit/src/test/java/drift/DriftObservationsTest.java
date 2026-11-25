package drift;

import static org.junit.jupiter.api.Assertions.*;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class DriftObservationsTest {
    @TempDir Path dir;
    private String oldResolved;
    private String oldEvents;

    @BeforeEach
    void setUp() throws Exception {
        Drift.clearViews();
        oldResolved = System.getProperty(Drift.RESOLVED);
        oldEvents = System.getProperty(DriftListener.EVENTS);
        Path resolved = Files.createDirectories(dir.resolve("resolved"));
        Files.writeString(resolved.resolve("obs03.json"), """
                {
                  "drift":"0.3",
                  "id":"obs03",
                  "ref":"dr2b:111111111111",
                  "scope":{"writes":["owners","pets"]},
                  "cases":{
                    "clean-err":{"at":["http"],"writes":[],"when":{"req":{"eq":"bad"}},"then":{"status":{"eq":400},"msg":{"eq":"bad"}}},
                    "partial-write":{"at":["http"],"writes":["owners"],"when":{"req":{"eq":"ok"}},"then":{"status":{"eq":201}}},
                    "unrestricted-err":{"at":["http"],"when":{"req":{"eq":"bad"}},"then":{"status":{"eq":400}}},
                    "big-str":{"at":["http"],"writes":["owners","pets"],"when":{"req":{"eq":"big"}},"then":{"note":{"eq":"%s"}}}
                  }
                }
                """.formatted("x".repeat(1025)));
        System.setProperty(Drift.RESOLVED, resolved.toString());
    }

    @AfterEach
    void tearDown() {
        Drift.end();
        if (oldResolved == null) System.clearProperty(Drift.RESOLVED);
        else System.setProperty(Drift.RESOLVED, oldResolved);
        if (oldEvents == null) System.clearProperty(DriftListener.EVENTS);
        else System.setProperty(DriftListener.EVENTS, oldEvents);
    }

    @Test
    @SuppressWarnings("unchecked")
    void verifyAndCheckFrameEmitSchemaValidObservationsWithRealWritesAndStrict03Eq() throws Exception {
        // 1. Standalone order: verify() BEFORE checkFrame() (superseding event carries read + frame)
        Drift.end();
        Path evFile = dir.resolve("obs03-v-first.jsonl");
        System.setProperty(DriftListener.EVENTS, evFile.toString());
        Drift.Case sc = Drift.expect("obs03", "clean-err", "http");
        sc.verify("status", 400, "msg", "bad", "extra_ignored", "secret");
        sc.checkFrame(Map.of("owners", Map.of("writes", List.of()), "pets", Map.of("writes", List.of())));
        Drift.flushEvents();

        List<String> lines = Files.readAllLines(evFile);
        assertEquals(2, lines.size());
        Map<String, Object> ev0 = (Map<String, Object>) Json.parse(lines.get(0));
        assertNull(ev0.get("read"), "verify before checkFrame must not claim read before forbidden writes checked");
        Map<String, Object> ev1 = (Map<String, Object>) Json.parse(lines.get(1));
        assertEquals(List.of("clean-err"), ev1.get("read"));
        Map<String, Object> env = (Map<String, Object>) ((Map<String, Object>) ev1.get("observations")).get("clean-err");
        assertEquals("drift.observation/1", env.get("schema"));
        assertEquals("returned", env.get("outcome"));
        assertEquals(Map.of("msg", "bad", "status", 400L), env.get("payload"));
        assertEquals(Map.of("writes", List.of()), env.get("frame"));

        // 2. Partial write frame records actual written resource ("owners"), NOT empty []
        Drift.end();
        Path evPart = dir.resolve("obs03-partial.jsonl");
        System.setProperty(DriftListener.EVENTS, evPart.toString());
        Drift.Case sp = Drift.expect("obs03", "partial-write", "http");
        sp.checkFrame(Map.of("owners", Map.of("writes", List.of("saveOwner")), "pets", Map.of("writes", List.of())));
        sp.verify("status", 201);
        Drift.flushEvents();
        Map<String, Object> evP = (Map<String, Object>) Json.parse(Files.readAllLines(evPart).get(0));
        Map<String, Object> envP = (Map<String, Object>) ((Map<String, Object>) evP.get("observations")).get("partial-write");
        assertEquals(Map.of("writes", List.of("owners")), envP.get("frame"));

        // 3. Unobserved forbidden resource in non-strict checkFrame withholds frame observation
        Drift.begin(null);
        Drift.Case cUnobs = Drift.expect("obs03", "clean-err", "http");
        cUnobs.verify("status", 400, "msg", "bad");
        DriftUiChecks.checkFrame(cUnobs, Map.of("owners", Map.of("observed", false), "pets", Map.of("writes", 0)), false);
        StringBuilder sb = new StringBuilder("{");
        DriftObservations.appendField(sb, "obs03", "passed", List.of("clean-err"));
        assertEquals("{", sb.toString(), "unobserved frame must withhold observation");
        Drift.end();

        // 4. D289 inherited permissions: omitted case writes skips allowed resource cleanly
        Drift.begin(null);
        Drift.Case cInh = Drift.expect("obs03", "unrestricted-err", "http");
        assertDoesNotThrow(() -> cInh.checkFrame(Map.of("owners", Map.of("writes", 2))));
        // 5. Strict 0.3 numeric eq rejects 1e-10 slack without declared tol
        assertThrows(AssertionError.class, () -> cInh.verify("status", 400.0000000001));
        // 6. Oversized payload omits observation safely
        assertNull(DriftObservations.serialize(Map.of("note", "x".repeat(1025)), Set.of("note")));
        Drift.end();
    }

    @Test
    @SuppressWarnings("unchecked")
    void f2AndF3ExactNeedSetSkipsUnusedAncestorPointersAndCountsUnicodeCodePoints() throws Exception {
        Path resolved = dir.resolve("resolved");
        Files.writeString(resolved.resolve("proj-need.json"), """
                {
                  "drift":"0.3",
                  "id":"proj-need",
                  "ref":"dr2b:444444444444",
                  "projections":{"then":{"breaker_blob":"/breaker","state":"/breaker/state","total":"/breaker/total","ok_cnt":"/breaker/ok","err_cnt":"/breaker/err","inv_flag":"/breaker/inv","note":"/breaker/note"}},
                  "invariants":{"inv_flag":{"eq":true}},
                  "cases":{
                    "leaf-only":{"at":["unit"],"when":{"x":{"eq":1}},"then":{"state":{"eq":"OPEN"}}},
                    "peer-sum":{"at":["unit"],"when":{"x":{"eq":2}},"then":{"total":{"peer":{"sum":["then.ok_cnt","then.err_cnt"]}}}},
                    "astral-note":{"at":["unit"],"when":{"x":{"eq":3}},"then":{"note":{"eq":"%s"}}}
                  }
                }
                """.formatted("\uD83D\uDE00".repeat(600)));
        Drift.clearViews();

        // F2: Unused ancestor pointer breaker_blob (/breaker) containing 2048-char diagnostic_dump must NOT bloat or drop observation;
        // invariant inv_flag IS included.
        Drift.end();
        Path evLeaf = dir.resolve("f2-leaf.jsonl");
        System.setProperty(DriftListener.EVENTS, evLeaf.toString());
        Drift.Case cLeaf = Drift.expect("proj-need", "leaf-only", "unit");
        cLeaf.checkProjection(Map.of("breaker", Map.of(
                "state", "OPEN",
                "inv", true,
                "diagnostic_dump", "x".repeat(2048))));
        Drift.flushEvents();
        String leafLine = Files.readAllLines(evLeaf).get(0);
        assertFalse(leafLine.contains("diagnostic_dump"), "unused ancestor field leaked: " + leafLine);
        Map<String, Object> evL = (Map<String, Object>) Json.parse(leafLine);
        Map<String, Object> obsL = (Map<String, Object>) ((Map<String, Object>) evL.get("observations")).get("leaf-only");
        assertEquals(Map.of("breaker", Map.of("state", "OPEN", "inv", true)), obsL.get("payload"));

        // F2: Peer-referenced fields (ok_cnt, err_cnt) ARE included alongside total.
        Drift.end();
        Path evPeer = dir.resolve("f2-peer.jsonl");
        System.setProperty(DriftListener.EVENTS, evPeer.toString());
        Drift.Case cPeer = Drift.expect("proj-need", "peer-sum", "unit");
        cPeer.checkProjection(Map.of("breaker", Map.of(
                "total", 5, "ok", 3, "err", 2, "inv", true, "diagnostic_dump", "x".repeat(2048))));
        Drift.flushEvents();
        String peerLine = Files.readAllLines(evPeer).get(0);
        assertFalse(peerLine.contains("diagnostic_dump"), peerLine);
        Map<String, Object> obsP = (Map<String, Object>) ((Map<String, Object>) ((Map<String, Object>) Json.parse(peerLine)).get("observations")).get("peer-sum");
        assertEquals(Map.of("breaker", Map.of("total", 5L, "ok", 3L, "err", 2L, "inv", true)), obsP.get("payload"));

        // F2: UI observation payloads are suppressed.
        Drift.begin(null);
        Drift.Case cUi = Drift.expect("proj-need", "leaf-only", "unit");
        DriftObservations.recordPayload(cUi, Map.of("schema", "drift.ui-observation/1", "breaker", Map.of("state", "OPEN")),
                Map.of("state", Map.of("eq", "OPEN")), Map.of("state", "/breaker/state"));
        StringBuilder uiSb = new StringBuilder("{");
        DriftObservations.appendField(uiSb, "proj-need", "passed", List.of("leaf-only"));
        assertEquals("{", uiSb.toString(), "UI observation must be suppressed");
        Drift.end();

        // F3: 600 astral emoji (600 code points, 1200 UTF-16 code units, ~2440 UTF-8 bytes) succeeds.
        String emoji600 = "\uD83D\uDE00".repeat(600);
        assertEquals(1200, emoji600.length());
        assertEquals(600, emoji600.codePointCount(0, emoji600.length()));
        String okEmoji = DriftObservations.serialize(Map.of("note", emoji600), Set.of("note"));
        assertNotNull(okEmoji, "600 astral code points must fit under 1024-codepoint and 4096-byte caps");

        // F3: 1025 ASCII code points and lone surrogates (values and keys) are rejected cleanly.
        assertNull(DriftObservations.serialize(Map.of("note", "a".repeat(1025)), Set.of("note")));
        assertNull(DriftObservations.serialize(Map.of("note", "bad\uD800val"), Set.of("note")));
        assertNull(DriftObservations.serialize(Map.of("note", "bad\uDC00val"), Set.of("note")));
        assertNull(DriftObservations.serialize(Map.of("note", Map.of("bad\uD800key", "ok")), Set.of("note")));
    }
}
