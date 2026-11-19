#!/usr/bin/env python3
"""Two-phase pre/post-execution JUnit XML and external harness shadow adapter."""
import sys
if sys.version_info < (3, 11):
 sys.stderr.write(f"drift_shadow_junit: Python 3.11+ required (found {sys.version_info.major}.{sys.version_info.minor})\n")
 sys.exit(2)
import argparse, hashlib, json, os, subprocess, tomllib, xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import drift_verify as dv
from drift_verify_base import SNAPSHOT_RE, canonical_json
from drift_verify_subject import (
    SHADOW_RUN_KEYS,
    SHADOW_RUN_SCHEMA,
    collect_shadow_inputs,
    file_sha256,
    lookup_registered_shadow_py,
    normalize_bytes,
    order_shadow_shards_py,
    resolve_shadow_roots_impl,
    shadow_inputs_fresh,
    validate_shadow_run_dict,
)


def run_verifier_self_test() -> int:
 return dv.run_verifier_self_test()


_SKIP_SNAPSHOT_DIRS = frozenset((".git", ".drift", ".drift-work", "target", ".build", "node_modules", "__pycache__"))
_OUTCOME_RANK = {"failed": 3, "skipped": 2, "passed": 1}
def validate_run_id(raw_id: str) -> str:
 rid = raw_id.strip() if isinstance(raw_id, str) else ""
 if not rid or rid != raw_id or "/" in rid or "\\" in rid or ".." in rid:
  raise ValueError(f"invalid --run-id '{raw_id}'")
 return rid
def capture_source_snapshot(source_root: Path) -> str:
 env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null"}
 if (source_root / ".git").exists():
  st = subprocess.run(["git", "-C", str(source_root), "-c", "core.quotepath=false", "status", "--porcelain"], env=env, capture_output=True, text=True)
  rev = subprocess.run(["git", "-C", str(source_root), "rev-parse", "--verify", "--quiet", "HEAD^{tree}"], env=env, capture_output=True, text=True)
  if st.returncode == 0 and st.stdout.strip() == "" and rev.returncode == 0:
   oid = rev.stdout.strip()
   if SNAPSHOT_RE.match(oid): return oid
 h = hashlib.sha256()
 for p in sorted(x for x in source_root.rglob("*") if x.is_file() and not x.is_symlink() and not (_SKIP_SNAPSHOT_DIRS & set(x.relative_to(source_root).parts))):
  rel = p.relative_to(source_root).as_posix()
  norm = normalize_bytes(p.read_bytes())
  h.update(f"{rel}\x00{len(norm)}\x00".encode("utf-8") + norm + b"\n")
 return h.hexdigest()
def collect_contract_digests(area_root: Path) -> dict[str, str]:
 c_dir = area_root / ".drift" / "contracts"
 p_dir = area_root / ".drift" / "profiles"
 out: dict[str, str] = {}
 if c_dir.is_dir():
  for cf in sorted(c_dir.rglob("*.toml")):
   info = dv.verify_contract_toml(cf, p_dir)
   out[info["id"]] = info["ref"]
 return out
def parse_proves_toml(area_root: Path, contract_refs: dict[str, str]) -> dict[str, list[tuple[str, str]]]:
 proves_p = area_root / ".drift" / "proves.toml"
 if not proves_p.is_file(): return {}
 doc = tomllib.loads(proves_p.read_text("utf-8"))
 raw_tests = doc.get("tests") if isinstance(doc.get("tests"), dict) else doc
 bindings: dict[str, list[tuple[str, str]]] = {}
 for k, val in raw_tests.items():
  if not isinstance(val, dict): continue
  tid = str(val.get("test", k)).strip()
  if "#" not in tid: continue
  entries = val.get("proves", [])
  if not isinstance(entries, list): raise ValueError(f"invalid proves list for {tid}")
  pairs: list[tuple[str, str]] = []
  for item in entries:
   cid, sep, case_id = str(item).partition(":")
   if not sep or not cid or not case_id:
    raise ValueError(f"invalid proves entry '{item}' for {tid}")
   if cid not in contract_refs:
    raise ValueError(f"proves entry '{item}' names unknown contract '{cid}'")
   pairs.append((cid, case_id))
  if pairs:
   bindings[tid] = sorted(set(pairs))
 return bindings
