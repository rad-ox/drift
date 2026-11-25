#!/usr/bin/env python3
"""Level-0 standalone verifier primitives: JCS, digests, strict JSON, paths, and 0.3 scalar/schema helpers."""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from pathlib import Path
from typing import Any

SAFE_INT = (1 << 53) - 1
MAX_MEASUREMENT_BYTES = 4 * 1024 * 1024
ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
WORD_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_WORD03_RE = WORD_RE
_RES03_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
DIGEST_RE = re.compile(r"^(?:dr1|dr2b):(?:sha256:[0-9a-f]{64}|[0-9a-f]{12})$")
SNAPSHOT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
SHA256_REF_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ARTIFACT_REF_RE = re.compile(r"^(?:sha256:[0-9a-f]{64}|(?:dr1|dr2b|dr2a|dr2r|dr2x):(?:sha256:[0-9a-f]{64}|[0-9a-f]{12}))$")
ENV_KEYS = frozenset(("toolchain", "deps", "config", "runner", "drift", "adapter", "policy"))

jcs_string = json.encoder.encode_basestring


def ssh_keygen_executable() -> str:
    return shutil.which("ssh-keygen") or "/usr/bin/ssh-keygen"


def jcs_number(val: Any) -> str:
    if isinstance(val, int) and not isinstance(val, bool):
        if not (-SAFE_INT <= val <= SAFE_INT):
            raise ValueError("int")
        return str(val)
    f = float(val)
    if not math.isfinite(f):
        raise ValueError("nan")
    if f == 0.0:
        return "0"
    neg, f = f < 0.0, abs(f)
    s = repr(f)
    if "e" in s or "E" in s:
        m, e = s.lower().split("e", 1)
        d, n = m.replace(".", "").rstrip("0") or "0", int(e) + 1
    elif "." in s:
        ip, fp = s.split(".", 1)
        d = (ip + fp).lstrip("0").rstrip("0") or "0"
        n = len(ip) if ip != "0" else -(len(fp) - len(fp.lstrip("0")))
    else:
        d, n = s.rstrip("0") or "0", len(s)
    k = len(d)
    if k <= n <= 21:
        b = d + ("0" * (n - k))
    elif 0 < n <= 21:
        b = f"{d[:n]}.{d[n:]}"
    elif -6 < n <= 0:
        b = f"0.{'0' * (-n)}{d}"
    else:
        b = f"{d if k == 1 else f'{d[0]}.{d[1:]}'}e{'+' if n >= 1 else '-'}{abs(n - 1)}"
    return f"-{b}" if neg else b


def canonical_json(obj: Any) -> str:
    if obj is None or isinstance(obj, bool):
        return "null" if obj is None else ("true" if obj else "false")
    if isinstance(obj, (int, float)):
        return jcs_number(obj)
    if isinstance(obj, str):
        return jcs_string(obj)
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(canonical_json(x) for x in obj) + "]"
    if isinstance(obj, dict):
        if all(isinstance(k, str) and k.isascii() for k in obj):
            return "{" + ",".join(f"{jcs_string(k)}:{canonical_json(v)}" for k, v in sorted(obj.items())) + "}"
        return "{" + ",".join(f"{jcs_string(str(k))}:{canonical_json(v)}" for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]).encode("utf-16-be"))) + "}"
    raise TypeError(type(obj).__name__)


def dr1_digest(obj: Any) -> str:
    return "dr1:sha256:" + hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def dr1_ref(d: str) -> str:
    if d.startswith("dr1:sha256:"):
        return "dr1:" + d[11:23]
    for p in ("dr2b:sha256:", "dr2a:sha256:", "dr2r:sha256:", "dr2x:sha256:", "dr2g:sha256:", "dr2o:sha256:", "dr2p:sha256:"):
        if d.startswith(p):
            return p[:5] + d[len(p) : len(p) + 12]
    return ""


