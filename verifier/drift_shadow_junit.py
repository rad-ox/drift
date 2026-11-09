#!/usr/bin/env python3
"""Two-phase pre/post-execution JUnit XML and external harness shadow adapter."""
import argparse, hashlib, json, os, subprocess, sys, tomllib, xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import drift_verify as dv
SHADOW_RUN_SCHEMA = "drift.shadow-run/1"
SHADOW_RUN_KEYS = frozenset(("schema", "run_id", "source_snapshot", "bindings_ref", "shadow_snapshot", "selected_tests", "shadow_inputs", "sequence", "supersedes"))
SNAPSHOT_RE = dv.SNAPSHOT_RE
def validate_shadow_run_dict(sr):
 if not isinstance(sr, dict) or any(k not in SHADOW_RUN_KEYS for k in sr) or sr.get("schema") != SHADOW_RUN_SCHEMA: raise ValueError("shadow_run")
 rid, s_snap, b_ref, sh_snap, s_in = sr.get("run_id", ""), sr.get("source_snapshot", ""), sr.get("bindings_ref", ""), sr.get("shadow_snapshot", ""), sr.get("shadow_inputs")
 if not isinstance(rid, str) or not rid.strip() or rid != rid.strip() or "/" in rid or "\\" in rid or ".." in rid: raise ValueError("shadow_run.run_id")
 if not isinstance(s_snap, str) or not SNAPSHOT_RE.match(s_snap) or not isinstance(b_ref, str) or len(b_ref) != 71 or not b_ref.startswith("sha256:") or not isinstance(sh_snap, str) or len(sh_snap) != 71 or not sh_snap.startswith("sha256:"): raise ValueError("shadow_run.ref")
 if not isinstance(s_in, dict) or not s_in or any(not isinstance(k, str) or not k.strip() or k.startswith("/") or "\\" in k or any(p in ("", ".", "..") for p in k.split("/")) or not isinstance(v, str) or len(v) != 71 or not v.startswith("sha256:") for k, v in s_in.items()): raise ValueError("shadow_run.inputs")
 if "selected_tests" in sr and (not isinstance(st_l := sr["selected_tests"], list) or not all(isinstance(x, str) and "#" in x for x in st_l) or st_l != sorted(set(st_l))): raise ValueError("shadow_run.selected_tests")
 if "sequence" in sr and (not isinstance(seq := sr["sequence"], int) or isinstance(seq, bool) or seq < 1): raise ValueError("shadow_run.sequence")
 if "supersedes" in sr and (not isinstance(sup_l := sr["supersedes"], list) or not all(isinstance(x, str) and bool(x.strip()) and x == x.strip() and "/" not in x and "\\" not in x and ".." not in x and x != rid for x in sup_l) or sup_l != sorted(set(sup_l))): raise ValueError("shadow_run.supersedes")
from drift_verify_sim import order_shadow_shards_py
def lookup_registered_shadow_py(probe_path: Path) -> str:
 reg = os.environ.get("DRIFT_SHADOW_REGISTRY", "").strip()
 reg_p = Path(reg) if reg else (Path(os.environ.get("XDG_CONFIG_HOME", "").strip() or (Path.home() / ".config")) / "drift" / "shadows.toml")
 if not reg_p.is_file() or reg_p.is_symlink(): return ""
 try:
  doc = tomllib.loads(reg_p.read_text("utf-8"))
  if doc.get("schema") != "drift.shadow-registry/1": return ""
  areas = doc.get("areas") or {}
 except Exception: return ""
 cur = probe_path.resolve()
 for d in (cur, *cur.parents):
  sd = str(areas.get(str(d), "")).strip()
  if sd and (Path(sd) / "shadow.toml").is_file(): return sd
 return ""
