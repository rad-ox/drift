#!/usr/bin/env python3
"""Fixtures, live unittest runners, read-only perimeter helpers, and Markdown renderer for DRIFT red-team benchmark (MIT License)."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

ALL_MODES = (
    "baseline-unit-tests",
    "isolated-unit-tests-no-drift",
    "drift-free-verified",
    "drift-enterprise-hardened",
    "drift-isolated-ci",
)

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

ESCAPED_DEEP_NAME = '"' + "[" * 65

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
    ("P01-genuine-fix", "Positive control: SUT bug is genuinely fixed and tested live via bridge", True),
    ("P02-genuine-fix-escaped-obs", "Positive control [parser-regression]: escaped-quote + 65 '[' observation JSONL", True),
    ("P03-genuine-fix-bridge-escaped-obs", "Positive control: live bridge auto-emits escaped-quote + 65 '[' observation", True),
    ("P04-genuine-fix-rerun-superseded", "Positive control: failing bridge run superseded by passing rerun after fix", True),
    ("P05-genuine-fix-parallel-shards", "Positive control: two independent bridge shards covering found and not-found", True),
    ("P06-genuine-fix-approved-contract-update", "Positive control: owner-approved contract update with matching SUT fix", True),
    ("P07-genuine-fix-refactor-behavior-unchanged", "Positive control: internal SUT refactor preserving contract outputs", True),
    ("P08-genuine-fix-callback-assertion", "Positive control: valid parameter-inspecting predicate callbacks in d.check", True),
]


def _config_toml(proof: str, require_signed: bool = False) -> str:
    extra = "\nrequire_signed_approval = true" if require_signed else ""
    return (
        'drift = "0.3"\nkind = "config"\n\n[area]\nowner = "items-team"\n\n'
        f'[policy]\npack = "core@1"\napprovers = ["items-team"]\nproof = "{proof}"{extra}\n'
    )


def _lock_readonly(paths: list[Path]) -> list[tuple[Path, int]]:
    """Apply OS read-only modes (0o444 on files, 0o555 on dirs) bottom-up and return restore list."""
    saved: list[tuple[Path, int]] = []
    all_nodes: list[Path] = []
    for root in paths:
        if not root.exists():
            continue
        if root.is_dir():
            for cur, _, files in os.walk(root):
                cp = Path(cur)
                for fn in files:
                    all_nodes.append(cp / fn)
                all_nodes.append(cp)
        else:
            all_nodes.append(root)
    files_list = [p for p in all_nodes if p.is_file()]
    dirs_list = sorted({p for p in all_nodes if p.is_dir()}, key=lambda p: len(p.parts), reverse=True)
    for p in files_list:
        saved.append((p, stat.S_IMODE(p.stat().st_mode)))
        p.chmod(0o444)
    for p in dirs_list:
        saved.append((p, stat.S_IMODE(p.stat().st_mode)))
        p.chmod(0o555)
    return saved


def _unlock_paths(saved: list[tuple[Path, int]]) -> None:
    """Restore original modes top-down so directories become writable before child files."""
    dirs_first = sorted(saved, key=lambda pair: (0 if pair[0].is_dir() else 1, len(pair[0].parts)))
    for p, mode in dirs_first:
        try:
            if p.exists():
                p.chmod(mode | 0o200)
        except OSError:
            pass


def _attempt_perimeter_write(target: Path, payload: str) -> bool:
    """Attempt an adversarial write to a protected path; return True iff write was denied."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        if target.exists() and not (stat.S_IMODE(target.stat().st_mode) & stat.S_IWUSR):
            return True
    try:
        with open(target, "w", encoding="utf-8") as fh:
            fh.write(payload)
        return False
    except PermissionError:
        return True


def _test_snippet(body: str, *, sut_name: str = "lamp", refactored: bool = False) -> str:
    if refactored:
        sut_def = (
            f"_ITEMS = {{'1': {{'status': 200, 'name': {sut_name!r}}}}}\n"
            "def sut(req, fixed=False):\n"
            "    i = req.rsplit('/', 1)[-1]\n"
            "    if i == '1' and not fixed: return {'status': 500, 'name': 'broken'}\n"
            "    return dict(_ITEMS.get(i, {'status': 404, 'error': 'item not found'}))\n"
        )
    else:
        sut_def = (
            "def sut(req, fixed=False):\n"
            "    i = req.rsplit('/', 1)[-1]\n"
            f"    if i == '1': return {{'status': 200, 'name': {sut_name!r}}} if fixed else {{'status': 500, 'name': 'broken'}}\n"
            "    return {'status': 404, 'error': 'item not found'}\n"
        )
    return "import drift\n" + sut_def + body