def digest_matches(ed: str, fd: str) -> bool:
    return bool(fd) and (ed == fd or ed == dr1_ref(fd))


def _proof_rank(floor: str) -> int:
    return {"killed": 3, "verified": 2, "bound": 1}.get(floor, 0)


def _decode_no_dup_keys(text: str) -> Any:
    d, ins, esc = 0, False, False
    for ch in text:
        if ins:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                ins = False
        elif ch == '"':
            ins = True
        elif ch in "{[":
            d += 1
            if d > 64:
                raise ValueError("depth")
        elif ch in "}]":
            d = max(0, d - 1)

    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in pairs:
            if k in out:
                raise ValueError(k)
            out[k] = v
        return out

    return json.loads(text, object_pairs_hook=hook)


def collect_receipt_files(events_paths: list[Path], suffix: str) -> list[Path]:
    out: list[Path] = []
    seen: set[Path] = set()
    for p in events_paths:
        if p:
            for f in (sorted(p.glob(f"*{suffix}")) if p.is_dir() else ([p] if p.is_file() and p.name.endswith(suffix) else [])):
                if f not in seen:
                    seen.add(f)
                    out.append(f)
    return out


def _read_confined_file(bundle_dir: Path, real_root: Path, rel_path: str) -> tuple[str, str, str]:
    if not rel_path or rel_path.startswith("/") or "\\" in rel_path or ":" in rel_path or "\x00" in rel_path:
        raise ValueError("path")
    segs = rel_path.split("/")
    if any(s in ("", ".", "..") for s in segs):
        raise ValueError("path")
    cur = bundle_dir
    for s in segs:
        cur = cur / s
        if cur.is_symlink():
            raise ValueError("symlink")
    if not cur.is_file():
        raise ValueError("missing")
    resolved = cur.resolve()
    if real_root not in resolved.parents:
        raise ValueError("escape")
    raw_bytes = resolved.read_bytes()
    if len(raw_bytes) > MAX_MEASUREMENT_BYTES:
        raise ValueError("size")
    text, h = raw_bytes.decode("utf-8"), hashlib.sha256(raw_bytes).hexdigest()
    return text, f"sha256:{h}", f"dr1:sha256:{h}"


def valid_verify_time_py(ts: str) -> str:
    raw = ts.strip()
    if not raw.endswith(("Z", "z")):
        return ""
    clean = raw[:-1]
    if len(clean) != 14 or not clean.isdigit():
        return ""
    yr, mo, dy, hr, mi, sc = int(clean[:4]), int(clean[4:6]), int(clean[6:8]), int(clean[8:10]), int(clean[10:12]), int(clean[12:14])
    mdays = 29 if mo == 2 and ((yr % 4 == 0 and yr % 100 != 0) or yr % 400 == 0) else {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30, 7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}.get(mo, 0)
    return f"{clean}Z" if yr >= 1970 and 1 <= dy <= mdays and hr <= 23 and mi <= 59 and sc <= 59 else ""


_valid_verify_time = valid_verify_time_py


def _has_temporal_bounds(text: str) -> tuple[bool, bool]:
    has_bounds = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for opt in ('valid-after="', 'valid-before="'):
            if opt in line:
                has_bounds = True
                if not valid_verify_time_py(line.split(opt, 1)[1].split('"', 1)[0]):
                    return True, True
    return has_bounds, False


def _valid_ext_trust_root_py(trust_root: Path | None) -> bool:
    if trust_root is None or trust_root.is_symlink() or not trust_root.is_file():
        return False
    norm, real_p = trust_root.as_posix(), trust_root.resolve().as_posix()
    return not (trust_root.name == "config.toml" or norm.startswith(".drift/") or "/.drift/" in norm or trust_root.resolve().name == "config.toml" or "/.drift/" in real_p)


def _req_str(m: dict[str, Any], k: str) -> str:
    v = m.get(k)
    if not isinstance(v, str) or not v.strip() or v.strip() != v:
        raise ValueError(k)
    return v


