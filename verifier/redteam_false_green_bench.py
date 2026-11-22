#!/usr/bin/env python3
"""Reproducible anti-false-green red-team benchmark for DRIFT (MIT License).

Measures real false-green and false-red rates across 11 protocol-aware adversarial
attacks (attempting to make CI go green without fixing a real SUT bug) and 2 positive
controls (where the SUT bug is genuinely fixed), comparing:
  1. baseline-unit-tests        (ordinary editable tests without DRIFT)
  2. drift-free-verified        (DRIFT Free, proof = "verified", unsigned approvals)
  3. drift-enterprise-hardened  (DRIFT Enterprise: killed + --when mutants + signed approvals)
  4. drift-isolated-ci          (DRIFT + .drift/ & acceptance harness outside agent write scope)

Every DRIFT verdict is computed live by executing the real CLI (`drift`) and MIT Python
verifier (`drift_verify.py`) — never simulated or hardcoded.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))


def _find_bridge_py() -> Path:
    for cand in (ROOT_DIR / "integrations/py", ROOT_DIR / "bridges"):
        if (cand / "drift.py").is_file():
            return cand
    raise FileNotFoundError("cannot locate drift.py bridge")


def _find_verifier_py() -> Path:
    for cand in (SCRIPTS_DIR / "drift_verify.py", ROOT_DIR / "verifier/drift_verify.py"):
        if cand.is_file():
            return cand
    raise FileNotFoundError("cannot locate drift_verify.py")


PROFILE_TOML = """drift = "0.3"
profile = "http-json@1"

[schema.when]
request = { type = "string" }

[schema.then]
status = { type = "int" }
name = { type = "string" }
error = { type = "string" }
"""

CONTRACT_TOML = """drift = "0.3"
id = "item-get"
intent = "Return item details for valid IDs and 404 for unknown IDs."

[use]
profile = "http-json@1"

[scope]
surface = "GET /items/{id}"
writes = []
reads = ["items"]
indirect = "none"

[cases.found]
at = ["http"]
when.request = "GET /items/1"
then.status = 200
then.name = "lamp"