def _genuine_test_code(fixed: bool, *, sut_name: str = "lamp", refactored: bool = False) -> str:
    return _test_snippet(
        f"FIXED = {fixed!r}\n"
        "drift.run_drift_case('item-get', 't.py#found', ['found'], lambda d: d.check('found', sut(d.when('found', 'request'), FIXED)), 'http')\n"
        "drift.run_drift_case('item-get', 't.py#not_found', ['not-found'], lambda d: d.check('not-found', sut(d.when('not-found', 'request'), FIXED)), 'http')\n",
        sut_name=sut_name,
        refactored=refactored,
    )


def _sut_module_source(fixed: bool, *, sut_name: str = "lamp", refactored: bool = False) -> str:
    if refactored:
        return (
            f"ITEMS = {{'1': {{'status': 200, 'name': {sut_name!r}}}}}\n"
            f"FIXED = {fixed!r}\n"
            "def handle(req):\n"
            "    item_id = req.rsplit('/', 1)[-1]\n"
            "    if item_id == '1' and not FIXED:\n"
            "        return {'status': 500, 'name': 'broken'}\n"
            "    return dict(ITEMS.get(item_id, {'status': 404, 'error': 'item not found'}))\n"
        )
    return (
        f"FIXED = {fixed!r}\n"
        "def handle(req):\n"
        "    item_id = req.rsplit('/', 1)[-1]\n"
        "    if item_id == '1':\n"
        f"        return {{'status': 200, 'name': {sut_name!r}}} if FIXED else {{'status': 500, 'name': 'broken'}}\n"
        "    return {'status': 404, 'error': 'item not found'}\n"
    )


def _strict_unittest_source(expected_name: str = "lamp") -> str:
    return (
        "import unittest\nimport sut\n\n"
        "class ItemTests(unittest.TestCase):\n"
        "    def test_found(self):\n"
        "        res = sut.handle('GET /items/1')\n"
        "        self.assertEqual(res['status'], 200)\n"
        f"        self.assertEqual(res['name'], {expected_name!r})\n\n"
        "    def test_not_found(self):\n"
        "        res = sut.handle('GET /items/999')\n"
        "        self.assertEqual(res['status'], 404)\n"
        "        self.assertEqual(res['error'], 'item not found')\n"
    )


def _weakened_unittest_source(scenario_id: str) -> str:
    """Return concrete weakened unittest code an adversary writes when tests are editable."""
    if scenario_id in ("A01-contract-edit-unapproved", "A07-unlisted-approver-forgery", "A08-allowlisted-self-approval"):
        return (
            "import unittest\nimport sut\n"
            "class ItemTests(unittest.TestCase):\n"
            "    def test_found(self):\n"
            "        res = sut.handle('GET /items/1')\n"
            "        self.assertEqual(res['status'], 500)\n"
            "        self.assertEqual(res['name'], 'broken')\n"
            "    def test_not_found(self):\n"
            "        res = sut.handle('GET /items/999')\n"
            "        self.assertEqual(res['status'], 404)\n"
            "        self.assertEqual(res['error'], 'item not found')\n"
        )
    if scenario_id in ("A03-deleted-test-gone", "A14-overlapping-test-deleted"):
        return (
            "import unittest\nimport sut\n"
            "class ItemTests(unittest.TestCase):\n"
            "    def test_not_found(self):\n"
            "        res = sut.handle('GET /items/999')\n"
            "        self.assertEqual(res['status'], 404)\n"
            "        self.assertEqual(res['error'], 'item not found')\n"
        )
    if scenario_id in ("A04-partial-then-read", "A05-noop-callback", "A12-tautology-callback", "A13-read-without-assert"):
        return (
            "import unittest\nimport sut\n"
            "class ItemTests(unittest.TestCase):\n"
            "    def test_found(self):\n"
            "        _ = sut.handle('GET /items/1')\n"
            "        self.assertTrue(True)\n"
            "    def test_not_found(self):\n"
            "        res = sut.handle('GET /items/999')\n"
            "        self.assertEqual(res['status'], 404)\n"
        )
    return (
        "import unittest\n"
        "TABLE = {'GET /items/1': {'status': 200, 'name': 'lamp'}, 'GET /items/999': {'status': 404, 'error': 'item not found'}}\n"
        "class ItemTests(unittest.TestCase):\n"
        "    def test_found(self):\n"
        "        res = TABLE['GET /items/1']\n"
        "        self.assertEqual(res['status'], 200)\n"
        "        self.assertEqual(res['name'], 'lamp')\n"
        "    def test_not_found(self):\n"
        "        res = TABLE['GET /items/999']\n"
        "        self.assertEqual(res['status'], 404)\n"
        "        self.assertEqual(res['error'], 'item not found')\n"
    )