def resolve_shadow_roots_impl(path, state_dir=""):
 p = Path(path)
 def _area_of(cand):
  if cand.parent.name == "contracts" and cand.parent.parent.name == ".drift": return cand.parent.parent.parent
  if cand.name == "config.toml" and cand.parent.name == ".drift": return cand.parent.parent
  cur = cand if cand.is_dir() else cand.parent
  for d in (cur, *cur.parents):
   if (d / "shadow.toml").exists() or (d / "shadow.toml").is_symlink() or (d / ".drift").exists(): return d
  return cand.parent
 env_sd = os.environ.get("DRIFT_STATE_DIR", "").strip()
 sd = state_dir or env_sd or lookup_registered_shadow_py(p if p.exists() else Path.cwd())
 area_root = Path(sd) if sd and not ((p.parent.name == "contracts" and p.parent.parent.name == ".drift") or (p / "shadow.toml").exists()) else _area_of(p)
 man = area_root / "shadow.toml"
 if not man.exists() and not man.is_symlink():
  if sd:
   r_area, r_cwd = area_root.resolve(), Path.cwd().resolve()
   if r_area != r_cwd and (r_area.is_relative_to(r_cwd) or r_cwd.is_relative_to(r_area)):
    raise ValueError(f"shadow state directory must lie outside source_root: {area_root}")
  return {"is_shadow": False, "source_root": area_root, "area_root": area_root, "work_root": area_root / ".drift-work"}
 if man.is_symlink() or not man.is_file(): raise ValueError(f"shadow.toml must be a regular file: {man}")
 doc = tomllib.loads(man.read_text("utf-8"))
 if set(doc) - {"schema", "source_root"} or doc.get("schema") != "drift.shadow-area/1": raise ValueError("invalid shadow.toml schema")
 raw_src = os.environ.get("DRIFT_SOURCE_ROOT", "").strip() or str(doc.get("source_root", "")).strip()
 if not raw_src: raise ValueError("missing source_root in shadow.toml")
 src_dir = Path(raw_src) if Path(raw_src).is_absolute() else (area_root / raw_src)
 if not src_dir.is_dir(): raise ValueError(f"no such source_root: {src_dir}")
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
def shadow_inputs_fresh(sr, sf, area_root=None):
 if not isinstance(sr, dict) or not isinstance(s_in := sr.get("shadow_inputs"), dict): return True
 try:
  roots = resolve_shadow_roots_impl(area_root or sf)
  cur_inputs, cur_b_ref, cur_sh_snap = collect_shadow_inputs(roots["area_root"])
 except Exception: return False
 return cur_b_ref == sr.get("bindings_ref") and cur_sh_snap == sr.get("shadow_snapshot") and cur_inputs == s_in
def _expect_err(fn, arg):
 try:
  fn(arg)
  raise AssertionError(arg)
 except ValueError: pass
