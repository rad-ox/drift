#!/usr/bin/env python3
"""Advisory release check; stdout is a notice, stderr is an unavailable diagnostic."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import urllib.error
import urllib.request


VERSION = re.compile(
    r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)


def version(value):
    match = VERSION.fullmatch(value) if isinstance(value, str) else None
    if not match:
        raise ValueError("invalid version")
    return tuple(int(match[i]) for i in (1, 2, 3)), match[4]


def load_policy(path):
    policy = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict) or type(policy.get("enabled")) is not bool:
        raise ValueError("invalid release policy")
    if (policy.get("channel") != "stable"
            or not isinstance(policy.get("repository"), str)
            or not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9_.-]+", policy["repository"])):
        raise ValueError("invalid release policy")
    if policy["repository"].split("/")[1] in (".", ".."):
        raise ValueError("invalid release repository")
    for key in ("timeout_seconds", "total_timeout_seconds", "max_response_bytes"):
        if type(policy.get(key)) is not int or policy[key] <= 0:
            raise ValueError("invalid release policy")
    if not policy["timeout_seconds"] < policy["total_timeout_seconds"] <= 3:
        raise ValueError("invalid release deadline")
    if policy["max_response_bytes"] > 65536:
        raise ValueError("invalid release response limit")
    return policy


def notice(installed, release, policy):
    local, prerelease = version(installed)
    if (not isinstance(release, dict) or type(release.get("draft")) is not bool
            or type(release.get("prerelease")) is not bool):
        raise ValueError("invalid release metadata")
    if release["draft"] or release["prerelease"]:
        return ""
    tag = release.get("tag_name")
    remote, remote_pre = version(tag)
    if remote_pre:
        raise ValueError("invalid stable release tag")
    if remote < local or (remote == local and prerelease is None):
        return ""
    available = tag.removeprefix("v")
    url = f'https://github.com/{policy["repository"]}/releases/tag/{tag}'
    return f"DRIFT update available: {installed} -> {available}. Release: {url}"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check(binary, policy):
    completed = subprocess.run(
        [binary, "version"], capture_output=True, text=True, check=True,
        timeout=policy["timeout_seconds"],
    )
    fields = completed.stdout.split()
    if len(fields) < 2 or fields[0] != "drift":
        raise ValueError("invalid CLI version")
    installed = fields[1]
    version(installed)
    request = urllib.request.Request(
        f'https://api.github.com/repos/{policy["repository"]}/releases/latest',
        headers={"Accept": "application/vnd.github+json", "User-Agent": "drift-release-check"},
    )
    with urllib.request.build_opener(NoRedirect).open(
            request, timeout=policy["timeout_seconds"]) as response:
        raw = response.read(policy["max_response_bytes"] + 1)
    if len(raw) > policy["max_response_bytes"]:
        raise ValueError("release response too large")
    return notice(installed, json.loads(raw), policy)


def deadline(_signum, _frame):
    raise TimeoutError("release check deadline")


def main():
    if os.environ.get("DRIFT_UPDATE_CHECK") == "0":
        return
    try:
        policy = load_policy(Path(__file__).with_name("release-policy.json"))
        if not policy["enabled"]:
            return
        signal.signal(signal.SIGALRM, deadline)
        signal.setitimer(signal.ITIMER_REAL, policy["total_timeout_seconds"])
        if len(sys.argv) != 2:
            raise ValueError("missing CLI path")
        message = check(sys.argv[1], policy)
        if message:
            print(message)
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError) as error:
        reason = "network unavailable" if isinstance(error, urllib.error.URLError) else type(error).__name__
        print(f"drift: release check unavailable ({reason}); continuing without an update verdict.",
              file=sys.stderr)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


if __name__ == "__main__":
    main()