def _positive_fixture_params(scenario_id: str) -> tuple[str, bool, str]:
    """Return (expected_name, refactored_sut, contract_toml) for positive controls P01-P08."""
    if scenario_id == "P03-genuine-fix-bridge-escaped-obs":
        c_toml = CONTRACT_TOML.replace('then.name = "lamp"', f"then.name = {json.dumps(ESCAPED_DEEP_NAME)}")
        return ESCAPED_DEEP_NAME, False, c_toml
    if scenario_id == "P06-genuine-fix-approved-contract-update":
        c_toml = CONTRACT_TOML.replace('then.name = "lamp"', 'then.name = "lantern"')
        return "lantern", False, c_toml
    if scenario_id == "P07-genuine-fix-refactor-behavior-unchanged":
        return "lamp", True, CONTRACT_TOML
    return "lamp", False, CONTRACT_TOML


def _run_unittest_mode(scenario_id: str, work: Path, *, isolated: bool) -> dict[str, Any]:
    """Execute live Python unittest suite for baseline-unit-tests or isolated-unit-tests-no-drift."""
    work.mkdir(parents=True, exist_ok=True)
    fixed = scenario_id.startswith("P")
    exp_name, refactored, _ = _positive_fixture_params(scenario_id) if fixed else ("lamp", False, CONTRACT_TOML)
    (work / "sut.py").write_text(_sut_module_source(fixed, sut_name=exp_name, refactored=refactored), encoding="utf-8")

    test_dir = work / "protected_tests" if isolated else work
    test_dir.mkdir(parents=True, exist_ok=True)
    test_file = test_dir / "test_items.py"
    test_file.write_text(_strict_unittest_source(exp_name), encoding="utf-8")

    saved_modes: list[tuple[Path, int]] = []
    write_denied: bool | None = None
    try:
        if isolated:
            saved_modes = _lock_readonly([test_dir])
            if not fixed:
                write_denied = _attempt_perimeter_write(test_file, _weakened_unittest_source(scenario_id))
                if not write_denied:
                    return {
                        "green": None,
                        "execution_error": True,
                        "live_runner": "unittest",
                        "write_denied": False,
                        "reasons": ["perimeter.write_not_denied"],
                    }
        else:
            if not fixed:
                test_file.write_text(_weakened_unittest_source(scenario_id), encoding="utf-8")

        env = {**os.environ, "PYTHONPATH": str(work)}
        proc = subprocess.run(
            [sys.executable, "-B", "-m", "unittest", "discover", "-s", str(test_dir), "-p", "test_*.py"],
            capture_output=True, text=True, env=env, check=False,
        )
        ok = proc.returncode == 0
        out: dict[str, Any] = {
            "green": ok,
            "execution_error": False,
            "live_runner": "unittest",
            "reasons": [] if ok else ["unittest.failed"],
        }
        if isolated:
            out["write_denied"] = True if not fixed else None
        return out
    finally:
        if saved_modes:
            _unlock_paths(saved_modes)


def _run_py_bridge(bridge_dir: Path, resolved_dir: Path, ev_file: Path, code: str, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(bridge_dir), "DRIFT_RESOLVED": str(resolved_dir), "DRIFT_EVENTS": str(ev_file), **(extra_env or {})}
    return subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, env=env, check=False)


def _run_py_bridge_file(bridge_dir: Path, resolved_dir: Path, ev_file: Path, script_path: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(bridge_dir), "DRIFT_RESOLVED": str(resolved_dir), "DRIFT_EVENTS": str(ev_file), **(extra_env or {})}
    return subprocess.run([sys.executable, "-B", str(script_path)], capture_output=True, text=True, env=env, check=False)


def _parse_verdict_stdout(res: subprocess.CompletedProcess[str], prefix: str) -> tuple[bool | None, dict[str, Any]]:
    if res.stdout.strip():
        try:
            contracts = json.loads(res.stdout).get("contracts")
            if isinstance(contracts, list) and contracts and isinstance(contracts[0], dict) and "ok" in contracts[0]:
                return bool(contracts[0]["ok"]), contracts[0]
        except Exception:
            pass
    return None, {"ok": None, "execution_error": True, "reasons": [f"{prefix}.rc_{res.returncode}"], "stderr": res.stderr.strip()}


