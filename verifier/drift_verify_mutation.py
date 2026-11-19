#!/usr/bin/env python3
"""Mutation manifest validation and mutation-event kill evaluation."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

from drift_verify_base import DIGEST_RE, ID_RE

THEN_MUT_OPS = frozenset((
    "negate", "add-one", "minus-one", "set-one", "multiply-two", "divide-two",
    "append-tilde", "drop-last", "seed-array", "swap-peer-then", "zero-sum-shear",
    "drop-forbid-key", "pick-forbidden-value", "break-monotonicity", "skew-sum-total",
    "exceed-step-delta", "shift-approx-target", "flip-balance-sign",
))
WHEN_MUT_OPS = frozenset(("swap-case-when", "perturb-case-when"))
MUT_EVENT_KEYS = frozenset(("manifest", "contract", "digest", "mutant", "case", "outcome", "control"))


def validate_mutation_manifest_core(text: str, decode_fn: Callable[[str], Any]) -> dict[str, Any]:
    doc = decode_fn(text)
    if not isinstance(doc, dict) or set(doc) != {"version", "contracts"} or doc.get("version") != 1 or isinstance(doc.get("version"), bool) or not isinstance(cs := doc["contracts"], list) or not cs:
        raise ValueError("manifest")
    by_id, targets, prev_c = {}, {}, ""
    for c in cs:
        if not isinstance(c, dict) or set(c) != {"id", "digest", "mutants"}:
            raise ValueError("contract")
        cid, cdig, muts = c["id"], c["digest"], c["mutants"]
        if not isinstance(cid, str) or not ID_RE.match(cid) or not isinstance(cdig, str) or not DIGEST_RE.match(cdig) or not isinstance(muts, list) or (prev_c and cid <= prev_c):
            raise ValueError("contract")
        prev_c, prev_m, m_list = cid, "", []
        for m in muts:
            if not isinstance(m, dict) or any(k not in ("id", "case", "path", "operator", "before", "after", "witness") for k in m) or any(r not in m for r in ("id", "case", "path", "operator", "before", "after")):
                raise ValueError("mutant")
            mid, mc, mp, mop = m["id"], m["case"], m["path"], m["operator"]
            if not all(isinstance(x, str) for x in (mid, mc, mp, mop)) or not ID_RE.match(mc) or mid != f"{mc}:{mp}" or (prev_m and mid <= prev_m):
                raise ValueError("mutant")
            esc = mc.replace("~", "~0").replace("/", "~1")
            tp, wp = f"/cases/{esc}/then/", f"/cases/{esc}/when/"
            if not ((mp.startswith(tp) and len(mp) > len(tp) and mop in THEN_MUT_OPS) or (mp.startswith(wp) and len(mp) > len(wp) and mop in WHEN_MUT_OPS)):
                raise ValueError("mutant")
            prev_m = mid
            targets[(cid, mid)] = rec = {"id": mid, "contract": cid, "digest": cdig, "case": mc, "path": mp}
            m_list.append(rec)
        by_id[cid] = {"id": cid, "digest": cdig, "mutants": m_list}
    return {"digest": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(), "contracts": by_id, "targets": targets}


validate_mutation_manifest_impl = validate_mutation_manifest_core


def _count_then_leaves(val: Any) -> int:
    return sum(_count_then_leaves(v) for v in val.values()) if isinstance(val, dict) else 1


def load_mutation_events_impl(paths: list[Path], manifest: dict[str, Any], decode_fn: Callable[[str], Any]) -> tuple[dict[tuple[str, str], dict[str, Any]], list[str]]:
    files = [f for p in paths for f in (sorted(p.glob("*.jsonl")) if p.is_dir() else ([p] if p.is_file() else []))]
    latest, errs, tgts = {}, [], manifest["targets"]
    for mf in files:
        for idx, line in enumerate(mf.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                ev = decode_fn(line)
                if not isinstance(ev, dict) or set(ev) != MUT_EVENT_KEYS or not all(isinstance(v, str) and v.strip() for v in ev.values()):
                    raise ValueError("mut")
                t = tgts.get((ev["contract"], ev["mutant"]))
                if t is None or ev["manifest"] != manifest["digest"] or ev["digest"] != t["digest"] or ev["case"] != t["case"] or ev["outcome"] not in ("killed", "survived", "inconclusive") or ev["control"] not in ("passed", "failed") or (ev["outcome"] in ("killed", "survived") and ev["control"] != "passed"):
                    raise ValueError("mut")
                latest[(ev["contract"], ev["mutant"])] = ev
            except Exception as exc:
                errs.append(f"mutation-events:{mf.name}:{idx}: {exc}")
    return latest, errs


def evaluate_contract_mutations_impl(contract: dict[str, Any], manifest: dict[str, Any] | None, latest_mut: dict[tuple[str, str], dict[str, Any]], mut_errors: list[str], digest_matches_fn: Callable[[str, str], bool]) -> bool:
    if manifest is None or mut_errors or (mc := manifest["contracts"].get(contract["id"])) is None or not digest_matches_fn(mc["digest"], contract["digest"]):
        return False
    tc: dict[str, int] = {}
    for m in mc["mutants"]:
        if "/when/" not in m["path"]:
            tc[m["case"]] = tc.get(m["case"], 0) + 1
        if (ev := latest_mut.get((contract["id"], m["id"]))) is None or ev["outcome"] != "killed":
            return False
    return all(tc.get(cid, 0) >= _count_then_leaves(cm.get("then", {})) for cid, cm in contract["cases"].items() if isinstance(cm, dict) and "status" not in cm)
