#!/usr/bin/env python3
"""Subject manifests, security locks, config/inventory validation, and shadow-area helpers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tomllib
from pathlib import Path
from typing import Any, Callable

from drift_verify_base import (
    ENV_KEYS,
    SHA256_REF_RE,
    SNAPSHOT_RE,
    _decode_no_dup_keys,
    _req_str,
    _valid_rel_scope,
    canonical_json,
    validate_config_ext_py,
)

SEC_CATEGORIES = frozenset(("sast", "fuzz", "policy", "deps"))
SHADOW_RUN_SCHEMA = "drift.shadow-run/1"
SHADOW_RUN_KEYS = frozenset(("schema", "run_id", "source_snapshot", "bindings_ref", "shadow_snapshot", "selected_tests", "shadow_inputs", "sequence", "supersedes"))
_META_KEYS = {"version", "classes", "tests", "snapshot", "pack_ref", "touched", "containment", "self_stubbed", "inputs", "env", "execution_ref", "subject_ref", "shadow_run"}
_PREF_RE = re.compile(r"^dr(?:1|2b):[0-9a-f]{12}$")
_CLS_RE = re.compile(r"^[^# \t\r\n/\\\[\]]+$")
_MTH_RE = re.compile(r"^[^# \t\r\n\[\]]+$")
_SREG: dict[Any, Any] = {}
_SROOT: dict[Any, Any] = {}


def parse_subject_manifest_core(text: str, decode_fn: Any, canon_fn: Any, sec_str_fn: Any, valid_rel_scope_fn: Any, sha256_re: Any) -> dict[str, Any]:
    doc = decode_fn(text)
    if not isinstance(doc, dict) or any(k not in ("schema", "subject_ref", "artifact_ref", "sources", "lockfile_ref", "toolchain", "target", "features", "flags", "harness", "verifier_ref") for k in doc) or doc.get("schema") != "drift.subject-manifest/1":
        raise ValueError("subject_manifest")
    aref, lref, vref = (sec_str_fn(doc, "artifact_ref") if "artifact_ref" in doc else ""), sec_str_fn(doc, "lockfile_ref"), sec_str_fn(doc, "verifier_ref")
    tc, tgt, harn = sec_str_fn(doc, "toolchain"), sec_str_fn(doc, "target"), sec_str_fn(doc, "harness")
    if (aref and not sha256_re.match(aref)) or not sha256_re.match(lref) or not sha256_re.match(vref) or not valid_rel_scope_fn(harn) or "#" not in harn:
        raise ValueError("subject_manifest_fields")
    feats = [sec_str_fn({"x": x}, "x") for x in doc.get("features", [])] if isinstance(doc.get("features", []), list) else None
    flgs = [sec_str_fn({"x": x}, "x") for x in doc.get("flags", [])] if isinstance(doc.get("flags", []), list) else None
    srcs = doc.get("sources")
    if feats is None or flgs is None or not isinstance(srcs, dict) or not srcs or any(not valid_rel_scope_fn(sp) or "#" in sp or not isinstance(sh, str) or not sha256_re.match(sh) for sp, sh in srcs.items()):
        raise ValueError("subject_manifest_sources")
    c_obj = {"features": feats, "flags": flgs, "harness": harn, "lockfile_ref": lref, "schema": "drift.subject-manifest/1", "sources": dict(srcs), "target": tgt, "toolchain": tc, "verifier_ref": vref}
    comp_ref = "sha256:" + hashlib.sha256(canon_fn(c_obj).encode("utf-8")).hexdigest()
    if "subject_ref" in doc and sec_str_fn(doc, "subject_ref") != comp_ref:
        raise ValueError("subject_ref_mismatch")
    return {**c_obj, "subject_ref": comp_ref, **({"artifact_ref": aref} if aref else {})}


def parse_subject_manifest_impl(text: str, decode_fn: Callable[[str], Any], canon_fn: Callable[[Any], str]) -> dict[str, Any]:
    return parse_subject_manifest_core(text, decode_fn, canon_fn, _req_str, _valid_rel_scope, SHA256_REF_RE)


def parse_security_lock_core(text: str, decode_fn: Any, canon_fn: Any, sec_str_fn: Any, sec_cats: Any) -> dict[str, Any]:
    doc = decode_fn(text)
    if not isinstance(doc, dict) or any(k not in ("schema", "lock_ref", "tools") for k in doc) or doc.get("schema") != "drift.security-lock/1" or not isinstance(raw_tools := doc.get("tools"), dict) or not raw_tools:
        raise ValueError("security_lock")
    tools: dict[str, dict[str, str]] = {}
    for tkey, tval in raw_tools.items():
        if not isinstance(tkey, str) or ":" not in tkey or not isinstance(tval, dict) or set(tval) != {"tool_ref", "ruleset_ref"}:
            raise ValueError("security_lock_entry")
        cat, tool = tkey.split(":", 1)
        tref, rref = sec_str_fn(tval, "tool_ref"), sec_str_fn(tval, "ruleset_ref")
        if cat not in sec_cats or not tool.strip() or tool.strip() != tool or not SHA256_REF_RE.match(tref) or not SHA256_REF_RE.match(rref):
            raise ValueError("security_lock_fields")
        tools[tkey] = {"ruleset_ref": rref, "tool_ref": tref}
    comp_ref = "sha256:" + hashlib.sha256(canon_fn({"schema": "drift.security-lock/1", "tools": tools}).encode("utf-8")).hexdigest()
    if "lock_ref" in doc and sec_str_fn(doc, "lock_ref") != comp_ref:
        raise ValueError("lock_ref_mismatch")
    return {"active": True, "lock_ref": comp_ref, "tools": tools}


def parse_security_lock_impl(text: str, decode_fn: Callable[[str], Any], canon_fn: Callable[[Any], str]) -> dict[str, Any]:
    return parse_security_lock_core(text, decode_fn, canon_fn, _req_str, SEC_CATEGORIES)


def resolve_verifier_subject_cli(args: Any, decode_fn: Any, canon_fn: Any, parse_sub_fn: Any, parse_lock_fn: Any) -> tuple[dict[str, Any], Any]:
    sec_lock = parse_lock_fn(args.security_lock.read_text("utf-8"), decode_fn, canon_fn) if getattr(args, "security_lock", None) else {}
    bin_ref, sub_ref, man_srcs, has_man, art_mismatch = "", "", None, False, False
    if args.subject_artifact:
        bin_ref = args.subject_artifact if args.subject_artifact.startswith("sha256:") else ("sha256:" + hashlib.sha256(Path(args.subject_artifact).read_bytes()).hexdigest())
    if args.subject:
        st = args.subject.read_text("utf-8", errors="ignore")
        if st.lstrip().startswith("{") and '"drift.subject-manifest/1"' in st:
            sm = parse_sub_fn(st, decode_fn, canon_fn)
            has_man, sub_ref, man_srcs, man_art = True, sm["subject_ref"], sm["sources"], sm.get("artifact_ref", "")
            if man_art and bin_ref and man_art != bin_ref:
                art_mismatch = True
            if not bin_ref and man_art:
                bin_ref = man_art
        else:
            bin_ref = "sha256:" + hashlib.sha256(args.subject.read_bytes()).hexdigest()
    return {"subject_ref": sub_ref, "artifact_ref": sub_ref or bin_ref, "binary_ref": bin_ref, "has_manifest": has_man, "artifact_mismatch": art_mismatch, "source_tree": args.subject_tree, "run_id": args.run_id, "security_lock": sec_lock}, man_srcs


def verify_tool_pin_cli_core(argv: list[str], parse_lock_fn: Any) -> int:
    ap = argparse.ArgumentParser(prog="drift_verify_sec.py")
    ap.add_argument("--verify-tool", required=True)
    ap.add_argument("--tool-bin", type=Path, required=True)
    ap.add_argument("--security-lock", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        lock = parse_lock_fn(args.security_lock.read_text("utf-8"), _decode_no_dup_keys, canonical_json)
        if not args.tool_bin.is_file():
            raise ValueError("missing_tool_bin")
        actual_ref = "sha256:" + hashlib.sha256(args.tool_bin.read_bytes()).hexdigest()
    except Exception as exc:
        print(json.dumps({"ok": False, "reason": "security.tool_unpinned", "error": str(exc)}, sort_keys=True))
        return 2
    pin = (lock.get("tools") or {}).get(args.verify_tool)
    if not pin or pin.get("tool_ref") != actual_ref:
        print(json.dumps({"ok": False, "reason": "security.tool_unpinned", "tool": args.verify_tool, "actual_ref": actual_ref, "expected_ref": (pin or {}).get("tool_ref", ""), "lock_ref": lock["lock_ref"]}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "tool": args.verify_tool, "tool_ref": actual_ref, "ruleset_ref": pin["ruleset_ref"], "lock_ref": lock["lock_ref"]}, sort_keys=True))
    return 0


def verify_config_toml_impl(path: Path, dr1_digest_fn: Callable[[Any], str], dr1_ref_fn: Callable[[str], str]) -> tuple[str, str, dict[str, Any]]:
    if not path.is_file():
        return "missing", "", {}
    raw = tomllib.loads(path.read_text("utf-8"))
    if raw.get("drift") != "0.3":
        return "invalid", "", {}
    appr = raw.pop("approval", None)
    dig = dr1_digest_fn(raw)
    pol = raw.get("policy") if isinstance(raw.get("policy"), dict) else {}
    if pol.get("pack") == "core@1" and "patch_scope" in pol and pol.get("patch_scope") not in ("optional", "required"):
        return "invalid", "", {}
    if pol.get("pack") == "core@1" and "require_signed_approval" in pol and not isinstance(pol.get("require_signed_approval"), bool):
        return "invalid", "", {}
    if not validate_config_ext_py(raw, pol):
        return "invalid", "", {}
    if not isinstance(appr, dict) or not appr.get("ref"):
        return "absent", dig, pol
    st = "current" if appr["ref"] == dr1_ref_fn(dig) else "stale"
    return st, dig, (pol if st == "current" else {})


def strip_outside_digest_impl(cases: Any, decs: Any, is_prose_fn: Callable[[str], bool]) -> None:
    for cm in (cases or {}).values():
        if isinstance(cm, dict):
            cm.pop("note", None)
    for dm in ((decs or {}).values() if isinstance(decs, dict) else ()):
        if isinstance(dm, dict):
            dm.pop("owner", None)
            dm.pop("note", None)
            if dm.get("evidence") == "observed" and is_prose_fn(str(dm.get("source", ""))):
                dm.pop("source", None)


def validate_shadow_run_dict(sr: Any) -> None:
    if not isinstance(sr, dict) or any(k not in SHADOW_RUN_KEYS for k in sr) or sr.get("schema") != SHADOW_RUN_SCHEMA:
        raise ValueError("shadow_run")
    rid, s_snap, b_ref, sh_snap, s_in = sr.get("run_id", ""), sr.get("source_snapshot", ""), sr.get("bindings_ref", ""), sr.get("shadow_snapshot", ""), sr.get("shadow_inputs")
    if not isinstance(rid, str) or not rid.strip() or rid != rid.strip() or "/" in rid or "\\" in rid or ".." in rid:
        raise ValueError("shadow_run.run_id")
    if not isinstance(s_snap, str) or not SNAPSHOT_RE.match(s_snap) or not isinstance(b_ref, str) or len(b_ref) != 71 or not b_ref.startswith("sha256:") or not isinstance(sh_snap, str) or len(sh_snap) != 71 or not sh_snap.startswith("sha256:"):
        raise ValueError("shadow_run.ref")
    if not isinstance(s_in, dict) or not s_in or any(not isinstance(k, str) or not k.strip() or k.startswith("/") or "\\" in k or any(p in ("", ".", "..") for p in k.split("/")) or not isinstance(v, str) or len(v) != 71 or not v.startswith("sha256:") for k, v in s_in.items()):
        raise ValueError("shadow_run.inputs")
    if "selected_tests" in sr and (not isinstance(st_l := sr["selected_tests"], list) or not all(isinstance(x, str) and "#" in x for x in st_l) or st_l != sorted(set(st_l))):
        raise ValueError("shadow_run.selected_tests")
    if "sequence" in sr and (not isinstance(seq := sr["sequence"], int) or isinstance(seq, bool) or seq < 1):
        raise ValueError("shadow_run.sequence")
    if "supersedes" in sr and (not isinstance(sup_l := sr["supersedes"], list) or not all(isinstance(x, str) and bool(x.strip()) and x == x.strip() and "/" not in x and "\\" not in x and ".." not in x and x != rid for x in sup_l) or sup_l != sorted(set(sup_l))):
        raise ValueError("shadow_run.supersedes")


def validate_inventory_text_impl(text: str, decode_fn: Callable[[str], Any]) -> dict[str, Any]:
    doc = decode_fn(text)
    if not isinstance(doc, dict) or any(k not in _META_KEYS for k in doc) or doc.get("version") not in (1, 2) or isinstance(doc.get("version"), bool):
        raise ValueError("inv")
    ex_ref, s_ref = doc.get("execution_ref", ""), doc.get("subject_ref", "")
    if (doc["version"] == 2 and not SHA256_REF_RE.match(str(ex_ref))) or (doc["version"] == 1 and "execution_ref" in doc) or ("subject_ref" in doc and not SHA256_REF_RE.match(str(s_ref))):
        raise ValueError("ref")
    cls, tsts = doc.get("classes"), doc.get("tests")
    if not isinstance(cls, list) or not all(isinstance(x, str) and _CLS_RE.match(x) for x in cls) or cls != sorted(set(cls)):
        raise ValueError("cls")
    c_set = set(cls)
    if not isinstance(tsts, list) or not all(isinstance(x, str) and "#" in x for x in tsts) or tsts != sorted(set(tsts)) or any((p := t.split("#", 1))[0] not in c_set or not _MTH_RE.match(p[1]) for t in tsts):
        raise ValueError("tst")
    t_set, snap, pref = set(tsts), doc.get("snapshot", ""), doc.get("pack_ref", "")
    if ("snapshot" in doc and (not isinstance(snap, str) or not SNAPSHOT_RE.match(snap))) or ("pack_ref" in doc and (not isinstance(pref, str) or not _PREF_RE.match(pref))) or ("touched" in doc and (not isinstance(tc := doc["touched"], list) or not all(isinstance(x, str) and x.strip() for x in tc) or tc != sorted(set(tc)) or any(tp.startswith("/") or "\\" in tp or any(s in ("", ".", "..") for s in tp.split("/")) for tp in tc))) or ("self_stubbed" in doc and (not isinstance(doc["self_stubbed"], list) or any(not isinstance(x, str) or x not in t_set for x in doc["self_stubbed"]))) or ("inputs" in doc and (not isinstance(ri := doc["inputs"], dict) or any(tid not in t_set or not isinstance(fm, dict) or any(not isinstance(fp, str) or not fp.strip() or not isinstance(ov, str) or not ov.strip() for fp, ov in fm.items()) for tid, fm in ri.items()))) or ("env" in doc and (not isinstance(re_e := doc["env"], dict) or set(re_e) != ENV_KEYS or any(not isinstance(ev, str) or not ev.strip() for ev in re_e.values()))):
        raise ValueError("inv")
    if "shadow_run" in doc:
        validate_shadow_run_dict(doc["shadow_run"])
    if "containment" in doc:
        cm = doc["containment"]
        if not isinstance(cm, list) or any(not isinstance(x, str) or x not in ("no_network", "readonly_workspace") for x in cm) or cm != sorted(set(cm)):
            raise ValueError("containment")
    return {"classes": c_set, "tests": t_set, "snapshot": snap, "pack_ref": pref, "version": doc["version"], "execution_ref": ex_ref, "subject_ref": s_ref, "touched": set(doc.get("touched", [])), "containment": set(doc.get("containment", [])), "shadow_run": doc.get("shadow_run")}


def lookup_registered_shadow_py(probe_path: Path) -> str:
    reg = os.environ.get("DRIFT_SHADOW_REGISTRY", "").strip()
    reg_p = Path(reg) if reg else (Path(os.environ.get("XDG_CONFIG_HOME", "").strip() or (Path.home() / ".config")) / "drift" / "shadows.toml")
    if not reg_p.is_file() or reg_p.is_symlink():
        return ""
    try:
        st = reg_p.stat()
        rk = (str(reg_p), st.st_mtime_ns, st.st_size)
        if rk not in _SREG:
            doc = tomllib.loads(reg_p.read_text("utf-8"))
            _SREG[rk] = (doc.get("areas") or {}) if doc.get("schema") == "drift.shadow-registry/1" else {}
        if not (areas := _SREG[rk]):
            return ""
    except Exception:
        return ""
    cur = probe_path.resolve()
    for d in (cur, *cur.parents):
        if (sd := str(areas.get(str(d), "")).strip()) and (Path(sd) / "shadow.toml").is_file():
            return sd
    return ""


def resolve_shadow_roots_impl(path: Any, state_dir: str = "") -> dict[str, Any]:
    p = Path(path)
    is_cc = p.parent.name == "contracts" and p.parent.parent.name == ".drift"
    ck = (str(p.parent), state_dir, *(os.environ.get(k, "") for k in ("DRIFT_STATE_DIR", "DRIFT_SOURCE_ROOT", "DRIFT_SHADOW_REGISTRY", "XDG_CONFIG_HOME")), str(Path.cwd())) if is_cc else None
    if ck and ck in _SROOT:
        return dict(_SROOT[ck])

    def _area_of(cand: Path) -> Path:
        if cand.parent.name == "contracts" and cand.parent.parent.name == ".drift":
            return cand.parent.parent.parent
        if cand.name == "config.toml" and cand.parent.name == ".drift":
            return cand.parent.parent
        cur = cand if cand.is_dir() else cand.parent
        for d in (cur, *cur.parents):
            if (d / "shadow.toml").exists() or (d / "shadow.toml").is_symlink() or (d / ".drift").exists():
                return d
        return cand.parent

    env_sd = os.environ.get("DRIFT_STATE_DIR", "").strip()
    sd = state_dir or env_sd or lookup_registered_shadow_py(p if p.exists() else Path.cwd())
    area_root = Path(sd) if sd and not (is_cc or (p / "shadow.toml").exists()) else _area_of(p)
    man = area_root / "shadow.toml"
    if not man.exists() and not man.is_symlink():
        if sd:
            r_area, r_cwd = area_root.resolve(), Path.cwd().resolve()
            if r_area != r_cwd and (r_area.is_relative_to(r_cwd) or r_cwd.is_relative_to(r_area)):
                raise ValueError(f"shadow state directory must lie outside source_root: {area_root}")
        res = {"is_shadow": False, "source_root": area_root, "area_root": area_root, "work_root": area_root / ".drift-work"}
        if ck:
            _SROOT[ck] = dict(res)
        return res
    if man.is_symlink() or not man.is_file():
        raise ValueError(f"shadow.toml must be a regular file: {man}")
    doc = tomllib.loads(man.read_text("utf-8"))
    if set(doc) - {"schema", "source_root"} or doc.get("schema") != "drift.shadow-area/1":
        raise ValueError("invalid shadow.toml schema")
    raw_src = os.environ.get("DRIFT_SOURCE_ROOT", "").strip() or str(doc.get("source_root", "")).strip()
    if not raw_src:
        raise ValueError("missing source_root in shadow.toml")
    src_dir = Path(raw_src) if Path(raw_src).is_absolute() else (area_root / raw_src)
    if not src_dir.is_dir():
        raise ValueError(f"no such source_root: {src_dir}")
    r_area, r_src = area_root.resolve(), src_dir.resolve()
    if r_area == r_src or r_area.is_relative_to(r_src) or r_src.is_relative_to(r_area):
        raise ValueError(f"shadow state directory must lie outside source_root: {area_root}")
    if (r_src / ".drift" / "config.toml").is_file() or (r_src / ".drift" / "contracts").is_dir():
        raise ValueError(f"ambiguous area for {r_src}: both in-tree .drift/ and shadow state directory {r_area} exist")
    if not state_dir and env_sd:
        r_cwd = Path.cwd().resolve()
        if not (r_cwd.is_relative_to(r_src) or r_cwd.is_relative_to(r_area)):
            raise ValueError(f"DRIFT_STATE_DIR ({area_root}) is bound to {r_src}, not {r_cwd}")
    for sub in ("", ".drift", ".drift-work", "harness", "fixtures", ".drift/config.toml", ".drift/contracts", ".drift/profiles", ".drift/proves.toml", ".drift-work/baselines", ".drift-work/events", ".drift-work/runs"):
        cand = area_root if not sub else (area_root / sub)
        if (cand.exists() or cand.is_symlink()) and cand.resolve().is_relative_to(r_src):
            raise ValueError(f"shadow state directory must lie outside source_root: {cand}")
    return {"is_shadow": True, "source_root": r_src, "area_root": r_area, "work_root": r_area / ".drift-work"}


def normalize_bytes(raw: bytes) -> bytes:
    return raw.replace(b"\r\n", b"\n") if b"\x00" not in raw else raw


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(normalize_bytes(path.read_bytes())).hexdigest()


def collect_shadow_inputs(area_root: Path) -> tuple[dict[str, str], str, str]:
    inputs: dict[str, str] = {}
    proves_p = area_root / ".drift" / "proves.toml"
    if proves_p.is_symlink():
        raise ValueError("proves.toml must not be a symlink")
    if proves_p.is_file():
        inputs[".drift/proves.toml"] = file_sha256(proves_p)
    for sub in ("harness", "fixtures"):
        base = area_root / sub
        if base.is_symlink():
            raise ValueError(f"{sub} must not be a symlink")
        if base.is_dir():
            for p in sorted(base.rglob("*")):
                if p.is_symlink():
                    raise ValueError(f"shadow input must not be a symlink: {p}")
                if p.is_file() and "__pycache__" not in p.parts and not p.name.endswith(".pyc"):
                    inputs[p.relative_to(area_root).as_posix()] = file_sha256(p)
    if not inputs:
        inputs[".drift/config.toml"] = file_sha256(area_root / ".drift" / "config.toml")
    b_ref = inputs.get(".drift/proves.toml", "sha256:" + hashlib.sha256(b"").hexdigest())
    sh_snap = "sha256:" + hashlib.sha256(canonical_json(inputs).encode("utf-8")).hexdigest()
    return inputs, b_ref, sh_snap


def shadow_inputs_fresh(sr: Any, sf: Path, area_root: Any = None) -> bool:
    if not isinstance(sr, dict) or not isinstance(s_in := sr.get("shadow_inputs"), dict):
        return True
    try:
        roots = resolve_shadow_roots_impl(area_root or sf)
        cur_inputs, cur_b_ref, cur_sh_snap = collect_shadow_inputs(roots["area_root"])
    except Exception:
        return False
    return cur_b_ref == sr.get("bindings_ref") and cur_sh_snap == sr.get("shadow_snapshot") and cur_inputs == s_in


def order_shadow_shards_py(parsed_shards: list[Any], target_run_id: str = "") -> tuple[list[Any], list[str]]:
    sh_idxs, run_to_idx, dup_errs = [], {}, []
    for idx, item in enumerate(parsed_shards):
        sr = item[6]
        if item[2] and isinstance(sr, dict):
            rid = sr.get("run_id", "")
            if rid in run_to_idx:
                dup_errs.append(f'shadow.duplicate_run_id: "{rid}"')
            run_to_idx[rid] = idx
            sh_idxs.append(idx)
    non_shadow = [s for s in parsed_shards if not (s[2] and isinstance(s[6], dict))]
    if dup_errs:
        return non_shadow, dup_errs
    clean_target = (target_run_id or "").strip()
    if not sh_idxs:
        return parsed_shards, []
    rids = [parsed_shards[i][6]["run_id"] for i in sh_idxs]
    n, rid_pos = len(rids), {r: i for i, r in enumerate(rids)}
    prec = [[False] * n for _ in range(n)]
    for i, s_idx in enumerate(sh_idxs):
        for sup_id in (parsed_shards[s_idx][6].get("supersedes") or ()):
            if sup_id in rid_pos:
                prec[rid_pos[sup_id]][i] = True
    for i, s_i in enumerate(sh_idxs):
        seq_i = int(parsed_shards[s_i][6].get("sequence") or 0)
        for j, s_j in enumerate(sh_idxs):
            seq_j = int(parsed_shards[s_j][6].get("sequence") or 0)
            if i != j and seq_i > 0 and seq_j > 0 and seq_i < seq_j and not prec[j][i]:
                prec[i][j] = True
    for k in range(n):
        for i in range(n):
            if prec[i][k]:
                for j in range(n):
                    if prec[k][j]:
                        prec[i][j] = True
    for i in range(n):
        if prec[i][i]:
            return non_shadow, [f'shadow.supersession_cycle: "{rids[i]}"']
    if clean_target:
        if clean_target not in rid_pos:
            return non_shadow, [f'shadow.unknown_run_id: "{clean_target}"']
        t_pos = rid_pos[clean_target]
        t_sr = parsed_shards[sh_idxs[t_pos]][6]
        keep_pos = [i for i in range(n) if i == t_pos or prec[i][t_pos]] if t_sr.get("selected_tests") else [t_pos]
    else:
        keep_pos = list(range(n))

    def _act_t(item: Any) -> set[str]:
        sel = set(item[6].get("selected_tests") or ())
        return sel if sel else set(item[4])

    for a_i, i in enumerate(keep_pos):
        t_i = _act_t(parsed_shards[sh_idxs[i]])
        for j in keep_pos[a_i + 1 :]:
            if not prec[i][j] and not prec[j][i] and (t_i & _act_t(parsed_shards[sh_idxs[j]])):
                return non_shadow, [f'shadow.ambiguous_run_order: "{rids[i]}" and "{rids[j]}" touch common tests without supersession or --run-id']
    ordered_pos, placed = [], set()
    while len(ordered_pos) < len(keep_pos):
        ready = [p for p in keep_pos if p not in placed and not any(q not in placed and prec[q][p] for q in keep_pos)]
        if not ready:
            break
        ready.sort(key=lambda p: (int(parsed_shards[sh_idxs[p]][6].get("sequence") or 0), rids[p]))
        placed.add(ready[0])
        ordered_pos.append(ready[0])
    return non_shadow + [parsed_shards[sh_idxs[p]] for p in ordered_pos], []