def _valid_rel_scope(raw: Any) -> bool:
    if not isinstance(raw, str) or not raw or raw.strip() != raw or raw.startswith("/") or "\\" in raw or "://" in raw:
        return False
    base = raw.split("#", 1)[0]
    return bool(base) and not any(s in ("", ".", "..") for s in base.split("/"))


def _split_scope_anchor(s: str) -> tuple[str, str]:
    norm = s.replace("\\", "/")
    if "#" in norm:
        base, anchor = norm.split("#", 1)
        return base.rstrip("/"), anchor.strip()
    return norm.rstrip("/"), ""


def _wild_tok(pat: str, txt: str) -> bool:
    if pat in ("*", txt):
        return True
    if "*" not in pat:
        return False
    parts = pat.split("*")
    if not txt.startswith(parts[0]) or not txt.endswith(parts[-1]) or len(parts[0]) > len(txt) - len(parts[-1]):
        return False
    pos, end_lim = len(parts[0]), len(txt) - len(parts[-1])
    for piece in parts[1:-1]:
        if piece:
            idx = txt.find(piece, pos, end_lim)
            if idx < 0:
                return False
            pos = idx + len(piece)
    return True


def _match_segs(pat: list[str], path: list[str]) -> bool:
    pi = si = 0
    st_p = st_s = -1
    while si < len(path):
        if pi < len(pat) and pat[pi] == "**":
            st_p, st_s, pi = pi, si, pi + 1
        elif pi < len(pat) and _wild_tok(pat[pi], path[si]):
            pi += 1
            si += 1
        elif st_p >= 0:
            st_s += 1
            si, pi = st_s, st_p + 1
        else:
            return False
    while pi < len(pat) and pat[pi] == "**":
        pi += 1
    return pi == len(pat)


def _cov_matches(cov_raw: str, sc_raw: str) -> bool:
    cov, cov_anchor = _split_scope_anchor(cov_raw)
    sc, sc_anchor = _split_scope_anchor(sc_raw)
    if not cov or not sc:
        return False
    if cov_anchor:
        return bool(sc_anchor and _wild_tok(cov_anchor, sc_anchor) and (cov == sc or _match_segs(cov.split("/"), sc.split("/"))))
    return True if (cov in (sc, "**", "*") or sc.startswith(cov + "/")) else _match_segs(cov.split("/"), sc.split("/"))


def _is_unanchored_prose_source(raw: str) -> bool:
    s = raw.strip()
    if not s or s.startswith("ADR-") or ";" in s or "://" in s:
        return False
    if " " in s:
        return True
    if ":" in s:
        return False
    b = s.split("@sha256:", 1)[0].replace("\\", "/")
    if not b or b.startswith(("note:", "cite:")) or any(c in b for c in " \t\n\r;"):
        return True
    dot = b.rfind(".")
    if 0 < dot < len(b) - 1 and b[dot + 1 :].isalnum() and any(c.isalpha() for c in b[dot + 1 :]):
        return False
    return not ("/" in b and any("a" <= c <= "z" for c in b))


def _contains_todo(v: Any) -> bool:
    return v == "todo" if isinstance(v, str) else (any(_contains_todo(x) for x in v) if isinstance(v, list) else (any(_contains_todo(x) for x in v.values()) if isinstance(v, dict) else False))


def _has_approval_blocker(raw: dict[str, Any], prof: dict[str, Any]) -> bool:
    if isinstance(sc := raw.get("scope"), dict) and sc.get("indirect") == "unknown":
        return True
    if any(_contains_todo(raw.get(s)) for s in ("use", "scope", "cases", "budgets", "formal", "cutover")):
        return True
    if isinstance(ot := raw.get("open"), dict) and any(isinstance(q, dict) and q.get("blocks", "approval") == "approval" for q in ot.values()):
        return True
    return any(isinstance(d, dict) and d.get("pick", "") == "" and d.get("decide_by", "approval") == "approval" for s in (raw.get("decisions"), prof.get("decisions")) if isinstance(s, dict) for d in s.values())


