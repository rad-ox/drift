#ifndef DRIFT_CPP_HPP
#define DRIFT_CPP_HPP

// Zero-dependency C++20 forward verification bridge for DRIFT (Unreal Engine / native C++).
// Conforms to drift.bridge-capabilities/1.

#include <bit>
#include <cmath>
#include <concepts>
#include <cstdint>
#include <fstream>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace drift {

using Str = std::string;
using SV = std::string_view;
template <class T> using Vec = std::vector<T>;
template <class V> using Map = std::map<Str, V>;
using Strs = Vec<Str>;
using CStrs = const Strs&;
using D = double;
using Dbls = Vec<D>;
using CDbls = const Dbls&;
using MapS = Map<Str>;
using SetS = std::set<Str>;
using Byte = unsigned char;
using Sz = std::size_t;
using std::fabs;
using std::isfinite;

inline constexpr const char* VERSION = "drift.cpp@0.11.0";
inline constexpr const char* BRIDGE_RUNTIME_BASELINE = "cpp-20";
inline constexpr char kHx[] = "0123456789abcdef";

[[noreturn]] inline void fail(const Str& m) { throw std::runtime_error(m); }
[[noreturn]] inline void badArg(const Str& m) { throw std::invalid_argument(m); }
[[noreturn]] inline void fk(SV k, SV m) { fail("then." + Str(k) + ": " + Str(m)); }
inline void fin(SV k, auto... vs) { (..., (!isfinite(vs) ? fk(k, "non-finite") : void())); }
inline Str ts(auto v) { return std::to_string(v); }

inline Str jsonEscape(SV s) {
    Str o;
    o.reserve(s.size());
    for (Sz i = 0; i < s.size();) {
        Byte c = Byte(s[i]);
        if (c < 0x80) {
            ++i;
            if (c == '"' || c == '\\') { o += '\\'; o += char(c); }
            else if (c < 0x20) { o += "\\u00"; o += kHx[c >> 4]; o += kHx[c & 15]; }
            else o += char(c);
            continue;
        }
        Sz n = c < 0xc2 ? 0 : c < 0xe0 ? 2 : c < 0xf0 ? 3 : c < 0xf5 ? 4 : 0;
        bool ok = n && i + n <= s.size();
        if (ok) {
            Byte b = Byte(s[i + 1]);
            ok = b >= (c == 0xe0 ? 0xa0 : c == 0xf0 ? 0x90 : 0x80) && b <= (c == 0xed ? 0x9f : c == 0xf4 ? 0x8f : 0xbf);
            for (Sz j = 2; ok && j < n; ++j) ok = (Byte(s[i + j]) & 0xc0) == 0x80;
        }
        if (!ok) fail("json.invalid_utf8");
        o.append(s.data() + i, n);
        i += n;
    }
    return o;
}

inline Str js(SV s) { return "\"" + jsonEscape(s) + "\""; }
inline Str jf(SV k, SV v) { return ",\"" + Str(k) + "\":" + Str(v); }
inline Str jfs(SV k, SV v) { return jf(k, js(v)); }
inline Str jfi(SV k, int v) { return jf(k, ts(v)); }

inline Str ja(CStrs xs) {
    Str o = "[";
    for (Sz i = 0; i < xs.size(); ++i) { if (i) o += ','; o += js(xs[i]); }
    return o + "]";
}
inline Str jsonStrArray(CStrs xs) { return ja(xs); }
inline Str jfa(SV k, CStrs xs) { return jf(k, ja(xs)); }
inline bool has(SV s, SV q) { return s.find_first_of(q) != SV::npos; }
inline bool blank(SV s) { return s.find_first_not_of(" \t\r\n\v\f") == SV::npos; }
inline bool validSnap(SV s) { return (s.size() == 40 || s.size() == 64) && s.find_first_not_of(kHx) == SV::npos; }

