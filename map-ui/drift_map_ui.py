#!/usr/bin/env python3
"""Isolated zero-approval offline loopback explorer for DRIFT flow maps."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import http.cookies
import json
import os
import platform
import re
import secrets
import shlex
import shutil
import stat
import subprocess
import sys
import threading
import urllib.parse
import urllib.request


def sanitize_text(val) -> str:
    if val is None:
        return ""
    s = str(val)
    out = []
    for ch in s:
        cp = ord(ch)
        if ch in ("\n", "\t"):
            out.append(" ")
            continue
        if cp < 0x20 or (0x7F <= cp <= 0x9F):
            continue
        if cp in (0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2028, 0x2029, 0xFEFF):
            continue
        if (0x202A <= cp <= 0x202E) or (0x2060 <= cp <= 0x206F) or (0xE0000 <= cp <= 0xE007F):
            continue
        out.append(ch)
    return "".join(out)


def verify_runtime_root() -> Path:
    uid = os.getuid() if hasattr(os, "getuid") else 0
    base_str = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
    base = Path(base_str)
    if base.is_symlink():
        raise RuntimeError("runtime base directory must not be a symlink")
    root = base / f"drift-map-ui-{uid}"
    if root.exists() or root.is_symlink():
        st = os.lstat(root)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise RuntimeError("runtime directory must be a real directory")
        if hasattr(os, "getuid") and st.st_uid != uid:
            raise RuntimeError("runtime directory owned by unexpected user")
        os.chmod(root, 0o700)
    else:
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(root, 0o700)
    st2 = os.lstat(root)
    if stat.S_ISLNK(st2.st_mode) or (st2.st_mode & 0o077) != 0:
        raise RuntimeError("runtime directory failed 0700 verification")
    return root


def resolve_drift_cli(here: Path) -> str:
    env_cli = os.environ.get("DRIFT_CLI", "").strip()
    candidates = [
        env_cli,
        str(here / "drift"),
        str(here.parent / "bin" / "drift"),
        str(here.parent.parent / "bin" / "drift"),
        str(here.parent.parent / ".build" / "drift"),
        str(Path.home() / ".local" / "bin" / "drift"),
        shutil.which("drift") or "",
    ]
    for cand in candidates:
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    raise RuntimeError("cannot locate executable drift CLI")


def probe_desktop() -> tuple[bool, str]:
    if os.environ.get("DRIFT_UI", "").strip().lower() == "off":
        return False, "drift_ui_off"
    if os.environ.get("CI", "").lower() in ("1", "true") or os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        return False, "ci_environment"
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return False, "ssh_session"
    sys_name = platform.system()
    if sys_name == "Darwin" or sys_name == "Windows":
        return True, sys_name.lower()
    if Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists() or os.environ.get("WSL_INTEROP"):
        return True, "wsl"
    if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"):
        return True, "x11_wayland"
    return False, "no_display"


def open_browser(url: str) -> bool:
    sys_name = platform.system()
    if sys_name == "Darwin":
        cmd = ["open", url]
    elif Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists() or os.environ.get("WSL_INTEROP"):
        for wb in (
            "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
            "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
            "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe",
        ):
            if os.access(wb, os.X_OK):
                subprocess.Popen([wb, f"--app={url}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
        cmd = ["cmd.exe", "/c", "start", "", url]
    elif sys_name == "Windows":
        cmd = ["cmd", "/c", "start", "", url]
    else:
        opener = shutil.which("xdg-open")
        if not opener:
            return False
        cmd = [opener, url]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


class MapSession:
    def __init__(self, drift_bin: str, cwd: str, base_args: argparse.Namespace, html_path: Path):
        self.drift_bin = drift_bin
        self.cwd = cwd
        self.target = base_args.target
        self.default_view = base_args.view or ("flow" if os.path.isdir(base_args.target) else "cases")
        self.default_focus = list(base_args.focus or [])
        self.default_depth = base_args.depth
        self.default_max_nodes = base_args.max_nodes
        self.with_flow = bool(base_args.flow)
        self.what_ifs = list(base_args.what_if or [])
        self.profiles = base_args.profiles or ""
        self.html_template = html_path.read_text(encoding="utf-8")
        self.boot_secret = secrets.token_urlsafe(24)
        self.boot_consumed = False
        self.session_id = secrets.token_urlsafe(24)
        self.csrf_token = secrets.token_urlsafe(24)
        self.nonce = secrets.token_urlsafe(16)
        self.lock = threading.Lock()
        self.done_event = threading.Event()
        self.exit_code = 1
        self.stdout_bytes = b""

    def set_terminal(self, code: int, out_bytes: bytes = b"") -> None:
        with self.lock:
            if self.done_event.is_set():
                return
            self.exit_code = code
            self.stdout_bytes = out_bytes
            self.done_event.set()

    def build_map_argv(self, fmt: str, view: str = "", focus: list[str] | None = None, depth: int | None = None, max_nodes: int | None = None, skip: int = 0) -> list[str]:
        v = view or self.default_view
        argv = [self.drift_bin, "map", self.target, "--view", v, "--as", fmt]
        for f in (focus if focus is not None else self.default_focus):
            if f:
                argv.extend(["--focus", f])
        d = self.default_depth if depth is None else depth
        if v == "flow" and d is not None:
            argv.extend(["--depth", str(d)])
        mn = self.default_max_nodes if max_nodes is None else max_nodes
        if mn is not None:
            argv.extend(["--max-nodes", str(mn)])
        if skip > 0:
            argv.extend(["--skip", str(skip)])
        if self.with_flow and v == "flow":
            argv.append("--flow")
        for wf in self.what_ifs:
            argv.extend(["--what-if", wf])
        if self.profiles:
            argv.extend(["--profiles", self.profiles])
        return argv

    def run_cli(self, argv: list[str]) -> tuple[int, bytes, str]:
        env = {**os.environ, "DRIFT_NO_OPS_LOG": "1"}
        proc = subprocess.run(argv, cwd=self.cwd, env=env, capture_output=True)
        return proc.returncode, proc.stdout, proc.stderr.decode("utf-8", errors="replace")


def start_server(sess: MapSession) -> tuple[ThreadingHTTPServer, int, str]:
    cookie_box = {"name": ""}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def expected_host(self) -> str:
            return f"127.0.0.1:{self.server.server_port}"

        def check_host(self) -> bool:
            host = (self.headers.get("Host") or "").strip()
            return host == self.expected_host()

        def check_session(self) -> bool:
            raw_cookie = self.headers.get("Cookie") or ""
            jar = http.cookies.SimpleCookie()
            try:
                jar.load(raw_cookie)
            except http.cookies.CookieError:
                return False
            morsel = jar.get(cookie_box["name"])
            return morsel is not None and secrets.compare_digest(morsel.value, sess.session_id)

        def check_csrf(self) -> bool:
            tok = (self.headers.get("X-Drift-Map-CSRF") or "").strip()
            return bool(tok) and secrets.compare_digest(tok, sess.csrf_token)

        def send_common_headers(self, status: int, content_type: str, extra: dict[str, str] | None = None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                f"default-src 'none'; script-src 'nonce-{sess.nonce}'; style-src 'nonce-{sess.nonce}'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'",
            )
            if extra:
                for k, v in extra.items():
                    self.send_header(k, v)
            self.end_headers()

        def send_json_bytes(self, status: int, payload: bytes):
            self.send_common_headers(status, "application/json; charset=utf-8")
            self.wfile.write(payload)

        def send_json(self, status: int, obj: dict):
            self.send_json_bytes(status, json.dumps(obj, sort_keys=True).encode("utf-8"))

        def read_json_body(self) -> dict | None:
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                return None
            if length < 0 or length > 262144:
                return None
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                data = json.loads(raw.decode("utf-8"))
                return data if isinstance(data, dict) else None
            except Exception:
                return None

        def do_GET(self):
            if not self.check_host():
                self.send_json(403, {"error": "forbidden_host"})
                return
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/api/gesture":
                self.send_json(404, {"error": "not_found"})
                return
            if parsed.path == "/":
                qs = urllib.parse.parse_qs(parsed.query)
                boot = (qs.get("boot") or [""])[0]
                if boot:
                    with sess.lock:
                        if sess.boot_consumed or not secrets.compare_digest(boot, sess.boot_secret):
                            self.send_json(403, {"error": "invalid_or_replayed_boot"})
                            return
                        sess.boot_consumed = True
                    html = (
                        sess.html_template.replace("__NONCE__", sess.nonce)
                        .replace("__CSRF__", sess.csrf_token)
                        .replace("__DEFAULT_VIEW__", sanitize_text(sess.default_view))
                    ).encode("utf-8")
                    self.send_common_headers(
                        200,
                        "text/html; charset=utf-8",
                        {"Set-Cookie": f"{cookie_box['name']}={sess.session_id}; HttpOnly; SameSite=Strict; Path=/"},
                    )
                    self.wfile.write(html)
                    return
                if not self.check_session():
                    self.send_json(403, {"error": "unauthenticated"})
                    return
                html = (
                    sess.html_template.replace("__NONCE__", sess.nonce)
                    .replace("__CSRF__", sess.csrf_token)
                    .replace("__DEFAULT_VIEW__", sanitize_text(sess.default_view))
                ).encode("utf-8")
                self.send_common_headers(200, "text/html; charset=utf-8")
                self.wfile.write(html)
                return

            if not self.check_session():
                self.send_json(403, {"error": "unauthenticated"})
                return
            qs = urllib.parse.parse_qs(parsed.query)
            view = (qs.get("view") or [sess.default_view])[0]
            focus = [x for x in qs.get("focus", []) if x]
            depth = int((qs.get("depth") or [str(sess.default_depth)])[0])
            max_nodes = int((qs.get("max_nodes") or [str(sess.default_max_nodes)])[0])
            skip = int((qs.get("skip") or ["0"])[0])
            if parsed.path == "/api/view":
                rc, out, err = sess.run_cli(sess.build_map_argv("json", view, focus, depth, max_nodes, skip))
                if rc != 0:
                    self.send_json(400, {"error": sanitize_text(err.strip())})
                    return
                self.send_json_bytes(200, out)
                return
            if parsed.path == "/api/mermaid":
                rc, out, err = sess.run_cli(sess.build_map_argv("mermaid", view, focus, depth, max_nodes, skip))
                if rc != 0:
                    self.send_json(400, {"error": sanitize_text(err.strip())})
                    return
                self.send_common_headers(200, "text/plain; charset=utf-8")
                self.wfile.write(out)
                return
            self.send_json(404, {"error": "not_found"})

        def do_POST(self):
            if not self.check_host():
                self.send_json(403, {"error": "forbidden_host"})
                return
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == "/api/gesture":
                self.send_json(404, {"error": "not_found"})
                return
            if not self.check_session() or not self.check_csrf():
                self.send_json(403, {"error": "unauthenticated_or_csrf"})
                return
            body = self.read_json_body()
            if body is None:
                self.send_json(400, {"error": "invalid_json"})
                return
            if parsed.path == "/api/closed":
                self.send_json(200, {"status": "closed"})
                sess.set_terminal(1, b"")
                return
            if parsed.path == "/api/walk":
                from_ep = sanitize_text(body.get("from") or "").strip()
                if not from_ep:
                    self.send_json(400, {"error": "from is required"})
                    return
                fmt = "mermaid" if body.get("format") == "mermaid" else "json"
                argv = [sess.drift_bin, "map", "walk", sess.target, "--from", from_ep, "--as", fmt]
                for v in body.get("via") or []:
                    vs = sanitize_text(v).strip()
                    if vs:
                        argv.extend(["--via", vs])
                mh = body.get("max_hops")
                if isinstance(mh, int) and 1 <= mh <= 32:
                    argv.extend(["--max-hops", str(mh)])
                for wf in sess.what_ifs:
                    argv.extend(["--what-if", wf])
                if sess.profiles:
                    argv.extend(["--profiles", sess.profiles])
                rc, out, err = sess.run_cli(argv)
                if rc != 0:
                    self.send_json(400, {"error": sanitize_text(err.strip())})
                    return
                if fmt == "mermaid":
                    self.send_common_headers(200, "text/plain; charset=utf-8")
                    self.wfile.write(out)
                else:
                    self.send_json_bytes(200, out)
                return
            if parsed.path == "/api/focus":
                handles = [sanitize_text(h).strip() for h in (body.get("handles") or []) if sanitize_text(h).strip()]
                if not handles:
                    self.send_json(400, {"error": "at least one handle is required"})
                    return
                view = sanitize_text(body.get("view") or sess.default_view).strip()
                map_ref = sanitize_text(body.get("map_ref") or "").strip()
                question = sanitize_text(body.get("question") or "").strip()
                argv = [sess.drift_bin, "map", "focus", sess.target, *handles, "--view", view, "--as", "json"]
                if map_ref:
                    argv.extend(["--map", map_ref])
                if question:
                    argv.extend(["--question", question])
                for wf in sess.what_ifs:
                    argv.extend(["--what-if", wf])
                if sess.profiles:
                    argv.extend(["--profiles", sess.profiles])
                rc, out, err = sess.run_cli(argv)
                if rc != 0:
                    self.send_json(400, {"error": sanitize_text(err.strip())})
                    return
                self.send_json(200, {"status": "submitted"})
                sess.set_terminal(0, out)
                return
            self.send_json(404, {"error": "not_found"})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_address[1]
    cookie_box["name"] = f"drift_map_sid_{port}"
    return srv, port, cookie_box["name"]


def http_req(url: str, method: str = "GET", headers: dict[str, str] | None = None, body: bytes | None = None) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers.items()), e.read()


def page_offline_clean(page: str, nonce: str) -> bool:
    """The served explorer must run under the strict nonce CSP with zero external requests."""
    if any(tok in page for tok in ("__NONCE__", "__CSRF__", "__DEFAULT_VIEW__")):
        return False
    blocks = re.findall(r"<(?:script|style)\b([^>]*)>", page, flags=re.I)
    if not blocks or any(f'nonce="{nonce}"' not in attrs or re.search(r"\bsrc\s*=", attrs, flags=re.I) for attrs in blocks):
        return False
    markup = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", page, flags=re.I | re.S)
    if re.search(r"<[^>]*\s(?:on[a-z]+|style)\s*=", markup, flags=re.I):
        return False
    if re.search(r"\b(?:src|href)\s*=\s*[\"']?\s*(?:https?:)?//", markup, flags=re.I):
        return False
    return not re.search(
        r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\s*\(|@import|url\(\s*[\"']?(?:https?:)?//",
        page,
    )


def run_self_test(sess: MapSession) -> int:
    srv, port, cookie_name = start_server(sess)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        st_host, _, _ = http_req(f"{base}/?boot={sess.boot_secret}", headers={"Host": "evil.example"})
        st_unauth, _, _ = http_req(f"{base}/api/view")
        st_gest, _, _ = http_req(f"{base}/api/gesture", method="POST", body=b"{}")
        st_boot, hdrs, page_raw = http_req(f"{base}/?boot={sess.boot_secret}")
        set_cookie = hdrs.get("Set-Cookie") or hdrs.get("set-cookie") or ""
        csp = hdrs.get("Content-Security-Policy") or hdrs.get("content-security-policy") or ""
        st_replay, _, _ = http_req(f"{base}/?boot={sess.boot_secret}")
        cookie_hdr = f"{cookie_name}={sess.session_id}"
        st_view, _, view_raw = http_req(f"{base}/api/view", headers={"Cookie": cookie_hdr})
        st_mmd, _, mmd_raw = http_req(f"{base}/api/mermaid", headers={"Cookie": cookie_hdr})
        view_doc = json.loads(view_raw.decode("utf-8"))
        first_h = view_doc["nodes"][0]["h"]
        map_ref = view_doc["map_ref"]
        focus_body = json.dumps({"handles": [first_h], "map_ref": map_ref, "view": sess.default_view}).encode("utf-8")
        st_foc, _, _ = http_req(
            f"{base}/api/focus",
            method="POST",
            headers={"Cookie": cookie_hdr, "X-Drift-Map-CSRF": sess.csrf_token, "Content-Type": "application/json"},
            body=focus_body,
        )
        sess.done_event.wait(timeout=5)
        cli_rc, cli_focus_raw, _ = sess.run_cli([
            sess.drift_bin, "map", "focus", sess.target, first_h, "--view", sess.default_view, "--map", map_ref, "--as", "json"
        ])
        csp_ok = "default-src 'none'" in csp and "connect-src 'self'" in csp and "cdn" not in csp.lower()
        report = {
            "cookie_port_scoped": cookie_name in set_cookie and str(port) in cookie_name,
            "csp_offline_exact": csp_ok,
            "gesture_endpoint_status": st_gest,
            "mermaid_ok": st_mmd == 200 and len(mmd_raw) > 0,
            "page_offline_clean": page_offline_clean(page_raw.decode("utf-8", errors="replace"), sess.nonce),
            "replay_boot_status": st_replay,
            "spoofed_host_status": st_host,
            "stdout_matches_cli_focus": cli_rc == 0 and sess.stdout_bytes == cli_focus_raw and st_foc == 200,
            "unauth_status": st_unauth,
            "view_ok": st_view == 200 and st_boot == 200,
        }
        print(json.dumps(report, sort_keys=True))
        ok = (
            st_host == 403
            and st_unauth == 403
            and st_replay == 403
            and st_gest == 404
            and report["cookie_port_scoped"]
            and report["csp_offline_exact"]
            and report["view_ok"]
            and report["mermaid_ok"]
            and report["page_offline_clean"]
            and report["stdout_matches_cli_focus"]
        )
        return 0 if ok else 1
    finally:
        srv.shutdown()
        srv.server_close()


def main() -> int:
    ap = argparse.ArgumentParser(prog="drift-map-ui")
    ap.add_argument("--launcher-dir", required=True)
    ap.add_argument("target", nargs="?", default=".drift/contracts")
    ap.add_argument("--view", default="")
    ap.add_argument("--focus", action="append", default=[])
    ap.add_argument("--depth", type=int, default=1)
    ap.add_argument("--max-nodes", type=int, default=40)
    ap.add_argument("--flow", action="store_true")
    ap.add_argument("--what-if", action="append", default=[])
    ap.add_argument("--profiles", default="")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    here = Path(args.launcher_dir).resolve()
    script_dir = Path(__file__).resolve().parent
    html_path = script_dir / "drift_map_ui.html"
    if not html_path.is_file():
        html_path = here / "drift_map_ui.html"
    if not html_path.is_file():
        print("drift-map-ui: missing drift_map_ui.html", file=sys.stderr)
        return 2

    try:
        drift_bin = resolve_drift_cli(here)
        _ = verify_runtime_root()
    except Exception as exc:
        print(f"drift-map-ui: {exc}", file=sys.stderr)
        return 2

    if not os.path.exists(args.target):
        print(f"drift-map-ui: target not found: {args.target}", file=sys.stderr)
        return 2

    if args.target.endswith(".json"):
        print("drift-map-ui: expects a contract file or area directory, not pre-rendered JSON", file=sys.stderr)
        return 2

    sess = MapSession(drift_bin, os.getcwd(), args, html_path)
    if args.self_test:
        return run_self_test(sess)

    desktop_ok, reason = probe_desktop()
    if not desktop_ok:
        mermaid_cmd = " ".join(shlex.quote(x) for x in ["drift", *sess.build_map_argv("mermaid")[1:]])
        print(f"drift-map-ui: fallback ({reason}); run: {mermaid_cmd}", file=sys.stderr)
        return 10

    srv, port, _ = start_server(sess)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        url = f"http://127.0.0.1:{port}/?boot={sess.boot_secret}"
        if not open_browser(url):
            mermaid_cmd = " ".join(shlex.quote(x) for x in ["drift", *sess.build_map_argv("mermaid")[1:]])
            print(f"drift-map-ui: fallback (browser_unavailable); run: {mermaid_cmd}", file=sys.stderr)
            return 10
        finished = sess.done_event.wait(timeout=max(5, args.timeout))
        if not finished:
            mermaid_cmd = " ".join(shlex.quote(x) for x in ["drift", *sess.build_map_argv("mermaid")[1:]])
            print(f"drift-map-ui: fallback (timeout); run: {mermaid_cmd}", file=sys.stderr)
            return 10
        if sess.exit_code == 0 and sess.stdout_bytes:
            sys.stdout.buffer.write(sess.stdout_bytes)
            sys.stdout.buffer.flush()
        return sess.exit_code
    finally:
        srv.shutdown()
        srv.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