def parse_junit_xml_dir(reports_dir: Path) -> tuple[bool, str, set[str], dict[str, str]]:
 xml_files = sorted(reports_dir.glob("*.xml")) if reports_dir.is_dir() else []
 if not xml_files:
  return False, "shadow.report_truncated:no_xml_reports", set(), {}
 executed_classes: set[str] = set()
 outcomes: dict[str, str] = {}
 for xf in xml_files:
  raw_txt = xf.read_text("utf-8", errors="replace").strip()
  if not raw_txt or (not raw_txt.endswith("</testsuite>") and not raw_txt.endswith("</testsuites>") and not (raw_txt.startswith("<testsuite") and raw_txt.endswith("/>"))):
   return False, f"shadow.report_truncated:{xf.name}", set(), {}
  try:
   root = ET.fromstring(raw_txt)
  except ET.ParseError:
   return False, f"shadow.report_truncated:{xf.name}", set(), {}
  suites = [root] if root.tag == "testsuite" else ([s for s in root.iter("testsuite") if s.findall("testcase") or "tests" in s.attrib] if root.tag == "testsuites" else [])
  if not suites:
   return False, f"shadow.report_truncated:{xf.name}", set(), {}
  for suite in suites:
   s_cls = (suite.attrib.get("name") or "").strip()
   if s_cls and "/" not in s_cls and "\\" not in s_cls and "#" not in s_cls:
    executed_classes.add(s_cls)
   cases = list(suite.findall("testcase"))
   decl_cnt = suite.attrib.get("tests")
   if decl_cnt is not None:
    try:
     if int(decl_cnt) > len(cases):
      return False, f"shadow.report_truncated:{xf.name}:expected_{decl_cnt}_got_{len(cases)}", set(), {}
    except ValueError:
     return False, f"shadow.report_truncated:{xf.name}:invalid_tests_attr", set(), {}
   for tc in cases:
    cls = (tc.attrib.get("classname") or s_cls).strip()
    mth = (tc.attrib.get("name") or "").strip()
    if mth.endswith("()"): mth = mth[:-2].strip()
    if not cls or not mth:
     return False, f"shadow.report_truncated:{xf.name}:missing_testcase_identity", set(), {}
    executed_classes.add(cls)
    tid = f"{cls}#{mth}"
    cand_out = "failed" if (tc.find("failure") is not None or tc.find("error") is not None) else ("skipped" if tc.find("skipped") is not None else "passed")
    prev_out = outcomes.get(tid)
    if prev_out is None or _OUTCOME_RANK[cand_out] > _OUTCOME_RANK[prev_out]:
     outcomes[tid] = cand_out
 return True, "", executed_classes, outcomes
def _scan_existing_shadow_runs(work_root: Path, exclude_run_id: str = "") -> tuple[int, list[str]]:
 events_dir = work_root / "events"
 max_seq, prior_ids = 0, set()
 if events_dir.is_dir():
  for mp in sorted(events_dir.glob("*.meta.json")):
   try:
    doc = json.loads(mp.read_text("utf-8"))
    sr = doc.get("shadow_run")
    if isinstance(sr, dict) and sr.get("run_id") and sr.get("run_id") != exclude_run_id:
     prior_ids.add(str(sr["run_id"]))
     max_seq = max(max_seq, int(sr.get("sequence") or 0))
   except Exception:
    pass
 seq_file = work_root / "runs" / ".sequence"
 if seq_file.is_file():
  try: max_seq = max(max_seq, int(seq_file.read_text("utf-8").strip() or "0"))
  except Exception: pass
 return max(max_seq, len(prior_ids)), sorted(prior_ids)
def _allocate_shadow_run_sequence(work_root: Path, exclude_run_id: str, pre_supersedes: list[str] | None = None) -> tuple[int, list[str]]:
 cur_max, cur_priors = _scan_existing_shadow_runs(work_root, exclude_run_id)
 seq_num = cur_max + 1
 seq_file = work_root / "runs" / ".sequence"
 seq_file.parent.mkdir(parents=True, exist_ok=True)
 seq_file.write_text(f"{seq_num}\n", encoding="utf-8")
 sup_ids = sorted((set(pre_supersedes or ()) | set(cur_priors)) - {exclude_run_id})
 return seq_num, sup_ids