template <class M, class F> inline Str jMap(const M& m, F f) {
    Str o = "{";
    Sz i = 0;
    for (auto& [k, v] : m) { if (i++) o += ','; o += f(k, v); }
    return o + "}";
}

inline CStrs capabilities() {
    static const Strs c = {"predicates", "forbid_keys", "not_in", "tuning_invariants", "case_frames", "counterexample_replay", "sim_receipt"};
    return c;
}

inline Str bridgeCapabilitiesJson() {
    return "{\"schema\":\"drift.bridge-capabilities/1\",\"bridge\":\"drift.cpp\"" + jfs("version", VERSION) + jfs("runtime_baseline", BRIDGE_RUNTIME_BASELINE) + jfa("capabilities", capabilities()) + "}";
}

inline void requireCapabilities(CStrs req) {
    auto& c = capabilities();
    SetS cs(c.begin(), c.end());
    for (auto& r : req) if (!cs.count(r)) fail("bridge.capability_unsupported:" + r);
}

inline void checkMonotonic(SV k, CDbls s, SV d) {
    if (d.starts_with("strictly_")) d.remove_prefix(9);
    int m = d == "non_decreasing" ? 0 : d == "increasing" ? 1 : d == "non_increasing" ? 2 : d == "decreasing" ? 3 : -1;
    if (m < 0 || s.empty()) fk(k, m < 0 ? "mode" : "empty");
    fin(k, s[0]);
    for (Sz i = 1; i < s.size(); ++i) {
        fin(k, s[i]);
        D p = s[i - 1], c = s[i];
        if (!(m == 0 ? p <= c : m == 1 ? p < c : m == 2 ? p >= c : p > c)) fk(k, "monotonic @" + ts(i));
    }
}

inline void checkStepMaxDelta(SV k, CDbls s, D md) {
    if (s.empty() || !isfinite(md) || md < 0) fk(k, "step_max_delta");
    fin(k, s[0]);
    for (Sz i = 1; i < s.size(); ++i) {
        fin(k, s[i]);
        if (!(fabs(s[i] - s[i - 1]) <= md + 1e-9)) fk(k, "step_max_delta @" + ts(i));
    }
}

inline void checkSumTotal(SV k, CDbls s, D lo, D hi) {
    if (s.empty() || !isfinite(lo) || !isfinite(hi) || lo > hi) fk(k, "sum_total");
    D t = 0;
    for (D v : s) { fin(k, v); t += v; }
    fin(k, t);
    if (!(t + 1e-9 >= lo && t - 1e-9 <= hi)) fk(k, "sum_total " + ts(t));
}

inline void checkApprox(SV k, D a, D t, D at, D rt = 0) {
    fin(k, a, t, at, rt);
    if (at < 0 || rt < 0) fk(k, "tol");
    D r = at + rt * fabs(t);
    fin(k, r);
    if (!(fabs(a - t) <= r)) fk(k, ts(a) + "!=" + ts(t));
}

inline void fkf(SV k, const Str& f) { fk(k, "forbidden key \"" + f + "\""); }
inline void checkForbidKeys(SV k, const MapS& o, CStrs fks) { for (auto& f : fks) if (o.count(f)) fkf(k, f); }

inline bool isFrameMeta(const MapS& m) {
    static const SetS ks = {"writes", "operations", "events", "before", "after", "observed"};
    for (auto& [k, v] : m) if ((v.empty() || v.find_first_not_of(SV(kHx, 10)) != SV::npos) && !ks.count(k)) return false;
    return true;
}

inline void checkForbidKeysNested(SV k, const Map<MapS>& o, CStrs fks) {
    for (auto& f : fks) {
        if (o.count(f)) fkf(k, f);
        for (auto& [ck, cm] : o) if ((ck != "_frame" || f == "_frame" || !isFrameMeta(cm)) && cm.count(f)) fkf(k, f);
    }
}