def _run_gate(drift_bin: Path, contracts_dir: Path, cfg_path: Path, ev_dir: Path, *, edition: str = "free", extra_args: list[str] | None = None) -> tuple[bool | None, dict[str, Any]]:
    env = {**os.environ}
    if edition == "free":
        env["DRIFT_EDITION"] = "free"
    else:
        env.pop("DRIFT_EDITION", None)
    cmd = [str(drift_bin), "gate", str(contracts_dir), "--config", str(cfg_path), "--events", str(ev_dir), "--explain", "--json", *(extra_args or [])]
    return _parse_verdict_stdout(subprocess.run(cmd, capture_output=True, text=True, env=env, check=False), "cli")


def _run_verifier(verifier_py: Path, contracts_dir: Path, cfg_path: Path, ev_dir: Path, extra_args: list[str] | None = None) -> tuple[bool | None, dict[str, Any]]:
    cmd = [sys.executable, "-B", str(verifier_py), str(contracts_dir), "--config", str(cfg_path), "--events", str(ev_dir), "--json", *(extra_args or [])]
    return _parse_verdict_stdout(subprocess.run(cmd, capture_output=True, text=True, check=False), "verifier")


def _sign_owner_approval(drift_bin: Path, cfg_p: Path, c_p: Path, sig_dir: Path, ssh_key: Path) -> tuple[str, str]:
    subprocess.run([str(drift_bin), "approve", str(c_p), "--by", "items-team"], check=True, capture_output=True)
    cfg_chk = json.loads(subprocess.check_output([str(drift_bin), "check", str(cfg_p), "--json"], text=True))["files"][0]
    c_chk = json.loads(subprocess.check_output([str(drift_bin), "check", str(c_p), "--json"], text=True))["files"][0]
    dig, adig, pol_ref = c_chk["digest"], c_chk.get("assurance_digest") or "none", cfg_chk["digest"]
    payload = {
        "context_ref": adig, "meaning": "owner_approval", "policy_ref": pol_ref,
        "schema": "drift.signature-payload/1", "signed_at": "2026-11-20T09:00:00Z",
        "signer": "owner:items-team", "target_kind": "contract", "target_ref": dig,
    }
    sig_dir.mkdir(parents=True, exist_ok=True)
    tmp_p = sig_dir / "_payload.tmp"
    tmp_p.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    subprocess.run(["ssh-keygen", "-Y", "sign", "-q", "-f", str(ssh_key), "-n", "drift-signature@v1", str(tmp_p)], check=True)
    sig_txt = Path(f"{tmp_p}.sig").read_text(encoding="utf-8").strip()
    tmp_p.unlink(missing_ok=True)
    Path(f"{tmp_p}.sig").unlink(missing_ok=True)
    (sig_dir / "owner.sig.json").write_text(json.dumps({"payload": payload, "schema": "drift.signature-envelope/1", "signature": sig_txt}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return dig, adig


def _init_area(drift_bin: Path, base: Path, *, proof: str, require_signed: bool = False, ssh_key: Path | None = None, contract_toml: str = CONTRACT_TOML) -> tuple[Path, Path, Path, str, Path]:
    c_dir, p_dir, sig_dir = base / ".drift/contracts", base / ".drift/profiles", base / "sigs"
    c_dir.mkdir(parents=True)
    p_dir.mkdir(parents=True)
    (p_dir / "http-json@1.toml").write_text(PROFILE_TOML, encoding="utf-8")
    cfg_p = base / ".drift/config.toml"
    cfg_p.write_text(_config_toml(proof, require_signed=require_signed), encoding="utf-8")
    c_p = c_dir / "item-get.toml"
    c_p.write_text(contract_toml, encoding="utf-8")
    subprocess.run([str(drift_bin), "approve", str(cfg_p), "--by", "items-team"], check=True, capture_output=True)
    if require_signed and ssh_key is not None:
        dig, _ = _sign_owner_approval(drift_bin, cfg_p, c_p, sig_dir, ssh_key)
    else:
        subprocess.run([str(drift_bin), "approve", str(c_p), "--by", "items-team"], check=True, capture_output=True)
        dig = json.loads(subprocess.check_output([str(drift_bin), "check", str(c_p), "--json"], text=True))["files"][0]["digest"]
    res_dir = base / "resolved"
    res_dir.mkdir()
    subprocess.run([str(drift_bin), "show", str(c_dir), "--out", str(res_dir)], check=True, capture_output=True)
    return c_dir, cfg_p, res_dir, dig, sig_dir


def summarize_results(results: dict[str, dict[str, Any]], modes: tuple[str, ...] = ALL_MODES) -> dict[str, Any]:
    """Compute fail-closed summary metrics; CLI errors never count as blocked attacks."""
    summary: dict[str, Any] = {}
    attacks = [sid for sid, row in results.items() if not row["sut_fixed"]]
    controls = [sid for sid, row in results.items() if row["sut_fixed"]]
    all_ok = True

    for m in modes:
        cells = [results[sid]["modes"][m] for sid in results]
        if cells and all(c.get("status") == "skipped" for c in cells):
            reason = next((c.get("reasons", ["skipped"])[0] for c in cells if c.get("reasons")), "skipped")
            if reason == "edition.requires_enterprise":
                reason = "requires DRIFT Enterprise"
            summary[m] = {"status": "skipped", "reason": reason, "attacks_total": len(attacks), "controls_total": len(controls)}
            continue

        exec_errs = [sid for sid in results if results[sid]["modes"][m].get("execution_error")]
        par_bad = [sid for sid in results if results[sid]["modes"][m].get("verifier_parity") is False]
        blocked = [sid for sid in attacks if not results[sid]["modes"][m].get("execution_error") and results[sid]["modes"][m].get("green") is False]
        fg = [sid for sid in attacks if not results[sid]["modes"][m].get("execution_error") and results[sid]["modes"][m].get("green") is True]
        fr = [sid for sid in controls if not results[sid]["modes"][m].get("execution_error") and results[sid]["modes"][m].get("green") is False]
        denom_a, denom_c = (len(attacks) or 1), (len(controls) or 1)
        summary[m] = {
            "status": "ok" if (not exec_errs and not par_bad and not fr) else "failed",
            "attacks_total": len(attacks),
            "attacks_blocked": len(blocked),
            "false_greens": len(fg),
            "false_green_rate": round(len(fg) / denom_a, 4),
            "residual_false_green_ids": fg,
            "controls_total": len(controls),
            "false_reds": len(fr),
            "false_red_rate": round(len(fr) / denom_c, 4),
            "execution_errors": len(exec_errs),
            "execution_error_ids": exec_errs,
            "parity_mismatches": len(par_bad),
            "parity_mismatch_ids": par_bad,
        }
        if exec_errs or par_bad or fr:
            all_ok = False

    return {"ok": all_ok, "summary": summary, "scenarios": results}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# DRIFT Anti-False-Green Red-Team Benchmark",
        "",
        f"Edition: `{report.get('edition', 'unknown')}` · Integrity: `{'ok' if report.get('ok') else 'FAILED'}`",
        "",
        "| Configuration | Attacks Blocked | False Greens | False-Green Rate | False Reds | Errors / Parity | Residual False Greens |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for m, s in report["summary"].items():
        if s.get("status") == "skipped":
            lines.append(f"| `{m}` | skipped | skipped | n/a | skipped | 0 / 0 | {s.get('reason', 'skipped')} |")
            continue
        res_ids = ", ".join(s["residual_false_green_ids"]) or "none"
        lines.append(
            f"| `{m}` | {s['attacks_blocked']}/{s['attacks_total']} | {s['false_greens']}/{s['attacks_total']} | "
            f"{s['false_green_rate']*100:.1f}% | {s['false_reds']}/{s['controls_total']} | "
            f"{s['execution_errors']} / {s['parity_mismatches']} | {res_ids} |"
        )
    lines.extend([
        "",
        "## Per-Scenario Verdicts",
        "",
        "| Scenario | SUT Fixed | Baseline `unittest` | Isolated `unittest` (no DRIFT) | Free `verified` | Enterprise Hardened | Isolated CI (DRIFT) |",
        "|---|:---:|:---:|:---:|:---:|:---:|:---:|",
    ])
    for sid, row in report["scenarios"].items():
        ms = row["modes"]

        def _cell(m: str) -> str:
            d = ms[m]
            if d.get("status") == "skipped":
                return "SKIPPED"
            if d.get("execution_error"):
                return "ERROR"
            lbl = "GREEN" if d["green"] else "BLOCKED"
            if d.get("verifier_parity") is False:
                lbl += " (PARITY_MISMATCH)"
            if d.get("triage_classes"):
                lbl += f" ({','.join(d['triage_classes'])})"
            return lbl

        lines.append(
            f"| `{sid}` | {'yes' if row['sut_fixed'] else 'no'} | {_cell('baseline-unit-tests')} | "
            f"{_cell('isolated-unit-tests-no-drift')} | {_cell('drift-free-verified')} | "
            f"{_cell('drift-enterprise-hardened')} | {_cell('drift-isolated-ci')} |"
        )
    return "\n".join(lines) + "\n"
