#!/usr/bin/env python3
"""Seeded differential JSON fuzzer comparing DRIFT V engine (`drift gate`) vs Python verifier (`drift_verify.py`).

Replays the mandatory regression corpus first, then generates seeded valid and adversarial
proof events (`.jsonl`) and inventory sidecars (`.meta.json`), asserting identical verdicts
and automatically shrinking any divergence to a minimal reproducer.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPTS_DIR.parent
DEFAULT_CORPUS = SCRIPTS_DIR / "json_diff_corpus.jsonl"

sys.path.insert(0, str(SCRIPTS_DIR))
import drift_verify  # noqa: E402


def _setup_fixture_area(base: Path, drift_bin: Path) -> tuple[Path, Path, str]:
    (base / ".drift" / "profiles").mkdir(parents=True)
    (base / ".drift" / "contracts").mkdir(parents=True)
    (base / ".drift" / "profiles" / "p@1.toml").write_text(
        'drift = "0.3"\nprofile = "p@1"\n[schema.when]\nx = { type = "int" }\n[schema.then]\ny = { type = "string" }\n',
        encoding="utf-8",
    )
    cfg = base / ".drift" / "config.toml"
    cfg.write_text(
        'drift = "0.3"\nkind = "config"\n[area]\nowner = "alice"\n[policy]\npack = "core@1"\napprovers = ["alice"]\nproof = "verified"\n',
        encoding="utf-8",
    )
    contract = base / ".drift" / "contracts" / "fz.toml"
    contract.write_text(
        'drift = "0.3"\nid = "fz"\nintent = "Differential JSON parity."\n[use]\nprofile = "p@1"\n'
        '[scope]\nwrites = []\nreads = []\nindirect = "none"\n'
        '[bind]\ncode = ["src/a.py", "src/b.py"]\n'
        '[cases.ok]\nat = ["unit"]\nwhen.x = 1\nthen.y = "ok"\n',
        encoding="utf-8",
    )
    subprocess.run([str(drift_bin), "approve", str(cfg), "--by", "alice"], check=True, capture_output=True)
    subprocess.run([str(drift_bin), "approve", str(contract), "--by", "alice"], check=True, capture_output=True)
    chk = json.loads(subprocess.check_output([str(drift_bin), "check", str(contract), "--json"], text=True))
    return base / ".drift" / "contracts", cfg, chk["files"][0]["digest"]


def _valid_event_line(dig: str) -> str:
    return json.dumps({
        "test": "T#ok",
        "contract": "fz",
        "cases": ["ok"],
        "read": ["ok"],
        "level": "unit",
        "outcome": "passed",
        "digest": dig,
        "schema": "0.3",
        "capabilities": [],
    }, separators=(",", ":"))


def _valid_meta_line() -> str:
    return json.dumps({"version": 1, "classes": ["T"], "tests": ["T#ok"]}, separators=(",", ":"))


def _eval_pair(
    drift_bin: Path,
    contracts_dir: Path,
    cfg_path: Path,
    dig: str,
    kind: str,
    payload: str,
    work_dir: Path,
) -> dict[str, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    ev_p = work_dir / "s.jsonl"
    meta_p = work_dir / "s.meta.json"
    if kind == "event":
        ev_p.write_text(payload + "\n", encoding="utf-8")
        meta_p.write_text(_valid_meta_line() + "\n", encoding="utf-8")
    else:
        ev_p.write_text(_valid_event_line(dig) + "\n", encoding="utf-8")
        meta_p.write_text(payload + "\n", encoding="utf-8")

    g_env = {**__import__("os").environ, "DRIFT_EDITION": "free"}
    g_res = subprocess.run(
        [str(drift_bin), "gate", str(contracts_dir), "--config", str(cfg_path), "--events", str(work_dir), "--json"],
        capture_output=True,
        text=True,
        env=g_env,
        check=False,
    )
    v_res = subprocess.run(
        [sys.executable, "-B", str(SCRIPTS_DIR / "drift_verify.py"), str(contracts_dir), "--config", str(cfg_path), "--events", str(work_dir), "--json"],
        capture_output=True,
        text=True,
        check=False,
    )

    def _summarize(res: subprocess.CompletedProcess[str], label: str) -> tuple[Any, list[str], str | None]:
        if res.returncode == 2 and not res.stdout.strip():
            return ("input_error", True, 0, []), ["input.invalid"], None
        if res.returncode not in (0, 1) or not res.stdout.strip():
            return None, [], f"{label} crashed rc={res.returncode}: {res.stderr.strip()}"
        try:
            doc = json.loads(res.stdout)["contracts"][0]
        except Exception as exc:
            return None, [], f"{label} non-JSON stdout ({exc}): {res.stdout[:200]}"
        sig = (
            doc["ok"],
            "events.invalid" in doc["reasons"],
            doc.get("gone", 0),
            [(r["case"], r["level"], r["state"]) for r in doc.get("results", [])],
        )
        return sig, doc["reasons"], None

    g_sig, g_reasons, g_err = _summarize(g_res, "drift gate")
    v_sig, v_reasons, v_err = _summarize(v_res, "drift_verify.py")
    if g_err or v_err:
        return {"match": False, "error": g_err or v_err, "v_engine": g_sig, "py_verifier": v_sig}
    # Invalid .meta.json sidecars fail closed with rc=2 (CLI) and events.invalid rc=1 (Python verifier).
    meta_both_rejected = (
        kind == "meta"
        and g_sig[0] == "input_error"
        and g_sig[1] is True
        and v_sig[0] is False
        and v_sig[1] is True
    )
    return {
        "match": (g_sig == v_sig) or meta_both_rejected,
        "v_engine": g_sig,
        "py_verifier": v_sig,
        "g_reasons": g_reasons,
        "v_reasons": v_reasons,
    }


def _rand_tricky_string(rng: random.Random) -> str:
    alphabet = ['"', '\\', '[', ']', '{', '}', 'a', '1', '\t', 'é', '😀']
    n = rng.randint(1, 80)
    return "".join(rng.choice(alphabet) for _ in range(n))


def _nested_list(depth: int) -> Any:
    val: Any = 1
    for _ in range(depth):
        val = [val]
    return val


def generate_seeded_cases(seed: int, count: int, dig: str) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    cases: list[dict[str, Any]] = []
    for i in range(count):
        mode = i % 10
        if mode == 0:
            # Valid event with tricky escaped quotes & brackets inside observation string
            s = _rand_tricky_string(rng) + '"' + "[" * rng.randint(60, 75) + "}" * rng.randint(0, 10)
            ev = {
                "test": "T#ok", "contract": "fz", "cases": ["ok"], "read": ["ok"],
                "level": "unit", "outcome": "passed", "digest": dig, "schema": "0.3", "capabilities": [],
                "observations": {"ok": {"schema": "drift.observation/1", "payload": {"y": "ok", "s": s}}},
            }
            payload = json.dumps(ev, separators=(",", ":"))
            if rng.random() < 0.5:
                payload = payload.replace('\\"', "\\u0022")
            cases.append({"name": f"seed{seed}-esc-obs-{i}", "kind": "event", "payload": payload})
        elif mode == 1:
            # Escaped quote followed by deep nesting around the 64 boundary
            # Total depth = 1 (root) + d; d=63 -> depth 64 (valid JSON), d=64..70 -> depth 65..71 (invalid)
            d = rng.choice([62, 63, 64, 65, 70])
            prefix = rng.choice(['\\"', '\\\\', '\\\\\\"', '\\"x\\"'])
            payload = '{"a":"' + prefix + '","b":' + "[" * d + "1" + "]" * d + "}"
            cases.append({"name": f"seed{seed}-depth-esc-{d}-{i}", "kind": "event", "payload": payload})
        elif mode == 2:
            # Observation container nesting right around the 64-container boundary (root -> obs -> ok -> payload -> nested = 4 levels)
            inner = rng.choice([59, 60, 61, 62])
            ev = {
                "test": "T#ok", "contract": "fz", "cases": ["ok"], "read": ["ok"],
                "level": "unit", "outcome": "passed", "digest": dig, "schema": "0.3", "capabilities": [],
                "observations": {"ok": {"schema": "drift.observation/1", "payload": {"y": "ok", "n": _nested_list(inner)}}},
            }
            cases.append({"name": f"seed{seed}-obs-depth-{inner}-{i}", "kind": "event", "payload": json.dumps(ev, separators=(",", ":"))})
        elif mode == 3:
            # Duplicate keys after escaped strings
            val = json.dumps(_rand_tricky_string(rng))
            payload = f'{{"test":"T#ok","contract":"fz","cases":["ok"],"read":["ok"],"level":"unit","outcome":"passed","digest":"{dig}","schema":"0.3","capabilities":[],"k":{val},"k":1}}'
            cases.append({"name": f"seed{seed}-dup-key-{i}", "kind": "event", "payload": payload})
        elif mode == 4:
            # Malformed / truncated / trailing garbage event
            base = _valid_event_line(dig)
            cut = rng.randint(1, len(base) - 1)
            payload = rng.choice([base[:cut], base + "}", base + " null", "[]", "42", '{"test":NaN}'])
            cases.append({"name": f"seed{seed}-malformed-ev-{i}", "kind": "event", "payload": payload})
        elif mode == 5:
            # Valid meta with tricky escaped inputs and touched paths
            meta = {
                "version": 1,
                "classes": ["T"],
                "tests": ["T#ok"],
                "touched": ["src/a.py", "src/b.py"],
                "inputs": {"T#ok": {"src/a.py": _rand_tricky_string(rng) + '"' + "{" * 68}},
            }
            cases.append({"name": f"seed{seed}-meta-esc-{i}", "kind": "meta", "payload": json.dumps(meta, separators=(",", ":"))})
        elif mode == 6:
            # Adversarial meta sidecar (path traversal, bad version, unsorted, unknown key)
            bad_metas = [
                '{"version":1,"classes":["T"],"tests":["T#ok"],"touched":["/abs/path"]}',
                '{"version":1,"classes":["T"],"tests":["T#ok"],"touched":["a/../b"]}',
                '{"version":true,"classes":["T"],"tests":["T#ok"]}',
                '{"version":1,"classes":["T"],"tests":["Other#ok"]}',
                '{"version":1,"classes":["T"],"tests":["T#ok"],"extra":1}',
                '{"version":1,"classes":["T"],"tests":["T#ok"],"a":"\\"","b":' + "[" * 65 + "1" + "]" * 65 + "}",
            ]
            cases.append({"name": f"seed{seed}-meta-bad-{i}", "kind": "meta", "payload": rng.choice(bad_metas)})
        elif mode == 7:
            # Unknown event property / bad read / bad outcome / bad digest
            bad_evs = [
                {"test": "T#ok", "contract": "fz", "cases": ["ok"], "read": ["other"], "level": "unit", "outcome": "passed", "digest": dig, "schema": "0.3", "capabilities": []},
                {"test": "T#ok", "contract": "fz", "cases": ["ok"], "read": ["ok"], "level": "unit", "outcome": "bogus", "digest": dig, "schema": "0.3", "capabilities": []},
                {"test": "T#ok", "contract": "fz", "cases": ["ok"], "read": ["ok"], "level": "unit", "outcome": "passed", "digest": "dr2b:BAD", "schema": "0.3", "capabilities": []},
                {"test": "T#ok", "contract": "fz", "cases": ["ok"], "read": ["ok"], "level": "unit", "outcome": "passed", "digest": dig, "schema": "0.2", "capabilities": []},
            ]
            cases.append({"name": f"seed{seed}-ev-schema-{i}", "kind": "event", "payload": json.dumps(rng.choice(bad_evs), separators=(",", ":"))})
        elif mode == 8:
            # Unicode keys and escaped quotes in observation payloads
            ev = {
                "test": "T#ok", "contract": "fz", "cases": ["ok"], "read": ["ok"],
                "level": "unit", "outcome": "passed", "digest": dig, "schema": "0.3", "capabilities": [],
                "observations": {"ok": {"schema": "drift.observation/1", "payload": {"y": "ok", "\ue000": "a\"b", "\U0001f600": "[[" * 35}}},
            }
            cases.append({"name": f"seed{seed}-unicode-{i}", "kind": "event", "payload": json.dumps(ev, ensure_ascii=rng.choice([True, False]), separators=(",", ":"))})
        else:
            # Valid v2 meta sidecar with execution_ref
            meta = {"version": 2, "classes": ["T"], "tests": ["T#ok"], "execution_ref": "sha256:" + "a" * 64, "touched": []}
            cases.append({"name": f"seed{seed}-meta-v2-{i}", "kind": "meta", "payload": json.dumps(meta, separators=(",", ":"))})
    return cases


def shrink_divergence(
    drift_bin: Path,
    contracts_dir: Path,
    cfg_path: Path,
    dig: str,
    kind: str,
    payload: str,
    work_root: Path,
) -> str:
    cur = payload
    step = 0
    while len(cur) > 8 and step < 32:
        improved = False
        for lo, hi in ((len(cur) // 4, len(cur) // 2), (len(cur) // 2, (3 * len(cur)) // 4), (len(cur) - 8, len(cur) - 1)):
            if lo >= hi or lo <= 0:
                continue
            cand = cur[:lo] + cur[hi:]
            step += 1
            res = _eval_pair(drift_bin, contracts_dir, cfg_path, dig, kind, cand, work_root / f"shrink-{step}")
            if not res["match"]:
                cur = cand
                improved = True
                break
        if not improved:
            break
    return cur


def load_corpus(corpus_path: Path, dig: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not corpus_path.is_file():
        return out
    for raw in corpus_path.read_text(encoding="utf-8").splitlines():
        ln = raw.strip()
        if not ln:
            continue
        rec = json.loads(ln)
        rec["payload"] = rec["payload"].replace("__DIG__", dig)
        out.append(rec)
    return out


def run_differential_fuzz(
    drift_bin: Path,
    *,
    corpus_path: Path = DEFAULT_CORPUS,
    seed: int = 20261120,
    cases_count: int = 30,
    workers: int = 4,
    shrink: bool = True,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="drift-json-diff-fuzz-") as td:
        tp = Path(td)
        contracts_dir, cfg_path, dig = _setup_fixture_area(tp / "area", drift_bin)
        corpus_cases = load_corpus(corpus_path, dig)
        seeded_cases = generate_seeded_cases(seed, cases_count, dig)
        all_cases = corpus_cases + seeded_cases

        divergences: list[dict[str, Any]] = []

        def _run_one(idx_case: tuple[int, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
            idx, c = idx_case
            res = _eval_pair(drift_bin, contracts_dir, cfg_path, dig, c["kind"], c["payload"], tp / f"c-{idx}")
            return c, res

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            for c, res in ex.map(_run_one, enumerate(all_cases)):
                if not res["match"]:
                    minimal = (
                        shrink_divergence(drift_bin, contracts_dir, cfg_path, dig, c["kind"], c["payload"], tp / f"sh-{c['name']}")
                        if shrink
                        else c["payload"]
                    )
                    divergences.append({"case": c["name"], "kind": c["kind"], "minimal_payload": minimal, **res})
                elif "expect_invalid" in c:
                    got_inv = res["v_engine"][1]
                    if bool(c["expect_invalid"]) != bool(got_inv):
                        divergences.append({
                            "case": c["name"],
                            "kind": c["kind"],
                            "error": f"corpus expectation mismatch: expected invalid={c['expect_invalid']}, got {got_inv}",
                            **res,
                        })

        return {
            "ok": len(divergences) == 0,
            "seed": seed,
            "corpus_cases": len(corpus_cases),
            "seeded_cases": len(seeded_cases),
            "total_cases": len(all_cases),
            "divergences": divergences,
        }


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="json_diff_fuzz.py")
    default_drift = ROOT_DIR / ".build" / "drift"
    if not default_drift.is_file():
        on_path = __import__("shutil").which("drift")
        if on_path:
            default_drift = Path(on_path)
    p.add_argument("--drift", type=Path, default=default_drift)
    p.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    p.add_argument("--seed", type=int, default=20261120)
    p.add_argument("--cases", type=int, default=40)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--no-shrink", action="store_true")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if not a.drift.is_file():
        print(f"json_diff_fuzz: missing drift binary at {a.drift}", file=sys.stderr)
        return 2
    rep = run_differential_fuzz(a.drift, corpus_path=a.corpus, seed=a.seed, cases_count=a.cases, workers=a.workers, shrink=not a.no_shrink)
    if a.json:
        print(json.dumps(rep, indent=2, sort_keys=True))
    else:
        print(f"json_diff_fuzz: {'ok' if rep['ok'] else 'FAIL'} ({rep['corpus_cases']} corpus + {rep['seeded_cases']} seeded cases, seed={rep['seed']}, divergences={len(rep['divergences'])})")
        for d in rep["divergences"]:
            print(f"  DIVERGENCE {d['case']}: {d}", file=sys.stderr)
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
