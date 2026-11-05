#!/bin/sh
# Universal vendor-agnostic DRIFT lifecycle hook for POSIX / WSL / Cloud agents.
# Supports SessionStart (sessionStart) and Stop (agentStop) payloads across
# Copilot, Claude, Codex, Gemini and Cursor. Fast-exits in < 5 ms outside DRIFT.
set -eu

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
mode=${1:-}

payload=""
if [ ! -t 0 ]; then
	payload=$(cat 2>/dev/null || true)
fi
payload_flat=$(printf '%s' "$payload" | tr -d '\r\n')

# O(|payload|) in-process JSON string extraction without fork/exec per field.
extract_str() { # key
	key_pat="\"$1\""
	case $payload_flat in
	*"$key_pat"*)
		rest=${payload_flat#*"$key_pat"}
		rest=${rest#*:}
		while :; do
			case $rest in
			" "* | "$tab"*) rest=${rest#?} ;;
			*) break ;;
			esac
		done
		case $rest in
		\"*)
			rest=${rest#\"}
			printf '%s' "${rest%%\"*}"
			;;
		esac
		;;
	esac
}

tab=$(printf '\t')
cwd=$(extract_str cwd)
[ -n "$cwd" ] || cwd=${PWD:-.}
case $cwd in
*\\*) cwd=$(printf '%s' "$cwd" | tr '\\' '/') ;;
esac
if [ ! -d "$cwd" ]; then
	exit 0
fi