inline void checkNotIn(SV k, SV a, CStrs b) { for (auto& x : b) if (a == x) fk(k, "not_in:" + Str(a)); }
inline void checkPrefix(SV k, SV a, SV p) { if (!a.starts_with(p)) fk(k, "prefix"); }
inline void checkSuffix(SV k, SV a, SV s) { if (!a.ends_with(s)) fk(k, "suffix"); }
inline void checkContains(SV k, SV a, SV n) { if (a.find(n) == SV::npos) fk(k, "contains"); }
inline void checkNonEmpty(SV k, SV a, bool w) { if (w ? a.empty() : !a.empty()) fk(k, "non_empty"); }

inline bool checkFrame(CStrs sw, CStrs aw, const Map<int>& ob, Strs& out, bool st = false) {
    SetS al(aw.begin(), aw.end());
    for (auto& [r, w] : ob) {
        if (w < 0) fail("frame.invalid:" + r);
        if (!al.count(r) && w) fail("undeclared write " + r + ":" + ts(w));
    }
    bool ok = true;
    for (auto& r : sw)
        if (al.count(r) || ob.count(r)) out.push_back("@frame:" + r);
        else if (st) fail("frame.observer_missing:" + r);
        else ok = false;
    return ok;
}

struct CounterexampleFixture { Str contract, caseId; MapS when; };

inline int replayCounterexamples(SV cid, SV csid, const Vec<CounterexampleFixture>& fxs, auto&& run) {
    int n = 0;
    for (auto& f : fxs) if (f.contract == cid && (f.caseId.empty() || f.caseId == csid)) { run(f.when); ++n; }
    return n;
}

inline void writeFileStrict(SV p, SV b) {
    std::ofstream f(Str(p), std::ios::trunc | std::ios::binary);
    f.write(b.data(), std::streamsize(b.size()));
    f.close();
    if (!f) fail("io.write_failed:" + Str(p));
}

inline Str canonicalTestId(SV s) {
    auto p = s.find('#');
    if (p == SV::npos || !p || p + 1 >= s.size() || has(s, "\r\n")) badArg("testId");
    SV c = s.substr(0, p), m = s.substr(p + 1);
    m = m.substr(0, m.find_first_of("(["));
    if (m.empty() || has(c, "# \t/\\[](") || has(m, "# \t[]")) badArg("testId");
    return Str(c) + "#" + Str(m);
}

inline Str validateTestClass(SV s) { Str c = canonicalTestId(s); return c.substr(0, c.find('#')); }

class ObsScalar {
    Str j_;
    explicit ObsScalar(Str j) : j_(std::move(j)) {}
public:
    using S = ObsScalar;
    static S null() { return S("null"); }
    static S boolean(bool v) { return S(v ? "true" : "false"); }
    static S integer(std::int64_t v) { constexpr std::int64_t M = 9007199254740991LL; return (v < -M || v > M) ? S("{\"$t\":\"i64\",\"v\":" + js(ts(v)) + "}") : S(ts(v)); }
    template <class T> requires (!std::signed_integral<T>) static S integer(T) = delete;
    static S floating(D v) {
        auto u = std::bit_cast<std::uint64_t>(v);
        Str h(16, '0');
        for (int i = 15; i >= 0; --i, u >>= 4) h[i] = kHx[u & 15];
        return S("{\"$t\":\"f64\",\"bits\":\"0x" + h + "\"}");
    }
    static S text(SV v) { return S(js(v)); }
    const Str& json() const { return j_; }
};

struct ReturnedObservation {
    Map<ObsScalar> payload;
    std::optional<Strs> frameWrites;
    bool frameRequired = true;
};
using ObservationRows = Vec<std::optional<ReturnedObservation>>;

struct ProofRun { Str contractId, digest, testId, caseId; bool verified = false; Str outcome = "passed", level = "unit"; MapS inputs; };

