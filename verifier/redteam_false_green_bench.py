#!/usr/bin/env python3
"""Reproducible anti-false-green red-team benchmark for DRIFT (MIT License).

Measures live false-green and false-red rates across 14 protocol-aware adversarial
attacks (attempting to make CI go green without fixing a real SUT bug) and 8 positive
controls (where the SUT bug is genuinely fixed), comparing five live configurations:
  1. baseline-unit-tests          (ordinary editable Python unittest suite, no DRIFT)
  2. isolated-unit-tests-no-drift (read-only Python unittest acceptance suite, no DRIFT)
  3. drift-free-verified          (DRIFT Free, proof = "verified", unsigned approvals)
  4. drift-enterprise-hardened    (DRIFT Enterprise: killed + --when mutants + signed approvals)
  5. drift-isolated-ci            (DRIFT + OS read-only .drift/ & acceptance harness perimeter)

Every configuration runs live subprocesses (real unittest suites, real Python/JS bridges,
real `drift` CLI, and MIT `drift_verify.py`). On a Free-only binary (or `--edition free`),
`drift-enterprise-hardened` is explicitly skipped rather than failing. Execution errors,
CLI-vs-verifier parity mismatches, and false reds fail closed (exit 1) and are never
counted as blocked attacks.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
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

from redteam_false_green_fixtures import (  # noqa: E402
    ALL_MODES,
    ATTACK_SPECS,
    CONTRACT_TOML,
    ESCAPED_DEEP_NAME,
    PROFILE_TOML,
    _attempt_perimeter_write,
    _config_toml,
    _genuine_test_code,
    _init_area,
    _lock_readonly,
    _positive_fixture_params,
    _run_gate,
    _run_py_bridge,
    _run_py_bridge_file,
    _run_unittest_mode,
    _run_verifier,
    _sign_owner_approval,
    _test_snippet,
    _unlock_paths,
    render_markdown,
    summarize_results,
)


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


def detect_edition(drift_bin: Path) -> str:
    """Detect effective DRIFT edition ('free', 'pro', or 'enterprise') from `drift version --json`."""
    try:
        res = subprocess.run([str(drift_bin), "version", "--json"], capture_output=True, text=True, check=False)
        if res.returncode == 0 and res.stdout.strip():
            doc = json.loads(res.stdout)
            eff = str(doc.get("effective_edition", "")).strip().lower()
            if eff in ("free", "pro", "enterprise"):
                return eff
            if "mutation_attest" in (doc.get("capabilities") or []):
                return "enterprise"
    except Exception:
        pass
    return "free"


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
    effective_edition: str = "enterprise",
) -> dict[str, Any]:
    """Execute one scenario under a specific configuration and return live pass/fail verdict."""
    work = root_tmp / f"{mode}-{scenario_id}"

    if mode == "baseline-unit-tests":
        return _run_unittest_mode(scenario_id, work, isolated=False)
    if mode == "isolated-unit-tests-no-drift":
        return _run_unittest_mode(scenario_id, work, isolated=True)
    if mode == "drift-enterprise-hardened" and effective_edition != "enterprise":
        return {
            "status": "skipped",
            "green": None,
            "execution_error": False,
            "reasons": ["edition.requires_enterprise"],
        }

    is_ent = mode == "drift-enterprise-hardened"
    is_iso = mode == "drift-isolated-ci"
    use_signed = is_ent or (is_iso and effective_edition == "enterprise")
    proof = "killed" if is_ent else "verified"
    gate_edition = "enterprise" if (is_ent or (is_iso and effective_edition == "enterprise")) else "free"
    fixed = scenario_id.startswith("P")
    exp_name, refactored, c_toml = _positive_fixture_params(scenario_id) if fixed else ("lamp", False, CONTRACT_TOML)
    # For P06 on non-isolated modes, initialize with baseline contract then exercise live owner re-approval.
    init_toml = CONTRACT_TOML if (scenario_id == "P06-genuine-fix-approved-contract-update" and not is_iso) else c_toml

    saved_modes: list[tuple[Path, int]] = []
    try:
        c_dir, cfg_p, res_dir, dig, sig_dir = _init_area(
            drift_bin,
            work,
            proof=proof,
            require_signed=use_signed,
            ssh_key=ssh_key if use_signed else None,
            contract_toml=init_toml,
        )
        c_p = c_dir / "item-get.toml"
        ev_dir = work / "events"
        ev_dir.mkdir()
        ev_file = ev_dir / "py.jsonl"

        if is_iso:
            prot_tests = work / "protected_tests"
            prot_tests.mkdir()
            accept_py = prot_tests / "accept_test.py"
            accept_py.write_text(_genuine_test_code(fixed, sut_name=exp_name, refactored=refactored), encoding="utf-8")
            lock_targets = [work / ".drift", prot_tests]
            if use_signed:
                lock_targets.append(sig_dir)
            saved_modes = _lock_readonly(lock_targets)

            write_denied: bool | None = None
            if not fixed:
                c_denied = _attempt_perimeter_write(c_p, CONTRACT_TOML.replace("then.status = 200", "then.status = 500"))
                t_denied = _attempt_perimeter_write(accept_py, "# tampered\n")
                write_denied = bool(c_denied and t_denied)
                if not write_denied:
                    return {
                        "green": None,
                        "execution_error": True,
                        "write_denied": False,
                        "reasons": ["perimeter.write_not_denied"],
                    }

            _run_py_bridge_file(bridge_dir, res_dir, ev_file, accept_py)
            extra_g = ["--signatures", str(sig_dir), "--trust-root", str(trust_root)] if use_signed else []
            ok, doc = _run_gate(drift_bin, c_dir, cfg_p, ev_dir, edition=gate_edition, extra_args=extra_g)
            out_iso: dict[str, Any] = {
                "green": ok,
                "execution_error": bool(doc.get("execution_error", False)),
                "reasons": doc.get("reasons", []),
                "write_denied": write_denied,
                "runner_kind": "bridge",
            }
            if gate_edition == "free" and not out_iso["execution_error"]:
                v_ok, v_doc = _run_verifier(verifier_py, c_dir, cfg_p, ev_dir)
                if v_doc.get("execution_error"):
                    out_iso["execution_error"] = True
                    out_iso["verifier_parity"] = False
                else:
                    out_iso["verifier_parity"] = (ok == v_ok)
            return out_iso

        mut_file = work / "mutants.json"
        mut_dir = work / "mut_events"
        extra_gate: list[str] = []
        if is_ent:
            mut_dir.mkdir()
            subprocess.run([str(drift_bin), "mutants", str(c_dir), "--when", "--out", str(mut_file)], check=True, capture_output=True)
            extra_gate.extend(["--mutants", str(mut_file), "--mutation-events", str(mut_dir), "--signatures", str(sig_dir), "--trust-root", str(trust_root)])

        def _run_code(code: str, target_ev: Path | None = None) -> None:
            ef = target_ev or ev_file
            _run_py_bridge(bridge_dir, res_dir, ef, code)
            if is_ent:
                _run_py_bridge(
                    bridge_dir,
                    res_dir,
                    ev_dir / f"{ef.stem}-mut-discard.jsonl",
                    code,
                    extra_env={"DRIFT_MUTANTS": str(mut_file), "DRIFT_MUTATION_EVENTS": str(mut_dir / f"{ef.stem}.mut.jsonl")},
                )

        runner_kind = "bridge"

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
            runner_kind = "synthetic_forged"
            lines = [
                json.dumps({"test": "t.py#found", "contract": "item-get", "cases": ["found"], "read": ["found"], "level": "http", "outcome": "passed", "digest": dig, "schema": "0.3", "capabilities": []}),
                json.dumps({"test": "t.py#not_found", "contract": "item-get", "cases": ["not-found"], "read": ["not-found"], "level": "http", "outcome": "passed", "digest": dig, "schema": "0.3", "capabilities": []}),
            ]
            ev_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            (ev_dir / "py.meta.json").write_text('{"version":1,"classes":["t.py"],"tests":["t.py#found","t.py#not_found"]}\n', encoding="utf-8")
            if is_ent:
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
        elif scenario_id in ("P01-genuine-fix", "P03-genuine-fix-bridge-escaped-obs", "P07-genuine-fix-refactor-behavior-unchanged"):
            _run_code(_genuine_test_code(fixed=True, sut_name=exp_name, refactored=refactored))
        elif scenario_id == "P06-genuine-fix-approved-contract-update":
            # Owner updates contract, re-approves (and re-signs on Enterprise), regenerates views, and runs fixed SUT.
            c_p.write_text(c_p.read_text(encoding="utf-8").replace('then.name = "lamp"', 'then.name = "lantern"'), encoding="utf-8")
            if is_ent:
                _sign_owner_approval(drift_bin, cfg_p, c_p, sig_dir, ssh_key)
                subprocess.run([str(drift_bin), "mutants", str(c_dir), "--when", "--out", str(mut_file)], check=True, capture_output=True)
            else:
                subprocess.run([str(drift_bin), "approve", str(c_p), "--by", "items-team"], check=True, capture_output=True)
            subprocess.run([str(drift_bin), "show", str(c_dir), "--out", str(res_dir)], check=True, capture_output=True)
            _run_code(_genuine_test_code(fixed=True, sut_name="lantern"))
        elif scenario_id == "P02-genuine-fix-escaped-obs":
            runner_kind = "parser_regression"
            lines = [
                json.dumps({"test": "t.py#found", "contract": "item-get", "cases": ["found"], "read": ["found"], "level": "http", "outcome": "passed", "digest": dig, "schema": "0.3", "capabilities": [], "observations": {"found": {"schema": "drift.observation/1", "payload": {"status": 200, "name": "lamp", "trace": ESCAPED_DEEP_NAME}}}}),
                json.dumps({"test": "t.py#not_found", "contract": "item-get", "cases": ["not-found"], "read": ["not-found"], "level": "http", "outcome": "passed", "digest": dig, "schema": "0.3", "capabilities": []}),
            ]
            ev_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
            (ev_dir / "py.meta.json").write_text('{"version":1,"classes":["t.py"],"tests":["t.py#found","t.py#not_found"]}\n', encoding="utf-8")
            if is_ent:
                _run_py_bridge(
                    bridge_dir, res_dir, ev_dir / "py-mut-discard.jsonl", _genuine_test_code(fixed=True),
                    extra_env={"DRIFT_MUTANTS": str(mut_file), "DRIFT_MUTATION_EVENTS": str(mut_dir / "py.mut.jsonl")},
                )
        elif scenario_id == "P04-genuine-fix-rerun-superseded":
            _run_py_bridge(
                bridge_dir,
                res_dir,
                ev_file,
                _test_snippet(
                    "try: drift.run_drift_case('item-get', 't.py#found', ['found'], lambda d: d.check('found', sut(d.when('found', 'request'), False)), 'http')\n"
                    "except AssertionError: pass\n"
                ),
            )
            _run_code(_genuine_test_code(fixed=True))
        elif scenario_id == "P05-genuine-fix-parallel-shards":
            shard_a = _test_snippet(
                "drift.run_drift_case('item-get', 'sa.py#found', ['found'], lambda d: d.check('found', sut(d.when('found', 'request'), True)), 'http')\n"
            )
            shard_b = _test_snippet(
                "drift.run_drift_case('item-get', 'sb.py#not_found', ['not-found'], lambda d: d.check('not-found', sut(d.when('not-found', 'request'), True)), 'http')\n"
            )
            _run_code(shard_a, target_ev=ev_dir / "shard_a.jsonl")
            _run_code(shard_b, target_ev=ev_dir / "shard_b.jsonl")
        elif scenario_id == "P08-genuine-fix-callback-assertion":
            code = _test_snippet(
                "def _chk_found(d):\n"
                "    res = sut(d.when('found', 'request'), True)\n"
                "    d.check('found', {'status': lambda e: res.get('status') == e, 'name': lambda e: res.get('name') == e})\n"
                "def _chk_nf(d):\n"
                "    res = sut(d.when('not-found', 'request'), True)\n"
                "    d.check('not-found', {'status': lambda e: res.get('status') == e, 'error': lambda e: res.get('error') == e})\n"
                "drift.run_drift_case('item-get', 't.py#found', ['found'], _chk_found, 'http')\n"
                "drift.run_drift_case('item-get', 't.py#not_found', ['not-found'], _chk_nf, 'http')\n"
            )
            _run_code(code)

        ok, doc = _run_gate(drift_bin, c_dir, cfg_p, ev_dir, edition=gate_edition, extra_args=extra_gate)
        out: dict[str, Any] = {
            "green": ok,
            "execution_error": bool(doc.get("execution_error", False)),
            "reasons": doc.get("reasons", []),
            "runner_kind": runner_kind,
        }
        if not is_ent:
            v_ok, v_doc = _run_verifier(verifier_py, c_dir, cfg_p, ev_dir)
            if v_doc.get("execution_error"):
                out["execution_error"] = True
                out["verifier_parity"] = False
            elif out["execution_error"]:
                out["verifier_parity"] = False
            else:
                out["verifier_parity"] = (ok == v_ok)
        if doc.get("triage"):
            out["triage_classes"] = sorted({t.get("class", "") for t in doc["triage"] if isinstance(t, dict)})
        return out
    except Exception as exc:
        return {
            "green": None,
            "execution_error": True,
            "reasons": [f"exec.error:{type(exc).__name__}"],
            "error": str(exc),
        }
    finally:
        if saved_modes:
            _unlock_paths(saved_modes)


def run_benchmark(
    drift_bin: Path,
    *,
    edition: str = "auto",
    max_workers: int | None = None,
) -> dict[str, Any]:
    if max_workers is None:
        max_workers = 1 if os.environ.get("DRIFT_CI") == "1" else 4
    bridge_dir = _find_bridge_py()
    verifier_py = _find_verifier_py()
    detected = detect_edition(drift_bin)
    effective_edition = detected if edition == "auto" else edition
    if edition == "enterprise" and detected != "enterprise":
        raise RuntimeError(f"requested --edition enterprise, but {drift_bin} reports edition '{detected}'")

    with tempfile.TemporaryDirectory(prefix="drift-redteam-bench-") as td:
        tp = Path(td)
        ssh_key = tp / "owner_ed25519"
        trust_root = tp / "allowed_signers"
        if effective_edition == "enterprise":
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(ssh_key)], check=True)
            pub = Path(f"{ssh_key}.pub").read_text(encoding="utf-8").strip()
            trust_root.write_text(f'owner:items-team namespaces="drift-signature@v1" {pub}\n', encoding="utf-8")

        jobs = [(sid, m) for sid, _, _ in ATTACK_SPECS for m in ALL_MODES]
        out_map: dict[tuple[str, str], dict[str, Any]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, max_workers)) as ex:
            fut_map = {
                ex.submit(
                    _execute_scenario,
                    sid,
                    drift_bin,
                    bridge_dir,
                    verifier_py,
                    mode=m,
                    root_tmp=tp,
                    ssh_key=ssh_key,
                    trust_root=trust_root,
                    effective_edition=effective_edition,
                ): (sid, m)
                for sid, m in jobs
            }
            for fut in concurrent.futures.as_completed(fut_map):
                out_map[fut_map[fut]] = fut.result()

        results: dict[str, dict[str, Any]] = {}
        for sid, desc, sut_fixed in ATTACK_SPECS:
            results[sid] = {
                "description": desc,
                "sut_fixed": sut_fixed,
                "modes": {m: out_map[(sid, m)] for m in ALL_MODES},
            }

    rep = summarize_results(results, ALL_MODES)
    rep["edition"] = effective_edition
    return rep


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="redteam_false_green_bench.py")
    default_drift = ROOT_DIR / ".build" / "drift"
    if not default_drift.is_file():
        on_path = shutil.which("drift")
        if on_path:
            default_drift = Path(on_path)
    p.add_argument("--drift", type=Path, default=default_drift)
    p.add_argument("--edition", choices=("auto", "free", "enterprise"), default="auto")
    p.add_argument("--as", dest="fmt", choices=("md", "json"), default="md")
    a = p.parse_args(argv)
    if not a.drift.is_file():
        print(f"redteam_false_green_bench: missing drift binary at {a.drift}", file=sys.stderr)
        return 2
    try:
        rep = run_benchmark(a.drift, edition=a.edition)
    except RuntimeError as exc:
        print(f"redteam_false_green_bench: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(rep, indent=2, sort_keys=True) if a.fmt == "json" else render_markdown(rep))
    return 0 if rep.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