def cmd_begin(args) -> int:
 roots = dv.resolve_shadow_roots(args.state_dir, str(args.state_dir))
 if not roots["is_shadow"]:
  print("drift_shadow_junit: state-dir is missing shadow.toml", file=sys.stderr); return 2
 area_root, src_root, work_root = roots["area_root"], roots["source_root"], roots["work_root"]
 run_id = validate_run_id(args.run_id)
 run_dir = work_root / "runs" / run_id
 reports_dir = run_dir / "reports"
 if run_dir.exists() and not args.force:
  print(f"drift_shadow_junit: run_id '{run_id}' already exists", file=sys.stderr); return 2
 reports_dir.mkdir(parents=True, exist_ok=True)
 for old in reports_dir.glob("*"):
  if old.is_file(): old.unlink()
 src_snap = capture_source_snapshot(src_root)
 sh_inputs, b_ref, sh_snap = collect_shadow_inputs(area_root)
 c_refs = collect_contract_digests(area_root)
 _ = parse_proves_toml(area_root, c_refs)
 sel = sorted({t.strip() for t in (args.select or []) if t.strip()})
 if any("#" not in t for t in sel):
  print("drift_shadow_junit: --select requires Class#method test IDs", file=sys.stderr); return 2
 _, prior_ids = _scan_existing_shadow_runs(work_root, run_id)
 pre = {
  "schema": SHADOW_RUN_SCHEMA,
  "phase": "pre_run",
  "run_id": run_id,
  "source_snapshot": src_snap,
  "bindings_ref": b_ref,
  "shadow_snapshot": sh_snap,
  "shadow_inputs": sh_inputs,
  "contract_digests": c_refs,
  "selected_tests": sel,
  "supersedes": prior_ids,
 }
 (run_dir / "pre_run.json").write_text(dv.canonical_json(pre) + "\n", encoding="utf-8")
 if args.json:
  print(json.dumps({"ok": True, "run_id": run_id, "reports_dir": str(reports_dir), "source_snapshot": src_snap, "shadow_snapshot": sh_snap}, sort_keys=True))
 return 0