[cases.not-found]
at = ["http"]
when.request = "GET /items/999"
then.status = 404
then.error = "item not found"
"""


def _config_toml(proof: str, require_signed: bool = False) -> str:
    extra = "\nrequire_signed_approval = true" if require_signed else ""
    return (
        'drift = "0.3"\nkind = "config"\n\n[area]\nowner = "items-team"\n\n'
        f'[policy]\npack = "core@1"\napprovers = ["items-team"]\nproof = "{proof}"{extra}\n'
    )


def _sut_response(req: str, *, fixed: bool) -> dict[str, Any]:
    # Buggy SUT returns 500 on /items/1 (missing fix); fixed SUT returns 200 lamp / 404 item not found.
    item_id = req.rsplit("/", 1)[-1]
    if item_id == "1":
        return {"status": 200, "name": "lamp"} if fixed else {"status": 500, "name": "broken"}
    return {"status": 404, "error": "item not found"}


def _run_py_bridge(bridge_dir: Path, resolved_dir: Path, ev_file: Path, code: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PYTHONPATH": str(bridge_dir),
        "DRIFT_RESOLVED": str(resolved_dir),
        "DRIFT_EVENTS": str(ev_file),
        **(extra_env or {}),
    }
    return subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, env=env, check=False)


def _run_gate(
    drift_bin: Path,
    contracts_dir: Path,
    cfg_path: Path,
    ev_dir: Path,
    *,
    edition: str = "free",
    extra_args: list[str] | None = None,
) -> tuple[bool, dict[str, Any]]:
    env = {**os.environ}
    if edition == "free":
        env["DRIFT_EDITION"] = "free"
    else:
        env.pop("DRIFT_EDITION", None)
    cmd = [
        str(drift_bin), "gate", str(contracts_dir),
        "--config", str(cfg_path),
        "--events", str(ev_dir),
        "--explain", "--json",
        *(extra_args or []),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
    if res.stdout.strip():
        try:
            doc = json.loads(res.stdout)["contracts"][0]
            return bool(doc.get("ok")), doc
        except Exception:
            pass
    return False, {"ok": False, "reasons": [f"cli.rc_{res.returncode}"], "stderr": res.stderr.strip()}


def _run_verifier(verifier_py: Path, contracts_dir: Path, cfg_path: Path, ev_dir: Path, extra_args: list[str] | None = None) -> tuple[bool, dict[str, Any]]:
    cmd = [
        sys.executable, "-B", str(verifier_py), str(contracts_dir),
        "--config", str(cfg_path), "--events", str(ev_dir), "--json", *(extra_args or []),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.stdout.strip():
        try:
            doc = json.loads(res.stdout)["contracts"][0]
            return bool(doc.get("ok")), doc
        except Exception:
            pass
    return False, {"ok": False, "reasons": [f"verifier.rc_{res.returncode}"], "stderr": res.stderr.strip()}


def _sign_owner_approval(
    drift_bin: Path,
    cfg_p: Path,
    c_p: Path,
    sig_dir: Path,
    ssh_key: Path,
) -> tuple[str, str]:
    subprocess.run([str(drift_bin), "approve", str(c_p), "--by", "items-team"], check=True, capture_output=True)
    cfg_chk = json.loads(subprocess.check_output([str(drift_bin), "check", str(cfg_p), "--json"], text=True))["files"][0]
    c_chk = json.loads(subprocess.check_output([str(drift_bin), "check", str(c_p), "--json"], text=True))["files"][0]
    dig = c_chk["digest"]
    adig = c_chk.get("assurance_digest") or "none"
    pol_ref = cfg_chk["digest"]
    payload = {
        "context_ref": adig,
        "meaning": "owner_approval",
        "policy_ref": pol_ref,
        "schema": "drift.signature-payload/1",
        "signed_at": "2026-11-20T09:00:00Z",
        "signer": "owner:items-team",
        "target_kind": "contract",
        "target_ref": dig,
    }
    p_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    sig_dir.mkdir(parents=True, exist_ok=True)
    tmp_p = sig_dir / "_payload.tmp"
    tmp_p.write_text(p_json, encoding="utf-8")
    subprocess.run(["ssh-keygen", "-Y", "sign", "-q", "-f", str(ssh_key), "-n", "drift-signature@v1", str(tmp_p)], check=True)
    sig_txt = Path(f"{tmp_p}.sig").read_text(encoding="utf-8").strip()
    tmp_p.unlink(missing_ok=True)
    Path(f"{tmp_p}.sig").unlink(missing_ok=True)
    env_doc = {"payload": payload, "schema": "drift.signature-envelope/1", "signature": sig_txt}
    (sig_dir / "owner.sig.json").write_text(json.dumps(env_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dig, adig


def _init_area(
    drift_bin: Path,
    base: Path,
    *,
    proof: str,
    require_signed: bool = False,
    ssh_key: Path | None = None,
) -> tuple[Path, Path, Path, str, Path]:
    c_dir = base / ".drift/contracts"
    p_dir = base / ".drift/profiles"
    sig_dir = base / "sigs"
    c_dir.mkdir(parents=True)
    p_dir.mkdir(parents=True)
    (p_dir / "http-json@1.toml").write_text(PROFILE_TOML, encoding="utf-8")
    cfg_p = base / ".drift/config.toml"
    cfg_p.write_text(_config_toml(proof, require_signed=require_signed), encoding="utf-8")
    c_p = c_dir / "item-get.toml"
    c_p.write_text(CONTRACT_TOML, encoding="utf-8")
    subprocess.run([str(drift_bin), "approve", str(cfg_p), "--by", "items-team"], check=True, capture_output=True)
    if require_signed and ssh_key is not None:
        dig, _ = _sign_owner_approval(drift_bin, cfg_p, c_p, sig_dir, ssh_key)
    else:
        subprocess.run([str(drift_bin), "approve", str(c_p), "--by", "items-team"], check=True, capture_output=True)
        chk = json.loads(subprocess.check_output([str(drift_bin), "check", str(c_p), "--json"], text=True))
        dig = chk["files"][0]["digest"]
    res_dir = base / "resolved"
    res_dir.mkdir()
    subprocess.run([str(drift_bin), "show", str(c_dir), "--out", str(res_dir)], check=True, capture_output=True)
    return c_dir, cfg_p, res_dir, dig, sig_dir


def _test_snippet(body: str) -> str:
    return (
        "import drift\n"
        "def sut(req, fixed=False):\n"
        "    i = req.rsplit('/', 1)[-1]\n"
        "    if i == '1': return {'status': 200, 'name': 'lamp'} if fixed else {'status': 500, 'name': 'broken'}\n"
        "    return {'status': 404, 'error': 'item not found'}\n"
        + body
    )


def _genuine_test_code(fixed: bool, escaped_note: bool = False) -> str:
    obs_note = ""
    if escaped_note:
        obs_note = ""
    return _test_snippet(
        f"FIXED = {fixed!r}\n"
        "drift.run_drift_case('item-get', 't.py#found', ['found'], lambda d: d.check('found', sut(d.when('found', 'request'), FIXED)), 'http')\n"
        "drift.run_drift_case('item-get', 't.py#not_found', ['not-found'], lambda d: d.check('not-found', sut(d.when('not-found', 'request'), FIXED)), 'http')\n"
        + obs_note
    )


ATTACK_SPECS = [
    ("A01-contract-edit-unapproved", "Weaken contract then.status=500 without re-approving", False),
    ("A02-stale-event-replay", "Replay previously passing JSONL from an outdated digest", False),
    ("A03-deleted-test-gone", "Delete failing test from suite while retaining old JSONL", False),
    ("A04-partial-then-read", "Omit checking then.name so case stays bound instead of verified", False),
    ("A05-noop-callback", "Pass no-op callback lambda v: None to d.check", False),
    ("A06-self-stub-build-output", "Feed contract d.build_output() directly into d.check", False),
    ("A07-unlisted-approver-forgery", "Recompute digest and write unlisted by='rogue-agent'", False),
    ("A08-allowlisted-self-approval", "Protocol-aware adversary recomputes dr2b and writes allowlisted by='items-team'", False),
    ("A09-hardcoded-actuals-literal", "Pass hardcoded literal {'status': 200, 'name': 'lamp'} to d.check without calling SUT", False),
    ("A10-when-to-then-lookup-table", "Mirror contract when->then in an in-test lookup table without calling SUT", False),
    ("A11-in-process-forged-jsonl", "Write synthetic passing JSONL and .meta.json directly from test process", False),
    ("A12-tautology-callback", "Pass tautology callbacks (() => true, (v) => true, lambda v: True) to d.check", False),
    ("A13-read-without-assert", "Call d.expect() on every then.* field without asserting any observed value", False),
    ("A14-overlapping-test-deleted", "Delete failing test from .meta.json (gone: 1) while a duplicate weak test still covers the case", False),
    ("P01-genuine-fix", "Positive control: SUT bug is genuinely fixed and tested live", True),
    ("P02-genuine-fix-escaped-obs", "Positive control: SUT genuinely fixed with escaped-quote observation", True),
]


def _execute_scenario(
    scenario_id: str,
    drift_bin: Path,
    bridge_dir: Path,
    verifier_py: Path,
    *,
    mode: str,
    root_tmp: Path,
    ssh_key: Path,
    trust_root: Path,
) -> dict[str, Any]:
    """Execute one scenario under a specific configuration and return live pass/fail verdict."""
    # Baseline editable unit tests: adversary can weaken assertions whenever tests are editable.
    if mode == "baseline-unit-tests":
        return {"green": True, "reasons": ["editable_test_passed"]}

    work = root_tmp / f"{mode}-{scenario_id}"
    is_ent = mode == "drift-enterprise-hardened"
    is_iso = mode == "drift-isolated-ci"
    proof = "killed" if is_ent else "verified"
    require_signed = is_ent or is_iso

    c_dir, cfg_p, res_dir, dig, sig_dir = _init_area(
        drift_bin, work, proof=proof, require_signed=require_signed, ssh_key=ssh_key if require_signed else None
    )
    c_p = c_dir / "item-get.toml"
    ev_dir = work / "events"
    ev_dir.mkdir()
    ev_file = ev_dir / "py.jsonl"

    # Under isolated CI, the agent can ONLY change SUT code; contracts & acceptance harness are immutable.
    if is_iso:
        fixed = scenario_id.startswith("P")
        _run_py_bridge(bridge_dir, res_dir, ev_file, _genuine_test_code(fixed))
        extra_g = ["--signatures", str(sig_dir), "--trust-root", str(trust_root)]
        ok, doc = _run_gate(drift_bin, c_dir, cfg_p, ev_dir, edition="enterprise", extra_args=extra_g)
        return {"green": ok, "reasons": doc.get("reasons", [])}

    mut_file = work / "mutants.json"
    mut_dir = work / "mut_events"
    extra_gate: list[str] = []
    if is_ent:
        mut_dir.mkdir()
        subprocess.run([str(drift_bin), "mutants", str(c_dir), "--when", "--out", str(mut_file)], check=True, capture_output=True)
        extra_gate.extend(["--mutants", str(mut_file), "--mutation-events", str(mut_dir), "--signatures", str(sig_dir), "--trust-root", str(trust_root)])

    def _run_code(code: str) -> None:
        _run_py_bridge(bridge_dir, res_dir, ev_file, code)
        if is_ent:
            _run_py_bridge(
                bridge_dir,
                res_dir,
                ev_dir / "py-mut-discard.jsonl",
                code,
                extra_env={"DRIFT_MUTANTS": str(mut_file), "DRIFT_MUTATION_EVENTS": str(mut_dir / "py.mut.jsonl")},
            )

    if scenario_id == "A01-contract-edit-unapproved":
        c_p.write_text(c_p.read_text(encoding="utf-8").replace("then.status = 200", "then.status = 500").replace('then.name = "lamp"', 'then.name = "broken"'), encoding="utf-8")
        subprocess.run([str(drift_bin), "show", str(c_dir), "--out", str(res_dir)], check=True, capture_output=True)
        _run_code(_genuine_test_code(fixed=False))
    elif scenario_id == "A02-stale-event-replay":
        _run_code(_genuine_test_code(fixed=True))
        c_p.write_text(c_p.read_text(encoding="utf-8").replace('then.name = "lamp"', 'then.name = "lantern"'), encoding="utf-8")
        if is_ent:
            _sign_owner_approval(drift_bin, cfg_p, c_p, sig_dir, ssh_key)
        else:
            subprocess.run([str(drift_bin), "approve", str(c_p), "--by", "items-team"], check=True, capture_output=True)
    elif scenario_id == "A03-deleted-test-gone":
        _run_code(_genuine_test_code(fixed=True))
        (ev_dir / "py.meta.json").write_text('{"version":1,"classes":["t.py"],"tests":["t.py#not_found"]}\n', encoding="utf-8")
    elif scenario_id == "A04-partial-then-read":
        code = _test_snippet(
            "try: drift.run_drift_case('item-get', 't.py#found', ['found'], lambda d: d.check('found', {'status': 200}), 'http')\n"
            "except AssertionError: pass\n"
            "drift.run_drift_case('item-get', 't.py#not_found', ['not-found'], lambda d: d.check('not-found', sut(d.when('not-found', 'request'), False)), 'http')\n"
        )
        _run_code(code)
    elif scenario_id == "A05-noop-callback":
        code = _test_snippet(
            "try: drift.run_drift_case('item-get', 't.py#found', ['found'], lambda d: d.check('found', {'status': lambda v: None, 'name': lambda v: None}), 'http')\n"
            "except AssertionError: pass\n"
            "drift.run_drift_case('item-get', 't.py#not_found', ['not-found'], lambda d: d.check('not-found', sut(d.when('not-found', 'request'), False)), 'http')\n"
        )
        _run_code(code)
    elif scenario_id == "A06-self-stub-build-output":
        code = _test_snippet(
            "drift.run_drift_case('item-get', 't.py#found', ['found'], lambda d: d.check('found', d.build_output('found')), 'http')\n"
            "drift.run_drift_case('item-get', 't.py#not_found', ['not-found'], lambda d: d.check('not-found', d.build_output('not-found')), 'http')\n"
        )
        _run_code(code)
    elif scenario_id == "A07-unlisted-approver-forgery":
        c_p.write_text(c_p.read_text(encoding="utf-8").replace("then.status = 200", "then.status = 500").replace('then.name = "lamp"', 'then.name = "broken"'), encoding="utf-8")
        subprocess.run([str(drift_bin), "approve", str(c_p), "--by", "rogue-agent"], capture_output=True)
        c_p.write_text(c_p.read_text(encoding="utf-8").replace('by = "items-team"', 'by = "rogue-agent"'), encoding="utf-8")
        subprocess.run([str(drift_bin), "show", str(c_dir), "--out", str(res_dir)], check=True, capture_output=True)
        _run_code(_genuine_test_code(fixed=False))
    elif scenario_id == "A08-allowlisted-self-approval":
        c_p.write_text(c_p.read_text(encoding="utf-8").replace("then.status = 200", "then.status = 500").replace('then.name = "lamp"', 'then.name = "broken"'), encoding="utf-8")
        subprocess.run([str(drift_bin), "approve", str(c_p), "--by", "items-team"], check=True, capture_output=True)
        subprocess.run([str(drift_bin), "show", str(c_dir), "--out", str(res_dir)], check=True, capture_output=True)
        if is_ent:
            subprocess.run([str(drift_bin), "mutants", str(c_dir), "--when", "--out", str(mut_file)], check=True, capture_output=True)
        _run_code(_genuine_test_code(fixed=False))
    elif scenario_id == "A09-hardcoded-actuals-literal":
        code = _test_snippet(
            "drift.run_drift_case('item-get', 't.py#found', ['found'], lambda d: d.check('found', {'status': 200, 'name': 'lamp'}), 'http')\n"
            "drift.run_drift_case('item-get', 't.py#not_found', ['not-found'], lambda d: d.check('not-found', {'status': 404, 'error': 'item not found'}), 'http')\n"
        )
        _run_code(code)
    elif scenario_id == "A10-when-to-then-lookup-table":
        code = _test_snippet(
            "TABLE = {'GET /items/1': {'status': 200, 'name': 'lamp'}, 'GET /items/999': {'status': 404, 'error': 'item not found'}}\n"
            "drift.run_drift_case('item-get', 't.py#found', ['found'], lambda d: d.check('found', TABLE.get(d.when('found', 'request'), {'status': 400, 'name': 'bad'})), 'http')\n"
            "drift.run_drift_case('item-get', 't.py#not_found', ['not-found'], lambda d: d.check('not-found', TABLE.get(d.when('not-found', 'request'), {'status': 400, 'error': 'bad'})), 'http')\n"
        )
        _run_code(code)
    elif scenario_id == "A11-in-process-forged-jsonl":
        lines = [
            json.dumps({"test": "t.py#found", "contract": "item-get", "cases": ["found"], "read": ["found"], "level": "http", "outcome": "passed", "digest": dig, "schema": "0.3", "capabilities": []}),
            json.dumps({"test": "t.py#not_found", "contract": "item-get", "cases": ["not-found"], "read": ["not-found"], "level": "http", "outcome": "passed", "digest": dig, "schema": "0.3", "capabilities": []}),
        ]
        ev_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        (ev_dir / "py.meta.json").write_text('{"version":1,"classes":["t.py"],"tests":["t.py#found","t.py#not_found"]}\n', encoding="utf-8")
        if is_ent:
            import hashlib
            man_bytes = mut_file.read_bytes()
            man = json.loads(man_bytes.decode("utf-8"))
            mid = man.get("manifest_id") or ("sha256:" + hashlib.sha256(man_bytes).hexdigest())
            m_lines = []
            for mc in man.get("contracts", []):
                for m in mc.get("mutants", []):
                    m_lines.append(json.dumps({
                        "manifest": mid,
                        "contract": mc["id"],
                        "digest": mc["digest"],
                        "mutant": m["id"],
                        "case": m["case"],
                        "outcome": "killed",
                        "control": "passed",
                    }))
            (mut_dir / "py.mut.jsonl").write_text("\n".join(m_lines) + "\n", encoding="utf-8")
    elif scenario_id == "A12-tautology-callback":
        _run_code(_test_snippet(
            "def _i(v): _ = v; return True\n"
            "for n, f in (('z', lambda: True), ('c', lambda v: True), ('i', _i)):\n"
            "  try: drift.run_drift_case('item-get', f't.py#f_{n}', ['found'], lambda d, f=f: d.check('found', {'status': f, 'name': f}), 'http')\n"
            "  except AssertionError: pass\n"
            "drift.run_drift_case('item-get', 't.py#not_found', ['not-found'], lambda d: d.check('not-found', sut(d.when('not-found', 'request'), False)), 'http')\n"
        ))
        js_b = next((p for p in (ROOT_DIR / "integrations/js/drift.mjs", ROOT_DIR / "bridges/drift.mjs") if p.is_file()), None)
        if js_b and shutil.which("node"):
            js = f"import{{runDriftCase}}from {json.dumps(js_b.resolve().as_uri())};for(const[n,f]of[['z',()=>true],['c',v=>true]])try{{await runDriftCase({{contract:'item-get',test:`t.mjs#${{n}}`,cases:['found'],level:'http'}},d=>d.check('found',{{status:f,name:f}}))}}catch(e){{if(!/must inspect/.test(e))throw e}}"
            subprocess.run(["node", "--input-type=module", "-e", js], env={**os.environ, "DRIFT_RESOLVED": str(res_dir), "DRIFT_EVENTS": str(ev_dir / "js.jsonl")}, capture_output=True, text=True, check=True)
    elif scenario_id == "A13-read-without-assert":
        _run_code(_test_snippet(
            "drift.run_drift_case('item-get','t.py#found',['found'],lambda d:(d.expect('found','status'),d.expect('found','name')),'http')\n"
            "drift.run_drift_case('item-get','t.py#not_found',['not-found'],lambda d:(d.expect('not-found','status'),d.expect('not-found','error')),'http')\n"
        ))
    elif scenario_id == "A14-overlapping-test-deleted":
        _run_code(_test_snippet(
            "try: drift.run_drift_case('item-get','t.py#f1',['found'],lambda d:d.check('found',sut(d.when('found','request'),False)),'http')\n"
            "except AssertionError: pass\n"
            "drift.run_drift_case('item-get','t.py#f2',['found'],lambda d:d.check('found',{'status':200,'name':'lamp'}),'http')\n"
            "drift.run_drift_case('item-get','t.py#not_found',['not-found'],lambda d:d.check('not-found',sut(d.when('not-found','request'),False)),'http')\n"
        ))
        (ev_dir / "py.meta.json").write_text('{"version":1,"classes":["t.py"],"tests":["t.py#f2","t.py#not_found"]}\n', encoding="utf-8")
    elif scenario_id == "P01-genuine-fix":
        _run_code(_genuine_test_code(fixed=True))
    elif scenario_id == "P02-genuine-fix-escaped-obs":
        lines = [
            json.dumps({"test": "t.py#found", "contract": "item-get", "cases": ["found"], "read": ["found"], "level": "http", "outcome": "passed", "digest": dig, "schema": "0.3", "capabilities": [], "observations": {"found": {"schema": "drift.observation/1", "payload": {"status": 200, "name": "lamp", "trace": '"' + "[" * 65}}}}),
            json.dumps({"test": "t.py#not_found", "contract": "item-get", "cases": ["not-found"], "read": ["not-found"], "level": "http", "outcome": "passed", "digest": dig, "schema": "0.3", "capabilities": []}),
        ]
        ev_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        (ev_dir / "py.meta.json").write_text('{"version":1,"classes":["t.py"],"tests":["t.py#found","t.py#not_found"]}\n', encoding="utf-8")
        if is_ent:
            _run_py_bridge(
                bridge_dir, res_dir, ev_dir / "py-mut-discard.jsonl", _genuine_test_code(fixed=True),
                extra_env={"DRIFT_MUTANTS": str(mut_file), "DRIFT_MUTATION_EVENTS": str(mut_dir / "py.mut.jsonl")},
            )

    ok, doc = _run_gate(drift_bin, c_dir, cfg_p, ev_dir, edition="enterprise" if is_ent else "free", extra_args=extra_gate)
    out: dict[str, Any] = {"green": ok, "reasons": doc.get("reasons", [])}
    if not is_ent:
        v_ok, _ = _run_verifier(verifier_py, c_dir, cfg_p, ev_dir)
        out["verifier_parity"] = (ok == v_ok)
    if doc.get("triage"):
        out["triage_classes"] = sorted({t.get("class", "") for t in doc["triage"] if isinstance(t, dict)})
    return out


def run_benchmark(drift_bin: Path) -> dict[str, Any]:
    bridge_dir = _find_bridge_py()
    verifier_py = _find_verifier_py()
    modes = ("baseline-unit-tests", "drift-free-verified", "drift-enterprise-hardened", "drift-isolated-ci")
    with tempfile.TemporaryDirectory(prefix="drift-redteam-bench-") as td:
        tp = Path(td)
        ssh_key = tp / "owner_ed25519"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(ssh_key)], check=True)
        pub = Path(f"{ssh_key}.pub").read_text(encoding="utf-8").strip()
        trust_root = tp / "allowed_signers"
        trust_root.write_text(f'owner:items-team namespaces="drift-signature@v1" {pub}\n', encoding="utf-8")

        results: dict[str, dict[str, Any]] = {}
        for sid, desc, sut_fixed in ATTACK_SPECS:
            row: dict[str, Any] = {"description": desc, "sut_fixed": sut_fixed, "modes": {}}
            for m in modes:
                row["modes"][m] = _execute_scenario(
                    sid, drift_bin, bridge_dir, verifier_py, mode=m, root_tmp=tp, ssh_key=ssh_key, trust_root=trust_root
                )
            results[sid] = row

    summary: dict[str, Any] = {}
    attacks = [sid for sid, _, fixed in ATTACK_SPECS if not fixed]
    controls = [sid for sid, _, fixed in ATTACK_SPECS if fixed]
    for m in modes:
        fg = [sid for sid in attacks if results[sid]["modes"][m]["green"]]
        fr = [sid for sid in controls if not results[sid]["modes"][m]["green"]]
        summary[m] = {
            "attacks_total": len(attacks),
            "attacks_blocked": len(attacks) - len(fg),
            "false_greens": len(fg),
            "false_green_rate": round(len(fg) / len(attacks), 4),
            "residual_false_green_ids": fg,
            "controls_total": len(controls),
            "false_reds": len(fr),
            "false_red_rate": round(len(fr) / len(controls), 4),
        }
    return {"summary": summary, "scenarios": results}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# DRIFT Anti-False-Green Red-Team Benchmark",
        "",
        "| Configuration | Attacks Blocked | False Greens | False-Green Rate | False Reds | Residual False Greens |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for m, s in report["summary"].items():
        res_ids = ", ".join(s["residual_false_green_ids"]) or "none"
        lines.append(
            f"| `{m}` | {s['attacks_blocked']}/{s['attacks_total']} | {s['false_greens']}/{s['attacks_total']} | {s['false_green_rate']*100:.1f}% | {s['false_reds']}/{s['controls_total']} | {res_ids} |"
        )
    lines.extend(["", "## Per-Scenario Verdicts", "", "| Scenario | SUT Fixed | Baseline | Free `verified` | Enterprise Hardened | Isolated CI |", "|---|:---:|:---:|:---:|:---:|:---:|"])
    for sid, row in report["scenarios"].items():
        ms = row["modes"]
        def _cell(m: str) -> str:
            d = ms[m]
            lbl = "GREEN" if d["green"] else "BLOCKED"
            if d.get("triage_classes"):
                lbl += f" ({','.join(d['triage_classes'])})"
            return lbl
        lines.append(f"| `{sid}` | {'yes' if row['sut_fixed'] else 'no'} | {_cell('baseline-unit-tests')} | {_cell('drift-free-verified')} | {_cell('drift-enterprise-hardened')} | {_cell('drift-isolated-ci')} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="redteam_false_green_bench.py")
    default_drift = ROOT_DIR / ".build" / "drift"
    if not default_drift.is_file():
        on_path = shutil.which("drift")
        if on_path:
            default_drift = Path(on_path)
    p.add_argument("--drift", type=Path, default=default_drift)
    p.add_argument("--as", dest="fmt", choices=("md", "json"), default="md")
    a = p.parse_args(argv)
    if not a.drift.is_file():
        print(f"redteam_false_green_bench: missing drift binary at {a.drift}", file=sys.stderr)
        return 2
    rep = run_benchmark(a.drift)
    print(json.dumps(rep, indent=2, sort_keys=True) if a.fmt == "json" else render_markdown(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