def tok_str_03(s: str, params: dict[str, Any], allow_lookup: bool = True) -> Any:
    if "$" not in s:
        return s
    if allow_lookup and s.startswith("${") and s.endswith("}") and not s.startswith("$${") and _WORD03_RE.match(s[2:-1]):
        return params.get(s[2:-1], s)
    out, i, n = [], 0, len(s)
    while i < n:
        if s[i : i + 3] == "$${" and (cl := s.find("}", i + 3)) > i + 3 and _WORD03_RE.match(s[i + 3 : cl]):
            out.append("${" + s[i + 3 : cl] + "}")
            i = cl + 1
            continue
        if allow_lookup and s[i : i + 2] == "${" and (cl := s.find("}", i + 2)) > i + 2:
            nm = s[i + 2 : cl]
            if nm in params:
                v = params[nm]
                out.append(("true" if v else "false") if isinstance(v, bool) else str(v))
            i = cl + 1
            continue
        out.append(s[i])
        i += 1
    return "".join(out)


def unesc_lit_03(v: Any) -> Any:
    if isinstance(v, str):
        return tok_str_03(v, {}, False)
    if isinstance(v, list):
        return [unesc_lit_03(x) for x in v]
    return {k: unesc_lit_03(val) for k, val in v.items()} if isinstance(v, dict) else v


def validate_config_ext_py(raw: dict[str, Any], pol: dict[str, Any]) -> bool:
    def _rel_glob(pat: Any) -> bool:
        return isinstance(pat, str) and bool(pat) and pat == pat.strip() and not pat.startswith(("/", "\\")) and "://" not in pat and all(s not in ("", ".", "..") for s in pat.replace("\\", "/").split("/"))
    if pol.get("pack") == "core@1" and "uncovered" in pol:
        unc = pol.get("uncovered")
        if not isinstance(unc, list) or len(set(unc)) != len(unc) or not all(_rel_glob(g) for g in unc):
            return False
    if "runners" in raw:
        runners = raw.get("runners")
        allowed = {"argv", "widen_argv", "cwd", "filter_mode", "compile_scope", "env", "match"}
        if not isinstance(runners, dict) or not runners:
            return False
        for r_id, prof in runners.items():
            if not isinstance(r_id, str) or not r_id.strip() or not isinstance(prof, dict) or any(k not in allowed for k in prof):
                return False
            for ak in ("argv", "widen_argv"):
                if ak == "argv" or ak in prof:
                    av = prof.get(ak)
                    if not isinstance(av, list) or not av or not all(isinstance(x, str) and x.strip() and x == x.strip() for x in av):
                        return False
            if "cwd" in prof:
                cwd = prof["cwd"]
                if not isinstance(cwd, str) or not cwd.strip() or cwd != cwd.strip() or cwd.startswith(("/", "\\")) or (cwd != "." and any(s in ("", ".", "..") for s in cwd.replace("\\", "/").split("/"))):
                    return False
            if "filter_mode" in prof and prof["filter_mode"] not in ("append_after_double_dash", "append", "mvn_dtest", "rust_test_exact", "none"):
                return False
            if "compile_scope" in prof and prof["compile_scope"] not in ("compile_and_run", "runtime_filter_only"):
                return False
            if "env" in prof and (not isinstance(env := prof["env"], dict) or any(not isinstance(k, str) or not k.strip() or k != k.strip() or not isinstance(v, str) for k, v in env.items())):
                return False
            if "match" in prof and (not isinstance(m := prof["match"], list) or not m or len(set(m)) != len(m) or not all(_rel_glob(g) for g in m)):
                return False
    if pol.get("pack") == "core@1" and "autonomy" in pol:
        aut, apprs = pol.get("autonomy"), set(pol.get("approvers") or [])
        if (
            not isinstance(aut, dict)
            or set(aut) - {"max_class", "principals", "max_targets"}
            or aut.get("max_class") not in ("C0", "C1")
            or not isinstance(aut.get("principals"), list)
            or not aut["principals"]
            or len(set(aut["principals"])) != len(aut["principals"])
            or any(not isinstance(x, str) or not x.startswith("agent:") or len(x) <= 6 or x in apprs for x in aut["principals"])
            or isinstance(aut.get("max_targets"), bool)
            or not isinstance(aut.get("max_targets"), int)
            or aut["max_targets"] < 1
        ):
            return False
    return True


