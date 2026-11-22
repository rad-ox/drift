#!/usr/bin/env python3
"""Universal loopback Observatory Deck gesture renderer for macOS, Linux Desktop, and fallback."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import base64
import json
import os
import platform
import secrets
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
import time
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
            out.append(ch)
            continue
        if cp < 0x20 or (0x7F <= cp <= 0x9F):
            continue
        if cp in (0x200B, 0x200C, 0x200D, 0x2028, 0x2029, 0xFEFF):
            continue
        if (0x202A <= cp <= 0x202E) or (0x2066 <= cp <= 0x206F) or (0xE0000 <= cp <= 0xE007F):
            continue
        out.append(ch)
    return "".join(out)


def find_chromium_app_binary() -> str:
    sys_name = platform.system()
    if sys_name == "Darwin":
        mac_apps = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
        for p in mac_apps:
            if os.access(p, os.X_OK):
                return p
    elif sys_name == "Windows":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        la = os.environ.get("LOCALAPPDATA", "")
        win_apps = [
            os.path.join(pf86, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(pf, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(pf, "Google", "Chrome", "Application", "chrome.exe"),
            os.path.join(la, "Google", "Chrome", "Application", "chrome.exe") if la else "",
        ]
        for p in win_apps:
            if p and os.path.isfile(p):
                return p
    for name in ("google-chrome", "chromium", "chromium-browser", "brave-browser", "microsoft-edge"):
        found = shutil.which(name)
        if found:
            return found
    return ""


def find_wsl_windows_browser() -> str:
    if not (Path("/proc/sys/fs/binfmt_misc/WSLInterop").exists() or os.environ.get("WSL_INTEROP")):
        return ""
    for wb in (
        "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe",
        "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
        "/mnt/c/Program Files/Microsoft/Edge/Application/msedge.exe",
    ):
        if os.access(wb, os.X_OK):
            return wb
    return ""


def probe_desktop() -> tuple[bool, str]:
    if os.environ.get("CI", "").lower() in ("1", "true") or os.environ.get("GITHUB_ACTIONS", "").lower() == "true":
        return False, "ci_environment"
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return False, "ssh_remote_session"

    sys_name = platform.system()
    if sys_name == "Darwin":
        try:
            ws = subprocess.run(["pgrep", "-x", "WindowServer"], capture_output=True, timeout=2)
            if ws.returncode != 0:
                return False, "no_macos_windowserver"
        except Exception:
            pass
        if not (find_chromium_app_binary() or shutil.which("open")):
            return False, "no_macos_opener"
        return True, "macos_aqua"

    if sys_name == "Windows":
        if not (find_chromium_app_binary() or os.environ.get("SystemRoot")):
            return False, "no_windows_opener"
        return True, "windows_web_deck"

    # Linux / BSD X11 or Wayland desktop
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return False, "no_display"
    xdg_sess = os.environ.get("XDG_SESSION_ID", "").strip()
    if xdg_sess and shutil.which("loginctl"):
        try:
            lk = subprocess.run(
                ["loginctl", "show-session", xdg_sess, "-p", "LockedHint", "--value"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if lk.returncode == 0 and lk.stdout.strip().lower() == "yes":
                return False, "desktop_locked"
        except Exception:
            pass
    if not (find_chromium_app_binary() or find_wsl_windows_browser() or shutil.which("xdg-open")):
        return False, "no_linux_opener"
    return True, "linux_desktop"


_ICON_CACHE = None


def load_deck_html() -> str:
    return (Path(__file__).resolve().parent / "drift_ui_deck.html").read_text(encoding="utf-8")


def load_brand_icons() -> dict[str, bytes]:
    global _ICON_CACHE
    if _ICON_CACHE is not None:
        return _ICON_CACHE
    out: dict[str, bytes] = {}
    marker = '<meta name="drift-app-ico" content="'
    html = load_deck_html()
    idx = html.find(marker)
    if idx >= 0:
        start = idx + len(marker)
        end = html.find('"', start)
        if end > start:
            ico = base64.b64decode(html[start:end])
            out["/favicon.ico"] = ico
            count = struct.unpack_from("<H", ico, 4)[0] if len(ico) >= 6 else 0
            for i in range(count):
                off = 6 + 16 * i
                if off + 16 <= len(ico):
                    w = ico[off] or 256
                    sz, pos = struct.unpack_from("<II", ico, off + 8)
                    if pos + sz <= len(ico):
                        out[f"/icon-{w}.png"] = ico[pos : pos + sz]
    _ICON_CACHE = out
    return out


def sanitize_tree(obj):
    if isinstance(obj, str):
        return sanitize_text(obj)
    if isinstance(obj, list):
        return [sanitize_tree(x) for x in obj]
    if isinstance(obj, dict):
        return {sanitize_text(k): sanitize_tree(v) for k, v in obj.items()}
    return obj


class DeckState:
    def __init__(self, req_doc: dict, quiet_arm_ms: int):
        self.req_doc = sanitize_tree(req_doc)
        self.quiet_arm_s = max(0.05, quiet_arm_ms / 1000.0)
        self.boot_secret = secrets.token_urlsafe(32)
        self.boot_consumed = False
        self.session_cookie = secrets.token_urlsafe(32)
        self.csrf_token = secrets.token_urlsafe(32)
        self.script_nonce = secrets.token_urlsafe(18)
        self.port = 0
        self.connected = False
        self.first_render_mono = 0.0
        now_m = time.monotonic()
        self.last_heartbeat_mono = now_m
        self.last_input_mono = now_m
        self.result_gesture = None
        self.done_event = threading.Event()
        self.lock = threading.Lock()


def make_handler(state: DeckState):
    class DeckHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def check_host(self) -> bool:
            h = (self.headers.get("Host") or "").strip()
            return h == f"127.0.0.1:{state.port}"

        def has_valid_cookie(self) -> bool:
            raw = self.headers.get("Cookie") or ""
            for part in raw.split(";"):
                k, _, v = part.strip().partition("=")
                if k == "drift_deck_sid" and secrets.compare_digest(v, state.session_cookie):
                    return True
            return False

        def send_security_headers(self, content_type: str):
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header(
                "Content-Security-Policy",
                f"default-src 'none'; style-src 'unsafe-inline'; script-src 'nonce-{state.script_nonce}'; connect-src 'self'; img-src 'self' data:; manifest-src 'self'; base-uri 'none'; form-action 'self'",
            )

        def serve_deck_page(self, set_cookie: str = ""):
            with state.lock:
                state.connected = True
                now = time.monotonic()
                if state.first_render_mono == 0.0:
                    state.first_render_mono = now
                state.last_heartbeat_mono = now
                state.last_input_mono = now

            req_json = json.dumps(state.req_doc).replace("</", "<\\/")
            html = (
                load_deck_html().replace("__NONCE__", state.script_nonce)
                .replace("__CSRF_TOKEN__", state.csrf_token)
                .replace("__REQ_JSON__", req_json)
            )
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_security_headers("text/html; charset=utf-8")
            if set_cookie:
                self.send_header("Set-Cookie", set_cookie)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.check_host():
                self.send_response(403)
                self.end_headers()
                return
            clean_path = self.path.split("?", 1)[0]
            icons = load_brand_icons()
            if clean_path in icons:
                blob = icons[clean_path]
                ctype = "image/x-icon" if clean_path.endswith(".ico") else "image/png"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Cache-Control", "public, max-age=3600")
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob)
                return
            if clean_path == "/manifest.webmanifest":
                mf = json.dumps({
                    "name": "DRIFT · Review Dossier",
                    "short_name": "DRIFT",
                    "display": "standalone",
                    "background_color": "#111419",
                    "theme_color": "#151922",
                    "icons": [
                        {"src": "/icon-128.png", "sizes": "128x128", "type": "image/png", "purpose": "any"},
                        {"src": "/icon-48.png", "sizes": "48x48", "type": "image/png", "purpose": "any"},
                        {"src": "/icon-32.png", "sizes": "32x32", "type": "image/png", "purpose": "any"},
                    ],
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/manifest+json")
                self.send_header("Content-Length", str(len(mf)))
                self.end_headers()
                self.wfile.write(mf)
                return
            if clean_path != "/deck" or not self.has_valid_cookie():
                self.send_response(403)
                self.end_headers()
                return
            self.serve_deck_page()

        def do_POST(self):
            if not self.check_host():
                self.send_response(403)
                self.end_headers()
                return

            parsed = urllib.parse.urlparse(self.path)
            length = int(self.headers.get("Content-Length") or "0")
            if length > 262144:
                self.send_response(413)
                self.end_headers()
                return
            raw_body = self.rfile.read(length) if length > 0 else b""

            if parsed.path == "/init":
                params = urllib.parse.parse_qs(raw_body.decode("utf-8", errors="replace"))
                tok = (params.get("boot_secret") or [""])[0]
                with state.lock:
                    if state.boot_consumed or not tok or not secrets.compare_digest(tok, state.boot_secret):
                        self.send_response(403)
                        self.end_headers()
                        return
                    state.boot_consumed = True
                self.serve_deck_page(f"drift_deck_sid={state.session_cookie}; HttpOnly; SameSite=Lax; Path=/")
                return

            if parsed.path == "/api/closed":
                qs = urllib.parse.parse_qs(parsed.query)
                qtok = (qs.get("t") or [""])[0]
                if self.has_valid_cookie() and qtok and secrets.compare_digest(qtok, state.csrf_token):
                    with state.lock:
                        if state.result_gesture is None:
                            state.result_gesture = {
                                "schema": "drift.ui-gesture/1",
                                "request_id": str(state.req_doc.get("request_id") or ""),
                                "action": "cancel",
                                "confirmed_review_ref": "",
                                "confirmed_owner": "",
                                "note": "",
                                "selections": [],
                            }
                            state.done_event.set()
                self.send_response(204)
                self.end_headers()
                return

            hdr_tok = self.headers.get("X-Drift-Token") or ""
            if not self.has_valid_cookie() or not hdr_tok or not secrets.compare_digest(hdr_tok, state.csrf_token):
                self.send_response(403)
                self.end_headers()
                return

            if parsed.path == "/api/heartbeat":
                with state.lock:
                    state.last_heartbeat_mono = time.monotonic()
                self.send_response(204)
                self.end_headers()
                return

            if parsed.path == "/api/activity":
                with state.lock:
                    now = time.monotonic()
                    state.last_heartbeat_mono = now
                    state.last_input_mono = now
                self.send_response(204)
                self.end_headers()
                return

            if parsed.path == "/api/gesture":
                try:
                    gest = json.loads(raw_body.decode("utf-8"))
                except Exception:
                    self.send_response(400)
                    self.end_headers()
                    return
                act = str(gest.get("action") or "cancel")
                with state.lock:
                    if state.result_gesture is not None:
                        self.send_response(409)
                        self.end_headers()
                        return
                    now = time.monotonic()
                    if act in ("approve", "amend", "self_test_ok"):
                        if state.first_render_mono == 0.0 or (now - state.first_render_mono) < state.quiet_arm_s:
                            self.send_response(409)
                            self.end_headers()
                            return
                    state.result_gesture = gest
                    state.done_event.set()
                self.send_response(200)
                self.send_security_headers("application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
                return

            self.send_response(404)
            self.end_headers()

    return DeckHandler


def write_boot_file(work_dir: Path, port: int, boot_secret: str) -> Path:
    boot_path = work_dir / f"boot-{secrets.token_hex(6)}.html"
    nonce = secrets.token_urlsafe(16)
    icons = load_brand_icons()
    icon_tag = ""
    if "/icon-128.png" in icons:
        b64_png = base64.b64encode(icons["/icon-128.png"]).decode("ascii")
        icon_tag = f"<link rel='icon' type='image/png' sizes='128x128' href='data:image/png;base64,{b64_png}'>"
    content = (
        "<!DOCTYPE html><meta charset='utf-8'><title>DRIFT · Review Dossier</title>"
        f"<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; img-src data:; script-src 'nonce-{nonce}'; form-action http://127.0.0.1:{port}\">"
        f"{icon_tag}"
        "<body style='background:#111316;color:#A8C0B8;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0'>"
        f"<form id='f' method='POST' action='http://127.0.0.1:{port}/init'>"
        f"<input type='hidden' name='boot_secret' value='{boot_secret}'>"
        "<noscript><button type='submit'>Open DRIFT Gate</button></noscript>"
        "</form>"
        f"<script nonce='{nonce}'>document.getElementById('f').submit();</script></body>"
    )
    fd = os.open(str(boot_path), os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return boot_path


def launch_browser_window(boot_path: Path, work_dir: Path) -> tuple[subprocess.Popen | None, Path | None]:
    file_url = boot_path.resolve().as_uri()
    chrom = find_chromium_app_binary()
    if chrom:
        prof = work_dir / "app-profile"
        prof.mkdir(mode=0o700, exist_ok=True)
        return (
            subprocess.Popen(
                [
                    chrom,
                    f"--app={file_url}",
                    "--window-size=1120,760",
                    f"--user-data-dir={prof}",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
            None,
        )
    wsl_wb = find_wsl_windows_browser()
    if wsl_wb and shutil.which("wslpath"):
        try:
            win_tmp = subprocess.check_output(["cmd.exe", "/c", "echo %TEMP%"], text=True, stderr=subprocess.DEVNULL, timeout=4).strip()
            wsl_tmp_base = Path(subprocess.check_output(["wslpath", "-u", win_tmp], text=True, timeout=4).strip())
            wsl_stage = wsl_tmp_base / f"drift-deck-{secrets.token_hex(6)}"
            wsl_stage.mkdir(mode=0o700, parents=True, exist_ok=True)
            win_boot = wsl_stage / boot_path.name
            shutil.copy2(boot_path, win_boot)
            wsl_prof = wsl_stage / "prof"
            wsl_prof.mkdir(mode=0o700, exist_ok=True)
            win_boot_str = subprocess.check_output(["wslpath", "-w", str(win_boot)], text=True, timeout=4).strip()
            win_prof_str = subprocess.check_output(["wslpath", "-w", str(wsl_prof)], text=True, timeout=4).strip()
            win_file_url = "file:///" + win_boot_str.replace("\\", "/")
            return (
                subprocess.Popen(
                    [
                        wsl_wb,
                        f"--app={win_file_url}",
                        "--window-size=1120,760",
                        f"--user-data-dir={win_prof_str}",
                        "--no-first-run",
                        "--no-default-browser-check",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                ),
                wsl_stage,
            )
        except Exception:
            pass
    sys_name = platform.system()
    if sys_name == "Darwin" and shutil.which("open"):
        return subprocess.Popen(["open", str(boot_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), None
    if sys_name == "Windows":
        return subprocess.Popen(["cmd.exe", "/c", "start", "", str(boot_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), None
    if shutil.which("xdg-open"):
        return subprocess.Popen(["xdg-open", str(boot_path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), None
    return None, None


def run_self_test(req_path: Path, res_path: Path) -> int:
    req_doc = json.loads(req_path.read_text(encoding="utf-8"))
    state = DeckState(req_doc, 450)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    state.port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    tmp_dir = Path(tempfile.mkdtemp(prefix="drift-deck-test-"))
    os.chmod(tmp_dir, 0o700)
    try:
        boot_file = write_boot_file(tmp_dir, state.port, state.boot_secret)
        st_mode = boot_file.stat().st_mode & 0o777
        if st_mode != 0o600:
            return 2

        # 1. Spoofed Host header must fail 403
        req_bad_host = urllib.request.Request(f"http://127.0.0.1:{state.port}/deck", headers={"Host": "evil.example"})
        try:
            urllib.request.urlopen(req_bad_host, timeout=2)
            return 2
        except urllib.error.HTTPError as e:
            if e.code != 403:
                return 2

        # 2. Unauthenticated POST /api/gesture must fail 403
        req_unauth = urllib.request.Request(
            f"http://127.0.0.1:{state.port}/api/gesture",
            data=b'{"action":"approve"}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req_unauth, timeout=2)
            return 2
        except urllib.error.HTTPError as e:
            if e.code != 403:
                return 2

        # 3. Bootstrap /init returns 200 OK deck directly + burns one-time boot_secret
        init_req = urllib.request.Request(
            f"http://127.0.0.1:{state.port}/init",
            data=urllib.parse.urlencode({"boot_secret": state.boot_secret}).encode("utf-8"),
            method="POST",
        )
        with urllib.request.urlopen(init_req, timeout=2) as resp:
            if resp.status != 200:
                return 2
            set_cookie = resp.headers.get("Set-Cookie") or ""
            deck_html = resp.read().decode("utf-8")
            if "deckRoot" not in deck_html or req_doc.get("request_id", "") not in deck_html:
                return 2
        cookie_kv = set_cookie.split(";", 1)[0]

        # Replaying consumed boot_secret must fail 403
        replay_req = urllib.request.Request(
            f"http://127.0.0.1:{state.port}/init",
            data=urllib.parse.urlencode({"boot_secret": state.boot_secret}).encode("utf-8"),
            method="POST",
        )
        try:
            urllib.request.urlopen(replay_req, timeout=2)
            return 2
        except urllib.error.HTTPError as e:
            if e.code != 403:
                return 2

        # 4. Immediate POST before quiet_arm_ms must fail 409
        is_v2 = req_doc.get("schema") == "drift.ui-request/2"
        gest_schema = "drift.ui-gesture/2" if is_v2 else "drift.ui-gesture/1"
        early_req = urllib.request.Request(
            f"http://127.0.0.1:{state.port}/api/gesture",
            data=json.dumps({"schema": gest_schema, "request_id": req_doc.get("request_id", ""), "action": "self_test_ok"}).encode("utf-8"),
            headers={"Cookie": cookie_kv, "X-Drift-Token": state.csrf_token, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(early_req, timeout=2)
            return 2
        except urllib.error.HTTPError as e:
            if e.code != 409:
                return 2

        # 5. Advance past quiet_arm_ms deterministically and confirm clean gesture commit
        with state.lock:
            state.first_render_mono -= 0.50
        ok_body = {
            "schema": gest_schema,
            "request_id": req_doc.get("request_id", ""),
            "action": "self_test_ok",
            "confirmed_review_ref": req_doc.get("review_ref", ""),
            "confirmed_owner": req_doc.get("owner", ""),
            "note": "",
            "selections": [],
        }
        if is_v2:
            ok_body["confirmed_packet_ref"] = req_doc.get("packet_ref", "")
            ok_body["confirmed_groups"] = []
        ok_req = urllib.request.Request(
            f"http://127.0.0.1:{state.port}/api/gesture",
            data=json.dumps(ok_body).encode("utf-8"),
            headers={"Cookie": cookie_kv, "X-Drift-Token": state.csrf_token, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(ok_req, timeout=2) as resp:
            if resp.status != 200:
                return 2
        if not state.done_event.wait(1.0) or not state.result_gesture:
            return 2
        res_path.write_text(json.dumps(state.result_gesture), encoding="utf-8")
        return 0
    finally:
        srv.shutdown()
        srv.server_close()
        shutil.rmtree(tmp_dir, ignore_errors=True)


def run_live_deck(req_path: Path, res_path: Path, sentinel_path: Path | None) -> int:
    parent_pid = os.getppid()
    req_doc = json.loads(req_path.read_text(encoding="utf-8"))
    quiet_arm = int(req_doc.get("quiet_arm_ms") or 300)
    timeout_s = req_doc.get("timeout_s", 0)
    state = DeckState(req_doc, quiet_arm)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(state))
    state.port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()

    work_dir = req_path.parent
    boot_file = write_boot_file(work_dir, state.port, state.boot_secret)
    proc = None
    extra_stage = None
    try:
        proc, extra_stage = launch_browser_window(boot_file, work_dir)
        if proc is None:
            return 10
        start_mono = time.monotonic()
        while not state.done_event.wait(0.25):
            now = time.monotonic()
            if sentinel_path is not None and (not sentinel_path.exists() or os.getppid() != parent_pid):
                return 1
            with state.lock:
                conn = state.connected
                last_hb = state.last_heartbeat_mono
                last_inp = state.last_input_mono
            if not conn and (now - start_mono) > 8.0:
                return 10
            # Background tabs can batch Chrome timers as infrequently as once a minute.
            if conn and (now - last_hb) > 90.0:
                return 10
            if conn and timeout_s > 0 and (now - last_inp) >= timeout_s:
                is_v2_live = req_doc.get("schema") == "drift.ui-request/2"
                state.result_gesture = {
                    "schema": "drift.ui-gesture/2" if is_v2_live else "drift.ui-gesture/1",
                    "request_id": str(req_doc.get("request_id") or ""),
                    "action": "timeout",
                    "confirmed_review_ref": "",
                    "confirmed_owner": "",
                    "note": "",
                    "selections": [],
                }
                if is_v2_live:
                    state.result_gesture["confirmed_packet_ref"] = ""
                    state.result_gesture["confirmed_groups"] = []
                break
        if state.result_gesture is None:
            return 10
        res_path.write_text(json.dumps(state.result_gesture), encoding="utf-8")
        return 0
    finally:
        try:
            boot_file.unlink(missing_ok=True)
        except Exception:
            pass
        srv.shutdown()
        srv.server_close()
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        if extra_stage is not None:
            shutil.rmtree(extra_stage, ignore_errors=True)


def main() -> int:
    args = sys.argv[1:]
    if len(args) == 1 and args[0] == "--probe":
        ok, reason = probe_desktop()
        print(json.dumps({"desktop_ok": ok, "reason": reason}))
        return 0 if ok else 10
    if len(args) == 3 and args[0] == "--self-test":
        return run_self_test(Path(args[1]), Path(args[2]))
    if len(args) in (2, 3):
        sent = Path(args[2]) if len(args) == 3 and args[2] else None
        return run_live_deck(Path(args[0]), Path(args[1]), sent)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