inline void emitObservedProofBatch(SV ep, SV mp, const Vec<ProofRun>& rs, const ObservationRows& ob, SV sn = "") {
    static constexpr char kC[] = "[\"rel-keys-guard/1\",\"rel-linear-balance/1\",\"rel-peer-sum/1\",\"rel-series/1\",\"rel-tol/1\",\"unit-conversion/1\"]";
    if (ob.size() != rs.size()) badArg("obs.size");
    if (!sn.empty() && !validSnap(sn)) badArg("snapshot");
    Str eo;
    SetS cs, ts_;
    Map<MapS> im;
    for (Sz idx = 0; idx < rs.size(); ++idx) {
        auto& r = rs[idx];
        bool ps = r.outcome == "passed";
        if ((!ps && r.outcome != "failed") || r.level.empty()) badArg("run");
        Str ct = canonicalTestId(r.testId), jc = js(r.caseId);
        cs.insert(ct.substr(0, ct.find('#')));
        ts_.insert(ct);
        bool ss = false, ok = ps && r.verified;
        auto& dst = im[ct];
        for (auto& [k, v] : r.inputs) {
            if (blank(k) || blank(v)) badArg("inputs");
            if (auto [it, ins] = dst.emplace(k, v); !ins && it->second != v) badArg("inputs.conflict:" + k);
            ss |= v == "sha256:self-stub" || k == ".drift/self-stub/" + r.contractId;
        }
        if (dst.empty()) im.erase(ct);
        bool i3 = r.digest.starts_with("dr2b:");
        Str of;
        if (i3 && ok && !ss && ob[idx]) {
            const auto& ro = *ob[idx];
            if (!ro.frameRequired || ro.frameWrites) {
                Str py = jMap(ro.payload, [](auto& k, auto& ov) {
                    if (ov.json().empty()) badArg("obs");
                    return js(k.starts_with('$') ? "$" + k : k) + ":" + ov.json();
                });
                if (py.size() <= 4096) {
                    Str fr = ro.frameWrites ? ("\"frame\":{\"writes\":" + ja(*ro.frameWrites) + "},") : "";
                    of = jf("observations", "{" + jc + ":{" + fr + "\"outcome\":\"returned\",\"payload\":" + py + ",\"schema\":\"drift.observation/1\"}}");
                }
            }
        }
        eo += (i3 ? Str("{\"capabilities\":") + kC + ",\"cases\":[" : "{\"cases\":[") + jc + "]"
            + jfs("contract", r.contractId) + jfs("digest", r.digest) + jfs("level", r.level) + of + jfs("outcome", r.outcome)
            + jf("read", "[" + (ok ? jc : "") + "]")
            + (i3 ? ",\"schema\":\"0.3\"" : "") + jfs("test", r.testId) + "}\n";
    }
    Str mo = "{\"classes\":" + ja({cs.begin(), cs.end()});
    if (!im.empty()) mo += jf("inputs", jMap(im, [](auto& t, auto& m) { return js(t) + ":" + jMap(m, [](auto& k, auto& v) { return js(k) + ":" + js(v); }); }));
    if (!sn.empty()) mo += jfs("snapshot", sn);
    mo += jfa("tests", {ts_.begin(), ts_.end()}) + ",\"version\":1}\n";
    writeFileStrict(ep, eo);
    writeFileStrict(mp, mo);
}

inline void emitProofBatch(SV ep, SV mp, const Vec<ProofRun>& rs, SV sn = "") {
    emitObservedProofBatch(ep, mp, rs, ObservationRows(rs.size()), sn);
}

inline void emitProofShard(SV ep, SV mp, SV id, SV dg, SV ti, SV ci, bool vr, SV f, SV h, SV oc = "passed", SV lv = "unit", SV sn = "") {
    ProofRun r{Str(id), Str(dg), Str(ti), Str(ci), vr, Str(oc), Str(lv), {}};
    if (!f.empty()) r.inputs[Str(f)] = Str(h);
    emitProofBatch(ep, mp, {r}, sn);
}