def cmd_finish(args) -> int:
 roots = dv.resolve_shadow_roots(args.state_dir, str(args.state_dir))
 area_root, src_root, work_root = roots["area_root"], roots["source_root"], roots["work_root"]
 run_id = validate_run_id(args.run_id)
 run_dir = work_root / "runs" / run_id
 pre_p = run_dir / "pre_run.json"
 if not pre_p.is_file():
  print(f"drift_shadow_junit: shadow.missing_pre_run for '{run_id}'", file=sys.stderr); return 2
 pre = json.loads(pre_p.read_text("utf-8"))
 post_src_snap = capture_source_snapshot(src_root)
 post_inputs, post_b_ref, post_sh_snap = collect_shadow_inputs(area_root)
 post_c_refs = collect_contract_digests(area_root)
 if post_src_snap != pre["source_snapshot"] or post_sh_snap != pre["shadow_snapshot"] or post_c_refs != pre["contract_digests"]:
  print("drift_shadow_junit: shadow.context_mutated_during_run", file=sys.stderr); return 2
 bindings = parse_proves_toml(area_root, post_c_refs)
 sel_list = pre.get("selected_tests") or []
 sel_set = set(sel_list)
 ok_xml, trunc_reason, exec_classes, outcomes = parse_junit_xml_dir(run_dir / "reports")
 events_dir = work_root / "events"
 events_dir.mkdir(parents=True, exist_ok=True)
 shard_jsonl = events_dir / f"shadow-{run_id}.jsonl"
 shard_meta = events_dir / f"shadow-{run_id}.meta.json"
 seq_num, sup_ids = _allocate_shadow_run_sequence(work_root, run_id, pre.get("supersedes"))
 sr_meta = {
  "schema": SHADOW_RUN_SCHEMA,
  "run_id": run_id,
  "source_snapshot": post_src_snap,
  "bindings_ref": post_b_ref,
  "shadow_snapshot": post_sh_snap,
  "shadow_inputs": post_inputs,
  "sequence": seq_num,
  **({"supersedes": sup_ids} if sup_ids else {}),
  **({"selected_tests": sel_list} if sel_list else {}),
 }
 validate_shadow_run_dict(sr_meta)
 if not ok_xml:
  all_bound_t = sorted(sel_set if sel_set else set(bindings.keys()))
  all_bound_c = sorted({t.split("#", 1)[0] for t in all_bound_t if "#" in t})
  if all_bound_t:
   shard_jsonl.write_text("", encoding="utf-8")
   meta_inc = {"version": 1, "classes": all_bound_c, "tests": all_bound_t, "snapshot": post_src_snap, "shadow_run": sr_meta}
   shard_meta.write_text(dv.canonical_json(meta_inc) + "\n", encoding="utf-8")
  if args.json:
   print(json.dumps({"ok": False, "reason": trunc_reason, "run_id": run_id}, sort_keys=True))
  else:
   print(f"drift_shadow_junit: {trunc_reason}", file=sys.stderr)
  return 1
 disc_tests: set[str] = set()
 disc_classes: set[str] = set(exec_classes)
 removed_tests: list[str] = []
 for tid in sorted(outcomes):
  if sel_set and tid not in sel_set: continue
  cls = tid.split("#", 1)[0]
  disc_classes.add(cls)
  disc_tests.add(tid)
 for b_tid in sorted(bindings):
  if sel_set and b_tid not in sel_set: continue
  b_cls = b_tid.split("#", 1)[0]
  disc_classes.add(b_cls)
  if b_tid not in outcomes:
   removed_tests.append(b_tid)
 event_lines: list[str] = []
 for tid in sorted(disc_tests):
  if tid not in bindings: continue
  by_contract: dict[str, list[str]] = {}
  for cid, case_id in bindings[tid]:
   by_contract.setdefault(cid, []).append(case_id)
  for cid in sorted(by_contract):
   ev = {
  "test": tid,
  "contract": cid,
  "cases": sorted(set(by_contract[cid])),
  "level": args.level,
  "outcome": outcomes[tid],
  "digest": post_c_refs[cid],
  **({"schema": "0.3"} if post_c_refs[cid].startswith("dr2b:") else {}),
   }
   event_lines.append(dv.canonical_json(ev))
 inputs_map = {tid: post_inputs for tid in sorted(disc_tests)}
 meta_doc = {
  "version": 1,
  "classes": sorted(disc_classes),
  "tests": sorted(disc_tests),
  "snapshot": post_src_snap,
  **({"inputs": inputs_map} if inputs_map else {}),
  "shadow_run": sr_meta,
 }
 shard_jsonl.write_text(("\n".join(event_lines) + "\n") if event_lines else "", encoding="utf-8")
 shard_meta.write_text(dv.canonical_json(meta_doc) + "\n", encoding="utf-8")
 if args.json:
  print(json.dumps({"ok": True, "run_id": run_id, "shard": str(shard_jsonl), "events": len(event_lines), "discovered_tests": sorted(disc_tests), "removed_tests": removed_tests}, sort_keys=True))
 return 0
