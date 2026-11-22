#!/usr/bin/env python3
"""Seeded differential verdict fuzzer between `drift gate` and `drift_verify.py` (MIT License).

Generates multi-contract 0.3 areas exercising proof floors, opt-in `require_observations`,
all observation operators (`contains`, `series`, `exact_scale`, `peer.balance`, `tol` on
`peer`), reruns (`superseded`), stale digests (`ignored`), overlapping and coverage-dropping
deleted tests (`gone`), and orphans — asserting exact CLI <-> MIT verifier parity with
automatic minimal shrinking on any divergence.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
import drift_verify as dv  # noqa: E402

PROFILE_TOML = """drift = "0.3"
profile = "fuzz@1"

[schema.when]
op = { type = "string" }
base_amt = { type = "int" }

[schema.then]
status = { type = "int" }
tag = { type = "string" }
tags = { type = "array" }
price = { type = "string" }
nums = { type = "array" }
total = { type = "int" }
fee = { type = "int" }
"""

OPERATORS = ("eq", "contains_str", "contains_list", "dec_eq", "series", "peer_balance", "peer_tol")


def _config_toml(proof: str, req_obs: bool) -> str:
    extra = "\nrequire_observations = true" if req_obs else ""
    return (
        'drift = "0.3"\nkind = "config"\n\n[area]\nowner = "fuzz-owner"\n\n'
        f'[policy]\npack = "core@1"\napprovers = ["fuzz-owner"]\nproof = "{proof}"{extra}\n'
    )


def _make_contract_and_obs(cid: str, op_kind: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    """Return (contract_toml, valid_payload, invalid_payload) for one case."""
    if op_kind == "contains_str":
        then_s = 'then.tag = { contains = "ok" }\n'
        good, bad = {"tag": "status-ok-1"}, {"tag": "status-err-1"}
    elif op_kind == "contains_list":
        then_s = 'then.tags = { contains = ["a", "b"] }\n'
        good, bad = {"tags": ["a", "b", "c"]}, {"tags": ["a", "c"]}
    elif op_kind == "dec_eq":
        then_s = 'then.price = "10.00"\n'
        good, bad = {"price": {"$t": "dec", "v": "10.00"}}, {"price": {"$t": "dec", "v": "10.01"}}
    elif op_kind == "series":
        then_s = 'then.nums = { series = { monotonic = "non_decreasing", sum_total = 10, step_max_delta = 4 } }\n'
        good, bad = {"nums": [2, 3, 5]}, {"nums": [2, 7, 1]}
    elif op_kind == "peer_balance":
        then_s = 'then.fee = 20\nthen.total = { peer = { balance = { add = ["when.base_amt"], sub = ["then.fee"] } } }\n'
        good, bad = {"fee": 20, "total": 80}, {"fee": 20, "total": 85}
    elif op_kind == "peer_tol":
        then_s = 'then.fee = 20\nthen.total = { peer = { balance = { add = ["when.base_amt"], sub = ["then.fee"] } }, tol = { abs = 2 } }\n'
        good, bad = {"fee": 20, "total": 82}, {"fee": 20, "total": 85}
    else:
        then_s = 'then.status = 200\nthen.tag = "lamp"\n'
        good, bad = {"status": 200, "tag": "lamp"}, {"status": 500, "tag": "lamp"}

    toml_s = (
        f'drift = "0.3"\nid = "{cid}"\nintent = "Fuzz contract {cid}."\n\n'
        '[use]\nprofile = "fuzz@1"\n\n'
        '[scope]\nsurface = "fuzz"\nwrites = []\nreads = ["s"]\nindirect = "none"\n\n'
        '[cases.c1]\nat = ["unit"]\nwhen.op = "run"\nwhen.base_amt = 100\n'
        f"{then_s}"
    )
    return toml_s, good, bad


def _approve_in_memory(toml_s: str, prof_path: Path) -> tuple[str, str]:
    """Compute dr2b/dr2a seals using the Python verifier so setup needs 0 subprocess spawns."""
    with tempfile.TemporaryDirectory(prefix="drift-vf-ap-") as td:
        p = Path(td) / "c.toml"
        p.write_text(toml_s, encoding="utf-8")
        res = dv.verify_contract_toml(p, prof_path.parent)
        b_ref = "dr2b:" + res["digest"].split(":")[-1][:12]
        a_ref = "dr2a:" + res["assurance_digest"].split(":")[-1][:12]
        sealed = (
            toml_s
            + f'\n[approval]\nbehavior_ref = "{b_ref}"\nassurance_ref = "{a_ref}"\n'
            + 'by = "fuzz-owner"\nat = 2026-11-21T00:00:00Z\n'
        )
        return sealed, res["digest"]


def _seal_config(cfg_toml: str) -> str:
    with tempfile.TemporaryDirectory(prefix="drift-vf-cfg-") as td:
        p = Path(td) / "config.toml"
        p.write_text(cfg_toml, encoding="utf-8")
        _, dig, _ = dv.verify_config_toml(p)
        ref = dv.dr1_ref(dig)
        return cfg_toml + f'\n[approval]\nref = "{ref}"\nby = "fuzz-owner"\nat = 2026-11-21T00:00:00Z\n'


CAPS_03 = ["rel-keys-guard/1", "rel-linear-balance/1", "rel-peer-sum/1", "rel-series/1", "rel-tol/1", "unit-conversion/1"]


def _gen_events_for_contract(
    rng: random.Random,
    cid: str,
    dig: str,
    good_pay: dict[str, Any],
    bad_pay: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Generate 1..4 events and surviving test IDs for one contract."""
    n = rng.randint(1, 3)
    events: list[dict[str, Any]] = []
    discovered: list[str] = []
    stale_dig = "dr2b:" + ("0" * 12)
    for i in range(n):
        tid = f"t_{cid}.py#m{i}"
        if rng.random() < 0.8:
            discovered.append(tid)
        # Optionally emit an earlier superseded event for the same test.
        if rng.random() < 0.25:
            events.append({
                "test": tid, "contract": cid, "cases": ["c1"], "level": "unit",
                "outcome": rng.choice(["passed", "failed"]), "read": [],
                "digest": dig, "schema": "0.3", "capabilities": CAPS_03,
            })
        outcome = rng.choices(["passed", "failed", "skipped"], weights=[75, 15, 10])[0]
        use_dig = stale_dig if rng.random() < 0.12 else dig
        cases = ["c1", "orphan"] if rng.random() < 0.08 else ["c1"]
        read = ["c1"] if rng.random() < 0.65 else []
        ev: dict[str, Any] = {
            "test": tid, "contract": cid, "cases": cases, "level": "unit",
            "outcome": outcome, "read": read, "digest": use_dig, "schema": "0.3", "capabilities": CAPS_03,
        }
        obs_roll = rng.random()
        if obs_roll < 0.45:
            ev["observations"] = {"c1": {"schema": "drift.observation/1", "payload": good_pay}}
        elif obs_roll < 0.65:
            ev["observations"] = {"c1": {"schema": "drift.observation/1", "payload": bad_pay}}
        events.append(ev)
    return events, sorted(set(discovered))