def _norm_num_03(v: Any, typ: str) -> Any:
    if isinstance(v, bool):
        return v
    if typ == "num" and isinstance(v, (int, float)):
        return 0.0 if float(v) == 0.0 else float(v)
    if typ == "int" and isinstance(v, (int, float)) and float(v).is_integer():
        return int(v)
    return 0.0 if isinstance(v, float) and v == 0.0 else v


def _canon_ptr_03(s: str) -> str:
    st = 1 if s.startswith("/") else 0
    col = s.find(":/", st)
    return f"{s[st:col]}:{s[col + 1:]}" if col > st and _RES03_RE.match(s[st:col]) else s


BUDGET_METRICS = frozenset((
    "request_latency", "successful_throughput", "process_rss", "frame_time", "cold_start",
    "artifact_bytes", "work_units", "tick_alloc_bytes", "tick_alloc_count",
    "alloc_bytes_total", "alloc_count_total", "frame_hitch_ns", "cpu_time_ns",
))


def _budget_metrics_closure_ok(req_bmetrics: list[str], res_budgets: dict[str, dict[str, Any]], act_cids: set[str]) -> bool:
    if not req_bmetrics:
        return True
    req_set = set(req_bmetrics)
    case_mets: dict[str, set[str]] = {}
    case_refs: dict[str, set[tuple[str, str]]] = {}
    for bm in res_budgets.values():
        if not isinstance(bm, dict):
            continue
        cid = str(bm.get("case", ""))
        if cid not in act_cids:
            continue
        met = str(bm.get("metric", ""))
        case_mets.setdefault(cid, set())
        if met:
            case_mets[cid].add(met)
        if met in req_set:
            wl, ev = str(bm.get("workload_ref", "")), str(bm.get("environment_ref", ""))
            if wl and ev:
                case_refs.setdefault(cid, set()).add((wl, ev))
    return bool(case_mets) and all(req_set <= mets and len(case_refs.get(cid, set())) <= 1 for cid, mets in case_mets.items())


def _canon_pred_03(sp: dict[str, Any]) -> dict[str, Any]:
    typ = str(sp.get("type", ""))
    m: dict[str, Any] = {"type": typ}
    for bk in ("min", "max"):
        if bk in sp:
            m[bk] = int(sp[bk]) if typ == "int" else float(sp[bk])
    if isinstance(sp.get("len"), dict) and (lm := {k: int(sp["len"][k]) for k in ("min", "max") if k in sp["len"]}):
        m["len"] = lm
    for k in ("enum", "unit", "role", "transient", "compensating"):
        if sp.get(k):
            m[k] = sp[k]
    if sp.get("ptr"):
        m["ptr"] = _canon_ptr_03(str(sp["ptr"]))
    return m