# Walk up from cwd to find the nearest .drift/config.toml (stopping at .git or /).
area=""
dir=$(CDPATH='' cd -- "$cwd" 2>/dev/null && pwd || printf '%s' "$cwd")
while [ -n "$dir" ]; do
	if [ -f "$dir/.drift/config.toml" ]; then
		area=$dir
		break
	fi
	[ ! -e "$dir/.git" ] || break
	[ "$dir" != / ] || break
	parent=${dir%/*}
	[ "$parent" != "$dir" ] || break
	dir=${parent:-/}
done

[ -n "$area" ] || exit 0

# Resolve the native Linux/WSL drift binary (never a Windows .exe inside POSIX).
drift_bin=${DRIFT_CLI:-}
if [ -z "$drift_bin" ] || [ ! -x "$drift_bin" ]; then
	for cand in "$here/../../bin/drift" "$HOME/.local/bin/drift" "$(command -v drift 2>/dev/null || true)"; do
		if [ -n "$cand" ] && [ -x "$cand" ]; then
			case $cand in
			*.exe) continue ;;
			esac
			drift_bin=$cand
			break
		fi
	done
fi
[ -n "$drift_bin" ] || exit 0

event=$(extract_str hook_event_name)
[ -n "$event" ] || event=$(extract_str hookEventName)
	if [ -z "$event" ]; then
	case $mode in
	session | start | SessionStart | sessionStart) event=SessionStart ;;
	stop | Stop | agentStop) event=Stop ;;
	*)
		case $payload_flat in
		*'"stop_hook_active"'* | *'"stopReason"'* | *'"stop_reason"'*) event=Stop ;;
		*) event=SessionStart ;;
		esac
		;;
	esac
fi
case $event in
SessionStart | sessionStart | session | start | startup | resume | before_agent_start | beforeAgentStart) norm_event=sessionstart ;;
Stop | stop | agentStop | agent_stop | afterAgent | after_agent) norm_event=stop ;;
*) norm_event=$(printf '%s' "$event" | tr '[:upper:]' '[:lower:]' | tr -d '_-') ;;
esac

json_escape() {
	printf '%s' "$1" | tr '\n\r\t' '   ' | sed 's/\\/\\\\/g; s/"/\\"/g'
}

contracts_dir=$area/.drift/contracts

case $norm_event in
sessionstart | startup | resume | beforeagentstart)
	summary="DRIFT area active at $area."
	if [ -d "$contracts_dir" ]; then
		stats_out=$("$drift_bin" status "$contracts_dir" 2>/dev/null | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//' || true)
		[ -z "$stats_out" ] || summary="$summary $stats_out."
	fi
	if [ "${DRIFT_EDITION:-}" = "free" ]; then
		msg="$summary For read-only Q&A or explanations that do not edit code or contracts, answer directly without loading DRIFT skills. When changing code or contracts in DRIFT Free, use drift check, drift fmt, drift review --brief, drift approve --by <owner>, drift prove, and drift gate."
	else
		msg="$summary For read-only Q&A or explanations that do not edit code or contracts, answer directly without loading DRIFT skills or writing recall cards. When changing code or contracts, follow the drift skill: (0) Orient first with drift impact --recall '<expr>' (e.g. 'feature @') before exploratory grep/view; on a MISS during contract/code work, record the discovered capsule in .drift-work/recall.jsonl. (1) Behaviour unchanged on covered code (bugfix/refactor/test hardening): 0 human stops, use drift select --changed and drift gate --base. On uncovered code (0 matching contracts), a DRIFT split/refactor is a Baseline Carve-out: scaffold the contract(s) (drift new --from-recall --code), bind proof tests, and run drift review --brief instead of ending with no contract. (2) New or changed behaviour across multiple slices (Wave): use 1 cohesive contract for uniform dispatch/handler splits, or N contracts when slices have distinct rules (<path>#<symbol> on shared files, decide_by = \"execution\" for non-blocking details), run 1 batch drift review .drift/contracts --brief --base, wait ONCE for owner drift approve .drift/contracts --by <owner>, then execute all slices in parallel via drift impact --schedule --pack ready. Never piggyback new feature assertions onto existing approved cases."
	fi
	printf '{"additionalContext":"%s"}\n' "$(json_escape "$msg")"
	exit 0
	;;
stop | agentstop | afteragent)
	if printf '%s' "$payload" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
		exit 0
	fi
	if ! "$drift_bin" check "$area/.drift" --json >/dev/null 2>&1; then
		printf '{"decision":"block","reason":"DRIFT check reported findings in %s/.drift. Run drift fmt and drift check --json to fix contract or config findings before finishing."}\n' "$(json_escape "$area")"
		exit 0
	fi
	if [ "${DRIFT_EDITION:-}" != "free" ] && command -v git >/dev/null 2>&1 && git -C "$area" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
		changed=$(git -C "$area" -c core.quotepath=false status --porcelain --untracked-files=normal 2>/dev/null | awk '
			length($0) >= 4 && substr($0, 1, 1) != "D" && substr($0, 2, 1) != "D" {
				p = substr($0, 4)
				if (substr($0, 1, 1) ~ /[RC]/ || substr($0, 2, 1) ~ /[RC]/) {
					sub(/^.* -> /, "", p)
				}
				gsub(/^"|"$|\r$/, "", p)
				if (p != "") print p
			}
		' | grep -v '^\.drift/' | grep -E '\.(v|java|kt|js|mjs|ts|tsx|py|go|rs)$' | head -n 25 || true)
		if [ -n "$changed" ]; then
			contracts_dirty=$(git -C "$area" status --porcelain --untracked-files=normal -- .drift/contracts 2>/dev/null || true)
			set --
			for f in $changed; do
				[ -f "$area/$f" ] || continue
				set -- "$@" --code "$f"
			done
			if [ "$#" -gt 0 ]; then
				imp_flat=""
				if [ -d "$contracts_dir" ]; then
					imp_flat=$("$drift_bin" impact "$contracts_dir" "$@" --json 2>/dev/null | tr -d '\n ' || true)
				fi
				[ -n "$imp_flat" ] || imp_flat='{"contracts":[],"unmatched_code":["uncontracted"]}'
				if printf '%s' "$imp_flat" | grep -q '"unmatched_code":\["'; then
					if [ -n "$contracts_dirty" ] || printf '%s' "$imp_flat" | grep -q '"contracts":\[\]'; then
						stamp_id=$(printf '%s:%s' "$area" "$changed" | cksum | awk '{print $1}')
						stamp_file=${TMPDIR:-/tmp}/drift-stop-$stamp_id
						if [ ! -f "$stamp_file" ]; then
							: >"$stamp_file" 2>/dev/null || true
							printf '{"decision":"block","reason":"DRIFT impact detected changed source files in %s not covered by any contract scope.code (unmatched_code). Scaffold the baseline contract(s) (drift new --from-recall --code) or run drift sweep --root %s --sync-scope instead of piggybacking on unrelated cases."}\n' "$(json_escape "$area")" "$(json_escape "$area")"
							exit 0
						fi
					fi
				fi
			fi
		fi
	fi
	exit 0
	;;
esac
exit 0