struct SimDivergentTick { int tick = 0; Str caseId, expectedHash, observedHash; };

inline void emitSimReceipt(
    SV sp, SV id, SV dg, SV si, SV rr, SV sr, SV sn,
    CStrs cv, CStrs cs, SV sd, SV ip, SV tj, int tk, CStrs pl,
    int wn, int mr, int rm, int lk, CStrs ac, CStrs cm, CStrs ic, CStrs iv,
    const Vec<SimDivergentTick>& dt = {}) {
    if (!validSnap(sn)) badArg("snapshot");
    if (tk < 0 || wn < 0 || mr < 0 || rm < 0 || lk < 0) badArg("sim.negative");
    Str dj = "[";
    for (Sz i = 0; i < dt.size(); ++i) {
        auto& [t, c, e, o] = dt[i];
        if (t < 0) badArg("sim.tick");
        if (i) dj += ',';
        dj += "{\"case\":" + js(c) + jfs("expected_hash", e) + jfs("observed_hash", o) + jfi("tick", t) + "}";
    }
    dj += ']';
    SetS cs_(cm.begin(), cm.end());
    bool ep = !ac.empty();
    for (auto& e : ac) if (!cs_.count(e)) ep = false;
    const char* oc = (!dt.empty() || rm > 0 || lk > 0 || !ic.empty()) ? "violated"
        : (tk <= 0 || wn <= 0 || mr <= 0 || pl.empty() || !ep) ? "inconclusive" : "passed";
    Str o = "{\"cases\":" + ja(cs) + jfs("code_snapshot", sn) + jfs("contract", id) + jfa("covered_scope", cv)
        + jfs("digest", dg) + jfs("outcome", oc)
        + ",\"rollback_invariance\":{\"leaked_ambient_mutations\":" + ts(lk) + jfi("max_rollback_frames", mr) + jfi("resim_mismatches", rm) + jfi("windows_tested", wn) + "}"
        + jfs("runner", "drift-cpp-sim") + jfs("runner_ref", rr)
        + ",\"save_epoch_compatibility\":{\"active_save_epochs\":" + ja(ac) + jfa("compatible_epochs", cm) + jfa("incompatible_epochs", ic) + jfa("invariants_checked", iv) + "}"
        + jfs("schema", "drift.sim-receipt/1") + jfs("simulation_id", si) + jfs("subject_ref", sr)
        + ",\"tick_determinism\":{\"divergent_ticks\":" + dj + jfs("input_stream_ref", ip) + jfa("platforms_compared", pl)
        + jfs("seed_corpus_ref", sd) + jfi("ticks_executed", tk) + jfs("trajectory_digest", tj) + "}}\n";
    writeFileStrict(sp, o);
}

inline void checkPlanBalance(SV k, D a, CDbls ad, CDbls sb, D tl = 1e-9) {
    fin(k, a, tl);
    if (tl < 0) fk(k, "tol");
    D t = 0;
    for (D v : ad) { fin(k, v); t += v; }
    for (D v : sb) { fin(k, v); t -= v; }
    fin(k, t);
    if (!(fabs(a - t) <= tl)) fk(k, "balance " + ts(t));
}

inline void checkPlanPeerSum(SV k, D a, CDbls p, D tl = 1e-9) { checkPlanBalance(k, a, p, {}, tl); }

inline void checkPlanScaledBounds(SV k, D a, D cv, bool h0, D lo, bool h1, D hi) {
    fin(k, a, cv);
    if (h0) { fin(k, lo); if (!(a + 1e-9 >= lo * cv)) fk(k, "min"); }
    if (h1) { fin(k, hi); if (!(a - 1e-9 <= hi * cv)) fk(k, "max"); }
}

} // namespace drift

#endif // DRIFT_CPP_HPP