def _merge_pred_03(b: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    out = {**b, "type": c.get("type", b.get("type", ""))}
    if "min" in b or "min" in c:
        out["min"] = max(b["min"], c["min"]) if ("min" in b and "min" in c) else c.get("min", b.get("min"))
    if "max" in b or "max" in c:
        out["max"] = min(b["max"], c["max"]) if ("max" in b and "max" in c) else c.get("max", b.get("max"))
    bl, cl = b.get("len") or {}, c.get("len") or {}
    lm = {}
    if "min" in bl or "min" in cl:
        lm["min"] = max(bl["min"], cl["min"]) if ("min" in bl and "min" in cl) else cl.get("min", bl.get("min"))
    if "max" in bl or "max" in cl:
        lm["max"] = min(bl["max"], cl["max"]) if ("max" in bl and "max" in cl) else cl.get("max", bl.get("max"))
    if lm:
        out["len"] = lm
    for k in ("enum", "unit", "role", "transient", "compensating", "ptr"):
        if c.get(k):
            out[k] = c[k]
    return out


def sub_use_text_params(val: Any, use_tbl: Any) -> Any:
    params = {k: str(v) for k, v in use_tbl.items() if k not in ("profile", "waive", "vocabulary", "concepts") and isinstance(v, (str, int, bool))} if isinstance(use_tbl, dict) else {}

    def _sub(x: Any) -> Any:
        if isinstance(x, str):
            for pk, pv in params.items():
                if x == f"${{{pk}}}":
                    return pv
                x = x.replace(f"${{{pk}}}", pv)
            return x
        return [_sub(i) for i in x] if isinstance(x, list) else ({k: _sub(v) for k, v in x.items()} if isinstance(x, dict) else x)

    return _sub(val)


def check_receipt_scope_snap_subj(rec: dict[str, Any], scope_code: list[str], active_cases: set[str], expected_snapshot: str, expected_subject_ref: str, cov_matches_fn: Any, prefix: str, extra_ok: bool = True) -> tuple[str, str] | None:
    eff = rec["outcome"]
    deg = "inconclusive" if eff == "passed" else eff
    if not extra_ok or not scope_code or not all(any(cov_matches_fn(c, sc) for c in rec["covered_scope"]) for sc in scope_code) or not active_cases or not all(c in active_cases for c in rec["cases"]):
        return deg, f"{prefix}.incomplete_scope"
    if expected_snapshot and rec["code_snapshot"] != expected_snapshot:
        return deg, f"{prefix}.snapshot_mismatch"
    if expected_subject_ref and rec["subject_ref"] != expected_subject_ref:
        return deg, f"{prefix}.subject_mismatch"
    return None


def reduce_receipt_groups(by_target: dict[Any, dict[str, dict[str, Any]]], eval_rec_fn: Any, prefix: str) -> tuple[list[str], list[dict[str, Any]]]:
    eval_list, reasons, has_viol, has_inc = [], [], False, False
    c_rsn, v_rsn, i_rsn = f"{prefix}.conflicting_receipts", f"{prefix}.violated", f"{prefix}.inconclusive"
    for tkey in sorted(by_target):
        bucket = by_target[tkey]
        group = [bucket[k] for k in sorted(bucket)]
        has_conflict = len(group) > 1
        grp_evals = [(rec, *eval_rec_fn(rec)) for rec in group]
        grp_viol = any(eff == "violated" for _, eff, _ in grp_evals)
        for rec, eff0, rsn0 in grp_evals:
            eff, rsn = eff0, rsn0
            if has_conflict:
                if grp_viol:
                    eff, rsn = "violated", (rsn0 if (rsn0 and rsn0 != v_rsn) else c_rsn)
                else:
                    eff, rsn = "inconclusive", c_rsn
            item = {**rec, "effective_outcome": eff, "provenance": "measured"}
            if rsn:
                item["reason"] = rsn
            eval_list.append(item)
            if eff == "violated":
                has_viol = True
                if rsn and rsn not in reasons:
                    reasons.append(rsn)
                if has_conflict and c_rsn not in reasons:
                    reasons.append(c_rsn)
            elif eff != "passed":
                has_inc = True
                if rsn and rsn not in reasons:
                    reasons.append(rsn)
    if has_viol and v_rsn not in reasons:
        reasons.append(v_rsn)
    if has_inc and not has_viol and i_rsn not in reasons:
        reasons.append(i_rsn)
    return reasons, eval_list
