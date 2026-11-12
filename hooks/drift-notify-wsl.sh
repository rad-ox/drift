#!/bin/sh
# Reference detached WSL2 / TTY attention sink for DRIFT lifecycle hooks.
# Reads one drift.attention/1 JSON line from stdin with zero shell interpolation,
# optionally writes OSC 9 to /dev/tty, and dispatches an in-place Windows 11
# bottom-right Toast (Group="drift", Tag=<12-hex area hash>) via detached
# Windows PowerShell 5.1 (powershell.exe) with all stdio FDs closed.
set -eu

payload=$(cat 2>/dev/null || true)
payload_flat=$(printf '%s' "$payload" | tr -d '\r\n')
[ -n "$payload_flat" ] || exit 0

extract_json_str() { # key
	k="\"$1\""
	case $payload_flat in
	*"$k"*)
		rest=${payload_flat#*"$k"}
		rest=${rest#*:}
		while :; do
			case $rest in
			" "* | "	"*) rest=${rest#?} ;;
			*) break ;;
			esac
		done
		case $rest in
		\"*)
			rest=${rest#\"}
			val=""
			while :; do
				chunk=${rest%%\"*}
				val="${val}${chunk}"
				[ "$rest" != "$chunk" ] || break
				case $chunk in
				*\\)
					val="${val%?}\""
					rest=${rest#*\"}
					;;
				*) break ;;
				esac
			done
			printf '%s' "$val"
			;;
		esac
		;;
	esac
}

area=$(extract_json_str area)
area_name=$(extract_json_str area_name)
[ -n "$area_name" ] || area_name=${area##*/}
[ -n "$area_name" ] || area_name="drift"
headline=$(extract_json_str headline)
[ -n "$headline" ] || headline="Attention needed"
detail=$(extract_json_str detail)
tag=$(printf '%s' "${area:-$area_name}" | cksum | awk '{printf "d%010u", $1}' | cut -c1-12)

# Deterministic offline test capture when DRIFT_NOTIFY_CAPTURE_FILE is set.
if [ -n "${DRIFT_NOTIFY_CAPTURE_FILE:-}" ]; then
	printf '{"tag":"%s","area_name":"%s","headline":"%s","detail":"%s"}\n' \
		"$tag" "$area_name" "$headline" "$detail" >>"$DRIFT_NOTIFY_CAPTURE_FILE"
	exit 0
fi

# Tier 1: zero-fork OSC 9 to /dev/tty when an interactive terminal is attached (never stdout).
if [ "${DRIFT_NOTIFY_TTY:-1}" != "0" ] && [ -w /dev/tty ] 2>/dev/null; then
	osc_msg=$(printf 'DRIFT [%s]: %s%s' "$area_name" "$headline" "${detail:+ — $detail}" | tr -d '\000-\037\177')
	{ printf '\033]9;%s\007' "$osc_msg" >/dev/tty; } 2>/dev/null || true
fi

# Tier 2: detached WSL2 Windows PowerShell 5.1 WinRT ToastNotificationManager (in-place Tag replacement).
ps51=""
for cand in "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe" "$(command -v powershell.exe 2>/dev/null || true)"; do
	if [ -n "$cand" ] && [ -x "$cand" ]; then
		ps51=$cand
		break
	fi
done
[ -n "$ps51" ] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

encoded=$(DRIFT_T_TITLE="DRIFT · $area_name" DRIFT_T_HEAD="$headline" DRIFT_T_BODY="$detail" DRIFT_T_TAG="$tag" python3 - <<'PY'
import base64, html, os
title = html.escape(os.environ.get("DRIFT_T_TITLE", "DRIFT")[:80])
head = html.escape(os.environ.get("DRIFT_T_HEAD", "")[:140])
body = html.escape(os.environ.get("DRIFT_T_BODY", "")[:200])
tag = html.escape(os.environ.get("DRIFT_T_TAG", "drift")[:16])
xml = f"<toast duration='short'><visual><binding template='ToastGeneric'><text>{title}</text><text>{head}</text>" + (f"<text>{body}</text>" if body else "") + "</binding></visual></toast>"
xml_ps = xml.replace("'", "''")
ps = (
    "$ErrorActionPreference='SilentlyContinue';"
    "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
    "[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]|Out-Null;"
    f"$x=New-Object Windows.Data.Xml.Dom.XmlDocument;$x.LoadXml('{xml_ps}');"
    "$t=[Windows.UI.Notifications.ToastNotification]::new($x);"
    f"$t.Group='drift';$t.Tag='{tag}';"
    "$t.ExpirationTime=[DateTimeOffset]::Now.AddMinutes(10);"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($t)"
)
print(base64.b64encode(ps.encode("utf-16-le")).decode("ascii"))
PY
) || exit 0

[ -n "$encoded" ] || exit 0
if command -v setsid >/dev/null 2>&1; then
	setsid "$ps51" -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand "$encoded" </dev/null >/dev/null 2>&1 &
else
	("$ps51" -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand "$encoded" </dev/null >/dev/null 2>&1 &)
fi
exit 0