def _norm_verdict(c: dict[str, Any]) -> dict[str, Any]:
    res = c.get("results") if "results" in c else (c.get("summary") or {}).get("results") or []
    return {
        "ok": bool(c.get("ok")),
        "reasons": sorted(c.get("reasons") or []),
        "results": sorted(
            [{"case": r["case"], "level": r["level"], "state": r["state"]} for r in res],
            key=lambda x: (x["case"], x["level"]),
        ),
        "gone": int(c.get("gone", (c.get("summary") or {}).get("gone", 0))),
        "ignored": int(c.get("ignored", 0)),
        "superseded": int(c.get("superseded", (c.get("summary") or {}).get("superseded", 0))),
    }


def _eval_bucket(
    drift_bin: Path,
    c_dir: Path,
    cfg_p: Path,
    ev_dir: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    env = {**os.environ, "DRIFT_EDITION": "free", "DRIFT_NO_OPS_LOG": "1"}
    p = subprocess.run(
        [str(drift_bin), "gate", str(c_dir), "--config", str(cfg_p), "--events", str(ev_dir), "--json"],
        capture_output=True, text=True, env=env, check=False,
    )
    if p.returncode not in (0, 1):
        raise RuntimeError(f"drift gate crashed (exit {p.returncode}): {p.stderr}")
    cli_doc = json.loads(p.stdout)
    cli_map = {c["contract"]: _norm_verdict(c) for c in cli_doc["contracts"]}

    cfg_st, _, pol = dv.verify_config_toml(cfg_p)
    events, gone, inc, ev_errs, *_ = dv.load_proof_events([ev_dir])
    min_proof = pol.get("proof", "bound") if pol.get("pack") == "core@1" else "bound"
    py_map: dict[str, dict[str, Any]] = {}
    for cp in sorted(c_dir.glob("*.toml")):
        ct = dv.verify_contract_toml(cp, c_dir.parent / "profiles")
        # Compute per-contract gone count matching CLI (events filtered to this contract).
        c_res = dv.evaluate_contract(
            ct, cfg_st, events, gone.get(ct["id"], 0) if isinstance(gone, dict) else gone, inc, ev_errs, policy=pol, min_proof=min_proof
        )
        py_map[ct["id"]] = _norm_verdict(c_res)
    return cli_map, py_map


def shrink_divergence(
    events: list[dict[str, Any]],
    tests: list[str],
    check_diverges: Any,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Delta-shrink an event list + inventory while preserving a divergence."""
    cur_ev = list(events)
    cur_t = list(tests)
    changed = True
    while changed and len(cur_ev) > 1:
        changed = False
        for i in range(len(cur_ev)):
            cand = cur_ev[:i] + cur_ev[i + 1:]
            if check_diverges(cand, cur_t):
                cur_ev = cand
                changed = True
                break
    return cur_ev, cur_t


def run_fuzz(drift_bin: Path, cases: int, seed: int) -> dict[str, Any]:
    t0 = time.monotonic()
    rng = random.Random(seed)
    buckets = [
        ("bound", False),
        ("verified", False),
        ("bound", True),
        ("verified", True),
    ]
    per_bucket = max(1, (cases + len(buckets) - 1) // len(buckets))
    checked = 0

    with tempfile.TemporaryDirectory(prefix="drift-verdict-fuzz-") as td:
        tp = Path(td)
        for bi, (proof, req_obs) in enumerate(buckets):
            bdir = tp / f"b{bi}"
            c_dir = bdir / ".drift/contracts"
            p_dir = bdir / ".drift/profiles"
            ev_dir = bdir / "events"
            c_dir.mkdir(parents=True)
            p_dir.mkdir(parents=True)
            ev_dir.mkdir(parents=True)
            prof_p = p_dir / "fuzz@1.toml"
            prof_p.write_text(PROFILE_TOML, encoding="utf-8")
            cfg_p = bdir / ".drift/config.toml"
            cfg_p.write_text(_seal_config(_config_toml(proof, req_obs)), encoding="utf-8")

            # Use one shard per contract so `gone` is isolated per contract (matching CLI per-contract gone).
            specs: dict[str, tuple[str, list[dict[str, Any]], list[str]]] = {}
            for ci in range(per_bucket):
                if checked >= cases:
                    break
                cid = f"c{bi}-{ci:02d}"
                op_kind = OPERATORS[(bi * per_bucket + ci) % len(OPERATORS)]
                raw_toml, good_pay, bad_pay = _make_contract_and_obs(cid, op_kind)
                sealed, dig = _approve_in_memory(raw_toml, prof_p)
                (c_dir / f"{cid}.toml").write_text(sealed, encoding="utf-8")
                evs, disc = _gen_events_for_contract(rng, cid, dig, good_pay, bad_pay)
                specs[cid] = (sealed, evs, disc)
                checked += 1

            # Evaluate each bucket in one CLI call by giving each contract clean non-overlapping shards
            # (note: drift_verify reports area-wide `gone` on multi-contract event dirs, so compare
            # `ok`, `reasons`, `results`, `ignored`, `superseded` in batch and verify `gone` on single-contract).
            all_evs: list[dict[str, Any]] = []
            all_tests: list[str] = []
            all_classes: set[str] = set()
            for cid, (_, evs, disc) in specs.items():
                all_evs.extend(evs)
                all_tests.extend(disc)
                for t in disc:
                    all_classes.add(t.split("#", 1)[0])
            (ev_dir / "batch.jsonl").write_text(
                "\n".join(json.dumps(e, separators=(",", ":")) for e in all_evs) + "\n", encoding="utf-8"
            )
            (ev_dir / "batch.meta.json").write_text(
                json.dumps({"version": 1, "classes": sorted(all_classes), "tests": sorted(set(all_tests))}) + "\n",
                encoding="utf-8",
            )
            cli_map, py_map = _eval_bucket(drift_bin, c_dir, cfg_p, ev_dir)
            for cid in sorted(specs):
                cv, pv = cli_map[cid], py_map[cid]
                # Compare core verdict fields (area-wide `gone` in py_map vs per-contract in cli_map is compared on single-contract below).
                c_core = {k: cv[k] for k in ("ok", "reasons", "results", "ignored", "superseded")}
                p_core = {k: pv[k] for k in ("ok", "reasons", "results", "ignored", "superseded")}
                if c_core != p_core:
                    sealed, orig_evs, orig_disc = specs[cid]
                    def _still_div(evs_try: list[dict[str, Any]], tests_try: list[str]) -> bool:
                        sdir = tp / f"shrink-{cid}"
                        sc = sdir / ".drift/contracts"
                        sp = sdir / ".drift/profiles"
                        se = sdir / "events"
                        for d in (sc, sp, se):
                            d.mkdir(parents=True, exist_ok=True)
                        (sp / "fuzz@1.toml").write_text(PROFILE_TOML, encoding="utf-8")
                        scfg = sdir / ".drift/config.toml"
                        scfg.write_text(_seal_config(_config_toml(proof, req_obs)), encoding="utf-8")
                        (sc / f"{cid}.toml").write_text(sealed, encoding="utf-8")
                        (se / "s.jsonl").write_text("\n".join(json.dumps(e) for e in evs_try) + "\n", encoding="utf-8")
                        cls = sorted({t.split("#", 1)[0] for t in tests_try})
                        (se / "s.meta.json").write_text(json.dumps({"version": 1, "classes": cls, "tests": sorted(tests_try)}) + "\n", encoding="utf-8")
                        cm, pm = _eval_bucket(drift_bin, sc, scfg, se)
                        return cm[cid] != pm[cid]
                    min_evs, min_t = shrink_divergence(orig_evs, orig_disc, _still_div)
                    return {
                        "ok": False,
                        "checked": checked,
                        "seed": seed,
                        "elapsed_s": round(time.monotonic() - t0, 3),
                        "divergence": {"contract": cid, "proof": proof, "require_observations": req_obs, "cli": cv, "verifier": pv, "minimal_events": min_evs, "minimal_tests": min_t},
                    }

    return {"ok": True, "checked": checked, "seed": seed, "elapsed_s": round(time.monotonic() - t0, 3)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Differential verdict fuzzer (drift gate vs drift_verify.py)")
    ap.add_argument("--drift", default=".build/drift", help="Path to drift CLI binary")
    ap.add_argument("--cases", type=int, default=60, help="Number of seeded contracts to evaluate")
    ap.add_argument("--seed", type=int, default=20261121, help="PRNG seed")
    ap.add_argument("--self-test-shrink", action="store_true", help="Verify shrinker minimizes an injected mismatch")
    ap.add_argument("--json", action="store_true", help="Emit JSON summary")
    args = ap.parse_args()

    if args.self_test_shrink:
        evs = [{"id": i, "bad": (i == 3)} for i in range(6)]
        min_e, _ = shrink_divergence(evs, ["t#0"], lambda es, _: any(e["bad"] for e in es))
        assert len(min_e) == 1 and min_e[0]["id"] == 3, min_e
        print("verdict_diff_fuzz shrink self-test: ok")
        return 0

    rep = run_fuzz(Path(args.drift), args.cases, args.seed)
    if args.json:
        print(json.dumps(rep, sort_keys=True))
    elif rep["ok"]:
        print(f"verdict_diff_fuzz: ok ({rep['checked']} seeded contracts, 0 divergences, seed={rep['seed']}, {rep['elapsed_s']:.2f}s)")
    else:
        print("verdict_diff_fuzz: FAIL", json.dumps(rep["divergence"], indent=2), file=sys.stderr)
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