def cmd_stamp_harness(args) -> int:
 roots = dv.resolve_shadow_roots(args.state_dir, str(args.state_dir))
 area_root, src_root, work_root = roots["area_root"], roots["source_root"], roots["work_root"]
 run_id = validate_run_id(args.run_id)
 pre_p = work_root / "runs" / run_id / "pre_run.json"
 if not pre_p.is_file():
  print(f"drift_shadow_junit: shadow.missing_pre_run for '{run_id}'", file=sys.stderr); return 2
 pre = json.loads(pre_p.read_text("utf-8"))
 post_src_snap = capture_source_snapshot(src_root)
 post_inputs, post_b_ref, post_sh_snap = collect_shadow_inputs(area_root)
 post_c_refs = collect_contract_digests(area_root)
 if post_src_snap != pre["source_snapshot"] or post_sh_snap != pre["shadow_snapshot"] or post_c_refs != pre["contract_digests"]:
  print("drift_shadow_junit: shadow.context_mutated_during_run", file=sys.stderr); return 2
 sel_list = pre.get("selected_tests") or []
 seq_num, sup_ids = _allocate_shadow_run_sequence(work_root, run_id, pre.get("supersedes"))
 sr_meta = {
  "schema": SHADOW_RUN_SCHEMA,
  "run_id": run_id,
  "source_snapshot": post_src_snap,
  "bindings_ref": post_b_ref,
  "shadow_snapshot": post_sh_snap,
  "shadow_inputs": post_inputs,
  "sequence": seq_num,
  **({"supersedes": sup_ids} if sup_ids else {}),
  **({"selected_tests": sel_list} if sel_list else {}),
 }
 validate_shadow_run_dict(sr_meta)
 events_dir = (work_root / "events").resolve()
 mp = Path(args.meta) if args.meta else (events_dir / f"shadow-{run_id}.meta.json")
 if not mp.is_file() or mp.is_symlink() or not mp.resolve().is_relative_to(events_dir):
  print("drift_shadow_junit: --meta must name a regular file inside <work_root>/events", file=sys.stderr); return 2
 if mp.stat().st_mtime_ns + 100_000_000 < pre_p.stat().st_mtime_ns:
  print("drift_shadow_junit: --meta predates pre_run.json", file=sys.stderr); return 2
 doc = json.loads(mp.read_text("utf-8"))
 if isinstance(doc.get("shadow_run"), dict) and doc["shadow_run"].get("run_id") not in (None, "", run_id):
  print("drift_shadow_junit: cannot restamp shard from another run_id", file=sys.stderr); return 2
 doc["snapshot"] = post_src_snap
 doc["shadow_run"] = sr_meta
 in_m = doc.get("inputs") if isinstance(doc.get("inputs"), dict) else {}
 for tid in doc.get("tests") or ():
  merged_t = {**(in_m.get(tid) or {}), **post_inputs}
  in_m[tid] = merged_t
 if in_m: doc["inputs"] = in_m
 mp.write_text(dv.canonical_json(doc) + "\n", encoding="utf-8")
 if args.json:
  print(json.dumps({"ok": True, "run_id": run_id, "stamped": [str(mp)]}, sort_keys=True))
 return 0
def cmd_import_historical(args) -> int:
 xf = Path(args.historical_xml)
 if not xf.is_file():
  print(f"drift_shadow_junit: no such XML file: {xf}", file=sys.stderr); return 2
 out = {"ok": False, "historical": True, "accredited": False, "reason": "shadow.unanchored_xml_rejected", "file": xf.name}
 if args.json: print(json.dumps(out, sort_keys=True))
 else: print("drift_shadow_junit: shadow.unanchored_xml_rejected (historical XML cannot be accredited without pre-run provenance)", file=sys.stderr)
 return 1
def main(argv=None) -> int:
 ap = argparse.ArgumentParser(prog="drift_shadow_junit.py")
 sub = ap.add_subparsers(dest="cmd", required=True)
 p_beg = sub.add_parser("begin")
 p_beg.add_argument("--state-dir", type=Path, default=Path(os.environ.get("DRIFT_STATE_DIR", ".")))
 p_beg.add_argument("--run-id", required=True)
 p_beg.add_argument("--select", action="append", default=[])
 p_beg.add_argument("--force", action="store_true")
 p_beg.add_argument("--json", action="store_true")
 p_fin = sub.add_parser("finish")
 p_fin.add_argument("--state-dir", type=Path, default=Path(os.environ.get("DRIFT_STATE_DIR", ".")))
 p_fin.add_argument("--run-id", required=True)
 p_fin.add_argument("--level", default="unit")
 p_fin.add_argument("--json", action="store_true")
 p_stm = sub.add_parser("stamp-harness")
 p_stm.add_argument("--state-dir", type=Path, default=Path(os.environ.get("DRIFT_STATE_DIR", ".")))
 p_stm.add_argument("--run-id", required=True)
 p_stm.add_argument("--meta", default="")
 p_stm.add_argument("--json", action="store_true")
 p_his = sub.add_parser("import-historical")
 p_his.add_argument("--historical-xml", required=True)
 p_his.add_argument("--json", action="store_true")
 args = ap.parse_args(argv)
 try:
  if args.cmd == "begin": return cmd_begin(args)
  if args.cmd == "finish": return cmd_finish(args)
  if args.cmd == "stamp-harness": return cmd_stamp_harness(args)
  if args.cmd == "import-historical": return cmd_import_historical(args)
 except Exception as exc:
  print(f"drift_shadow_junit: {exc}", file=sys.stderr); return 2
 return 2
if __name__ == "__main__":
 sys.exit(main())