def run_verifier_self_test():
 assert dv.canonical_json(-0.0) == "0" and dv.canonical_json(1e21) == "1e+21" and dv.canonical_json(1e-6) == "0.000001" and dv.canonical_json(1e-7) == "1e-7" and dv.canonical_json({"\ue000": 1, "\U0001f600": 2}) == '{"\U0001f600":2,"\ue000":1}'
 for b in (1 << 53, -(1 << 53), float("nan"), float("inf")): _expect_err(dv.canonical_json, b)
 eb = '"contract":"a","cases":["c"],"level":"unit","outcome":"passed"'
 for b in (f'"test":"t#1","test":"t#2",{eb}', f'"test":"t#1",{eb},"extra":1', f'"test":"t#1",{eb},"read":["other"]', '"test":"t#1","contract":"Bad_Id","cases":["c"],"level":"unit","outcome":"passed"', '"test":"t#1","contract":"a","cases":["c"],"level":"Unit","outcome":"passed"', f'"test":"t#1",{eb},"digest":"dr1:UPPER0000000"'): _expect_err(dv.validate_event_line, "{" + b + "}")
 _expect_err(dv.validate_event_line, '{"a":' * 65 + '1' + '}' * 65)
 assert len(dv.validate_inventory_text(json.dumps({"version": 1, "classes": ["a.mjs", "b.mjs"], "tests": ["a.mjs#t1", "b.mjs#t2"], "snapshot": "0" * 40, "pack_ref": "dr1:" + "0" * 12, "touched": ["src/a.mjs", "src/b.mjs"], "inputs": {"a.mjs#t1": {"src/a.mjs": "sha256:111"}}, "env": dict.fromkeys(dv.ENV_KEYS, "v")}))["tests"]) == 2
 assert dv.validate_inventory_text(json.dumps({"version": 2, "classes": ["a"], "tests": ["a#t"], "execution_ref": "sha256:" + "a" * 64, "touched": []}))["version"] == 2
 ib = '"version":1,"classes":["a"],"tests":["a#t1"]'
 for sfx in ('"version":2,"classes":[],"tests":[]', '"version":true,"classes":[],"tests":[]', '"version":1,"classes":["b","a"],"tests":[]', '"version":1,"classes":["a/b"],"tests":[]', '"version":1,"classes":["a"],"tests":["other#t1"]', f'{ib},"snapshot":"bad"', f'{ib},"pack_ref":"dr1:bad"', f'{ib},"touched":["/abs"]', f'{ib},"touched":["../e"]', f'{ib},"inputs":{{"u#t":{{"f":"1"}}}}', f'{ib},"env":{{"toolchain":"v1"}}', f'{ib},"extra":1'): _expect_err(dv.validate_inventory_text, "{" + sfx + "}")
 assert dv._is_unanchored_prose_source("observed in prod") and not dv._is_unanchored_prose_source("src/a/Item.java") and dv._has_approval_blocker({"scope": {"indirect": "unknown"}}, {})
 ck = {"id": "svc", "digest": "dr1:sha256:" + "a" * 64, "ref": "dr1:" + "a" * 12, "approval": "current", "approver": "o", "profile_proof": "killed", "cases": {"ok": {"at": ["unit"], "then": {"status": 200}}}, "open_cnt": 0, "exec_blk": False, "rel_blk": False}
 ev = [{"test": "T#ok", "contract": "svc", "cases": ["ok"], "read": ["ok"], "level": "unit", "outcome": "passed", "digest": ck["ref"]}]
 assert not dv.evaluate_contract(ck, "current", ev, 0, 0, [])["ok"] and dv.evaluate_contract(ck, "current", ev, 0, 0, [], mutations_ok=True)["ok"]
 dv.run_sec_self_test(ck, dv.digest_matches)
 dv.run_ra_self_test(ck, dv.digest_matches)
 print("drift_verify.py self-test: ok (RFC 8785 JCS, event & full inventory schema vectors passed)")
 return 0
def normalize_bytes(raw: bytes) -> bytes:
 return raw.replace(b"\r\n", b"\n") if b"\x00" not in raw else raw
def file_sha256(path: Path) -> str:
 return "sha256:" + hashlib.sha256(normalize_bytes(path.read_bytes())).hexdigest()
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
   if dv.SNAPSHOT_RE.match(oid): return oid
 h = hashlib.sha256()
 for p in sorted(x for x in source_root.rglob("*") if x.is_file() and not x.is_symlink() and not (_SKIP_SNAPSHOT_DIRS & set(x.relative_to(source_root).parts))):
  rel = p.relative_to(source_root).as_posix()
  norm = normalize_bytes(p.read_bytes())
  h.update(f"{rel}\x00{len(norm)}\x00".encode("utf-8") + norm + b"\n")
 return h.hexdigest()
def collect_shadow_inputs(area_root: Path) -> tuple[dict[str, str], str, str]:
 inputs: dict[str, str] = {}
 proves_p = area_root / ".drift" / "proves.toml"
 if proves_p.is_symlink(): raise ValueError("proves.toml must not be a symlink")
 if proves_p.is_file():
  inputs[".drift/proves.toml"] = file_sha256(proves_p)
 for sub in ("harness", "fixtures"):
  base = area_root / sub
  if base.is_symlink(): raise ValueError(f"{sub} must not be a symlink")
  if base.is_dir():
   for p in sorted(base.rglob("*")):
    if p.is_symlink(): raise ValueError(f"shadow input must not be a symlink: {p}")
    if p.is_file() and "__pycache__" not in p.parts and not p.name.endswith(".pyc"):
     rel = p.relative_to(area_root).as_posix()
     inputs[rel] = file_sha256(p)
 if not inputs:
  inputs[".drift/config.toml"] = file_sha256(area_root / ".drift" / "config.toml")
 b_ref = inputs.get(".drift/proves.toml", "sha256:" + hashlib.sha256(b"").hexdigest())
 sh_snap = "sha256:" + hashlib.sha256(dv.canonical_json(inputs).encode("utf-8")).hexdigest()
 return inputs, b_ref, sh_snap
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
