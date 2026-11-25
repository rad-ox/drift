#!/usr/bin/env python3
"""Proof event parsing, inventory sidecar reconciliation, and receipt loading for drift_verify.py (MIT License)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from drift_verify_base import (
    DIGEST_RE,
    ID_RE,
    WORD_RE,
    _decode_no_dup_keys,
)
from drift_verify_obs import obs03
from drift_verify_parity import load_parity_receipts_impl
from drift_verify_sec import (
    load_formal_receipts_impl,
    load_migration_receipts_impl,
    load_security_receipts_impl,
)
from drift_verify_sim import load_simulation_receipts_impl
from drift_verify_subject import (
    order_shadow_shards_py,
    shadow_inputs_fresh,
    validate_inventory_text_impl,
)

OUTCOMES = {"passed", "failed", "skipped", "disabled", "interrupted", "timeout"}
EVENT_KEYS = {
    "test",
    "contract",
    "cases",
    "level",
    "outcome",
    "read",
    "digest",
    "schema",
    "capabilities",
    "observations",
}
REQUIRED_EVENT_KEYS = ("test", "contract", "cases", "level", "outcome")


def validate_event_line_impl(line: str) -> dict[str, Any]:
    doc = _decode_no_dup_keys(line)
    if (
        not isinstance(doc, dict)
        or any(k not in EVENT_KEYS for k in doc)
        or any(req not in doc for req in REQUIRED_EVENT_KEYS)
    ):
        raise ValueError("event")

    cases = doc["cases"]
    read_cases = doc.get("read", [])
    digest = doc.get("digest", "")
    schema = doc.get("schema", "")
    capabilities = doc.get("capabilities", [])

    valid = (
        isinstance(doc["test"], str)
        and bool(doc["test"].strip())
        and isinstance(doc["contract"], str)
        and bool(ID_RE.match(doc["contract"]))
        and isinstance(cases, list)
        and bool(cases)
        and len(set(cases)) == len(cases)
        and all(isinstance(c, str) and bool(ID_RE.match(c)) for c in cases)
        and isinstance(doc["level"], str)
        and bool(WORD_RE.match(doc["level"]))
        and doc["outcome"] in OUTCOMES
        and isinstance(read_cases, list)
        and len(set(read_cases)) == len(read_cases)
        and all(isinstance(r, str) and r in cases for r in read_cases)
        and (digest == "" or (isinstance(digest, str) and bool(DIGEST_RE.match(digest))))
        and (schema == "" or schema == "0.3")
        and isinstance(capabilities, list)
        and all(isinstance(cp, str) and bool(cp.strip()) for cp in capabilities)
    )
    if not valid:
        raise ValueError("event")

    return {
        "test": doc["test"],
        "contract": doc["contract"],
        "cases": cases,
        "level": doc["level"],
        "outcome": doc["outcome"],
        "read": read_cases,
        "digest": digest,
        "schema": schema,
        "capabilities": capabilities,
        **obs03(doc, cases, schema),
    }


def canonical_test_id(test: str) -> str:
    raw = test.strip()
    start = raw.find("#") + 1
    for i in range(start, len(raw)):
        if raw[i] in ("(", "["):
            return raw[:i]
    return raw


def _discover_jsonl_shards(events_paths: list[Path]) -> list[Path]:
    shards: list[Path] = []
    for path in events_paths:
        if path.is_dir():
            shards.extend(sorted(path.glob("*.jsonl")))
        elif path.is_file() and path.name.endswith(".jsonl"):
            shards.append(path)
    return shards


def _reconcile_ordered_shards(
    ordered_shards: list[tuple[Any, ...]],
) -> tuple[list[tuple[Any, ...]], dict[str, set[str]]]:
    snap_union: dict[str, tuple[set[str], set[str]]] = {}
    for _, _, has_inv, classes, tests, snap, shadow_run, _ in ordered_shards:
        if has_inv and snap and not shadow_run:
            union_classes, union_tests = snap_union.setdefault(snap, (set(), set()))
            union_classes |= classes
            union_tests |= tests

    effective_shards: list[tuple[Any, ...]] = []
    latest_by_class: dict[str, set[str]] = {}
    for sf, raw, has_inv, classes, tests, snap, shadow_run, sref in ordered_shards:
        if has_inv and snap and not shadow_run and snap in snap_union:
            eff_classes = set(snap_union[snap][0])
            eff_tests = set(snap_union[snap][1])
        else:
            eff_classes = set(classes)
            eff_tests = set(tests)

        selected = set(shadow_run.get("selected_tests") or ()) if isinstance(shadow_run, dict) else set()
        by_class: dict[str, set[str]] = {}
        for test_id in eff_tests:
            if "#" in test_id:
                by_class.setdefault(test_id.split("#", 1)[0], set()).add(test_id)

        for cls in eff_classes:
            cur_tests = by_class.get(cls, set())
            prev_tests = latest_by_class.get(cls)
            if selected and prev_tests:
                preserved = {pt for pt in prev_tests if pt not in selected}
                eff_tests |= preserved
                cur_tests = cur_tests | preserved
            latest_by_class[cls] = cur_tests

        effective_shards.append((sf, raw, has_inv, eff_classes, eff_tests, snap, sref))

    return effective_shards, latest_by_class


def load_proof_events_impl(
    events_paths: list[Path],
    area_root: Path | None = None,
    target_run_id: str = "",
) -> tuple[Any, ...]:
    shards = _discover_jsonl_shards(events_paths)
    events: list[dict[str, Any]] = []
    gone: dict[str, int] = {}
    incomplete_shards = 0
    errors: list[str] = []
    snapshots: set[str] = set()
    shard_subjects: set[str] = set()
    all_have_snapshot = bool(shards)
    shard_hashes: list[str] = []
    parsed_shards: list[tuple[Any, ...]] = []

    for sf in shards:
        raw = sf.read_bytes()
        meta_path = sf.with_suffix(".meta.json")
        shard_hashes.append("sha256:" + hashlib.sha256(raw).hexdigest())

        has_inv = meta_path.is_file()
        classes: set[str] = set()
        tests: set[str] = set()
        snap = ""
        shadow_run: Any = None
        subject_ref = ""
        unevaluated: list[str] = []
        containment: set[str] = set()

        if has_inv:
            try:
                inv = validate_inventory_text_impl(meta_path.read_text("utf-8"), _decode_no_dup_keys)
                classes = set(inv["classes"])
                tests = set(inv["tests"])
                snap = inv["snapshot"]
                shadow_run = inv.get("shadow_run")
                subject_ref = inv.get("subject_ref", "")
                containment = set(inv.get("containment") or ())
                if "touched" in inv:
                    unevaluated.append("touched")
                if inv.get("pack_ref"):
                    unevaluated.append("pack_ref")
            except Exception as exc:
                errors.append(f"{meta_path.name}: {exc}")
                all_have_snapshot = False
                continue
        else:
            all_have_snapshot = False

        if shadow_run and not shadow_inputs_fresh(shadow_run, sf, area_root):
            continue
        parsed_shards.append(
            (sf, raw, has_inv, classes, tests, snap, shadow_run, subject_ref, unevaluated, containment)
        )

    ordered_shards, shard_errs = order_shadow_shards_py([x[:8] for x in parsed_shards], target_run_id)
    unev_by_shard = {x[0]: x[8] for x in parsed_shards}
    cont_by_shard = {x[0]: x[9] for x in parsed_shards}
    errors.extend(shard_errs)

    effective_shards, latest_by_class = _reconcile_ordered_shards(ordered_shards)

    for sf, raw, has_inv, classes, tests, snap, sref in effective_shards:
        if snap:
            snapshots.add(snap)
        else:
            all_have_snapshot = False
        if sref:
            shard_subjects.add(sref)

        line_count = 0
        unev_tokens = unev_by_shard.get(sf, ())
        for idx, raw_line in enumerate(raw.decode("utf-8").split("\n"), 1):
            line = raw_line[:-1] if raw_line.endswith("\r") else raw_line
            if not line.strip():
                continue
            try:
                ev = validate_event_line_impl(line)
            except Exception as exc:
                errors.append(f"events:{sf.name}:{idx}: DR-E701 {exc}")
                continue
            if unev_tokens:
                ev["_unev"] = unev_tokens
            ev["_containment"] = cont_by_shard.get(sf, set())
            line_count += 1

            tid = canonical_test_id(ev["test"])
            cls = tid.split("#", 1)[0] if "#" in tid else ""
            if (
                not has_inv
                or not cls
                or len(tid) <= len(cls) + 1
                or cls not in classes
                or tid not in latest_by_class.get(cls, ())
            ):
                gone[ev["contract"]] = gone.get(ev["contract"], 0) + 1
            else:
                events.append(ev)

        if has_inv and snap and tests and line_count == 0:
            incomplete_shards += 1

    sec_recs, sec_errs = load_security_receipts_impl(events_paths, _decode_no_dup_keys)
    form_recs, form_errs = load_formal_receipts_impl(events_paths, _decode_no_dup_keys)
    par_recs, par_errs = load_parity_receipts_impl(events_paths, _decode_no_dup_keys)
    mig_recs, mig_errs = load_migration_receipts_impl(events_paths, _decode_no_dup_keys)
    _, sim_errs = load_simulation_receipts_impl(events_paths, _decode_no_dup_keys)
    errors.extend(sec_errs + form_errs + par_errs + mig_errs + sim_errs)

    single_snapshot = (
        next(iter(snapshots))
        if all_have_snapshot and incomplete_shards == 0 and events and len(snapshots) == 1
        else ""
    )
    return (
        events,
        gone,
        incomplete_shards,
        errors,
        sec_recs,
        form_recs,
        par_recs,
        mig_recs,
        shard_subjects,
        single_snapshot,
        shard_hashes,
        sorted(snapshots),
        bool(all_have_snapshot and shards),
    )
