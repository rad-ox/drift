#!/bin/sh
# Universal vendor-agnostic DRIFT lifecycle hook for POSIX / WSL / Cloud agents.
# Supports SessionStart (sessionStart) and Stop (agentStop) payloads across
# Copilot, Claude, Codex, Gemini and Cursor. Fast-exits in < 5 ms outside DRIFT.
# Context boundary: these payloads carry no trusted task attribution or prompt
# identity. Stop diagnostics keep the conservative area check, state that task
# relevance is unknown, and deduplicate one unchanged diagnostic per host
# session (when supplied) and area; a changed diagnostic reopens it.
set -eu

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
mode=${1:-}

payload=""
if [ ! -t 0 ]; then
	payload=$(cat 2>/dev/null || true)
fi
payload_flat=$(printf '%s' "$payload" | tr -d '\r\n')
tab=$(printf '\t')

# O(|payload|) in-process JSON string extraction without fork/exec per field,
# preserving escaped quotes (\") and stripping prompt/initialPrompt bodies from
# metadata lookups so user prompt text cannot spoof top-level hook fields.
extract_str_from() { # haystack key
	hay=$1
	key_pat="\"$2\""
	case $hay in
	*"$key_pat"*)
		rest=${hay#*"$key_pat"}
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

strip_str_field() { # json key
	s=$1
	k="\"$2\""
	case $s in
	*"$k"*)
		pre=${s%%"$k"*}
		post=${s#*"$k"}
		post=${post#*:}
		while :; do
			case $post in
			" "* | "$tab"*) post=${post#?} ;;
			*) break ;;
			esac
		done
		case $post in
		\"*)
			post=${post#\"}
			while :; do
				c=${post%%\"*}
				[ "$post" != "$c" ] || break
				post=${post#*\"}
				case $c in
				*\\) ;;
				*) break ;;
				esac
			done
			printf '%s"%s":""%s' "$pre" "$2" "$post"
			return
			;;
		esac
		;;
	esac
	printf '%s' "$s"
}

meta_flat=$(strip_str_field "$payload_flat" initialPrompt)
meta_flat=$(strip_str_field "$meta_flat" prompt)

extract_str() { # key
	extract_str_from "$meta_flat" "$1"
}

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
	for cand in "$here/../../../bin/drift" "$here/../bin/drift" "$here/../../bin/drift" "$HOME/.local/bin/drift" "$(command -v drift 2>/dev/null || true)"; do
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
	prompt | userPromptSubmit | UserPromptSubmit | userPromptSubmitted | before_agent_start | beforeAgentStart) event=UserPromptSubmit ;;
	stop | Stop | agentStop) event=Stop ;;
	*)
		case $meta_flat in
		*'"stop_hook_active"'* | *'"stopReason"'* | *'"stop_reason"'*) event=Stop ;;
		*'"prompt"'*:*) event=UserPromptSubmit ;;
		*) event=SessionStart ;;
		esac
		;;
	esac
fi
case $event in
SessionStart | sessionStart | session | start | startup | resume) norm_event=sessionstart ;;
before_agent_start | beforeAgentStart) norm_event=beforeagentstart ;;
UserPromptSubmit | userPromptSubmit | userPromptSubmitted | prompt) norm_event=userpromptsubmit ;;
Stop | stop | agentStop | agent_stop | afterAgent | after_agent) norm_event=stop ;;
*) norm_event=$(printf '%s' "$event" | tr '[:upper:]' '[:lower:]' | tr -d '_-') ;;
esac

extract_session() {
	s=$(extract_str parentAgentId)
	[ -n "$s" ] || s=$(extract_str parent_agent_id)
	[ -n "$s" ] || s=$(extract_str session_id)
	[ -n "$s" ] || s=$(extract_str sessionId)
	printf '%s' "$s"
}

json_escape() {
	printf '%s' "$1" | tr '\n\r\t' '   ' | sed 's/\\/\\\\/g; s/"/\\"/g'
}

contracts_dir=$area/.drift/contracts

release_notice() {
	[ "${DRIFT_UPDATE_CHECK:-}" != 0 ] && [ -d "$here/release" ] || return 0
	if [ -f "$here/release/check.py" ] && command -v python3 >/dev/null 2>&1; then
		python3 "$here/release/check.py" "$drift_bin"
	else
		printf '%s\n' 'drift: release check unavailable (Python or component missing); continuing without an update verdict.' >&2
	fi
}

case $norm_event in
userpromptsubmit | userpromptsubmitted)
	prompt_text=$(extract_str_from "$payload_flat" prompt)
	case $prompt_text in
	"DRIFT area check found "*"(no trusted task attribution)."* | \
	"DRIFT area check could not run in "*"No check verdict is available."* | \
	"Changed source files in "*"(working-tree evidence, not task attribution)."*)
		exit 0
		;;
	esac
	session=$(extract_session)
	base_key=$(printf '%s:%s' "$area" "$session" | cksum | awk '{print $1}')
	rm -f "${TMPDIR:-/tmp}/drift-stop-check-${base_key}"* "${TMPDIR:-/tmp}/drift-stop-unowned-${base_key}"* 2>/dev/null || true
	exit 0
	;;
sessionstart | startup | resume | beforeagentstart)
	if [ "$norm_event" = beforeagentstart ]; then
		session=$(extract_session)
		base_key=$(printf '%s:%s' "$area" "$session" | cksum | awk '{print $1}')
		rm -f "${TMPDIR:-/tmp}/drift-stop-check-${base_key}"* "${TMPDIR:-/tmp}/drift-stop-unowned-${base_key}"* 2>/dev/null || true
	fi
	summary="DRIFT area active at $area."
	if [ -d "$contracts_dir" ]; then
		stats_out=$("$drift_bin" status "$contracts_dir" 2>/dev/null | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g; s/^ //; s/ $//' || true)
		[ -z "$stats_out" ] || summary="$summary $stats_out."
	fi
	if [ "$norm_event" != beforeagentstart ]; then
		if update_notice=$(release_notice); then
			[ -z "$update_notice" ] || summary="$summary $update_notice"
		else
			printf '%s\n' 'drift: release check unavailable (component failure); continuing without an update verdict.' >&2
		fi
	fi
	if [ "${DRIFT_EDITION:-}" = "free" ]; then
		msg="$summary For read-only Q&A or explanations that do not edit code or contracts, answer directly without loading DRIFT skills. When changing code or contracts in DRIFT Free, use drift check, drift fmt, drift review --brief, drift approve --by <owner>, drift prove, and drift gate."
	else
		drift_skill="drift"
		if [ -d "${HOME:-}/.copilot/skills/drift-enterprise" ] || [ -d "${HOME:-}/.agents/skills/drift-enterprise" ]; then
			drift_skill="drift-enterprise"
		elif [ -d "${HOME:-}/.copilot/skills/drift-pro" ] || [ -d "${HOME:-}/.agents/skills/drift-pro" ]; then
			drift_skill="drift-pro"
		fi
		msg="$summary For read-only Q&A or explanations that do not edit code or contracts, answer directly without loading DRIFT skills or writing recall cards. When changing code or contracts, follow the $drift_skill skill: (0) Orient first with drift recall query '<expr>' (e.g. 'feature @') before exploratory grep/view; on a MISS during contract/code work, record the discovered capsule in .drift-work/recall.jsonl. (1) Behaviour unchanged on covered code (bugfix/refactor/test hardening): 0 human stops, use drift select --changed and drift gate --base. On uncovered code (0 matching contracts), a DRIFT split/refactor is a Baseline Carve-out: scaffold the contract(s) (drift new --from-recall --code), bind proof tests, and run drift review --brief instead of ending with no contract. (2) New or changed behaviour across multiple slices (Wave): use 1 cohesive contract for uniform dispatch/handler splits, or N contracts when slices have distinct rules (<path>#<symbol> on shared files, decide_by = \"execution\" for non-blocking details), run 1 batch drift review .drift/contracts --brief --base, wait ONCE for owner drift approve .drift/contracts --by <owner>, then execute all slices in parallel via drift plan --pack ready. Never piggyback new feature assertions onto existing approved cases."
	fi
	printf '{"additionalContext":"%s"}\n' "$(json_escape "$msg")"
	exit 0
	;;
stop | agentstop | afteragent)
	case $meta_flat in
	*'"stop_hook_active"'*:*true*)
		if printf '%s' "$meta_flat" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
			printf '%s\n' 'drift: continued stop; the previous DRIFT outcome was not re-evaluated and is not treated as passing.' >&2
			exit 0
		fi
		;;
	esac
	session=$(extract_session)
	turn=""
	for tk in prompt_id promptId turn_id turnId interaction_id interactionId; do
		turn=$(extract_str "$tk")
		[ -z "$turn" ] || break
	done
	base_key=$(printf '%s:%s' "$area" "$session" | cksum | awk '{print $1}')
	turn_key=""
	if [ -n "$turn" ]; then
		turn_key=$(printf '%s' "$turn" | cksum | awk '{print $1}')
		stamp_file=${TMPDIR:-/tmp}/drift-stop-check-${base_key}-${turn_key}
	else
		stamp_file=${TMPDIR:-/tmp}/drift-stop-check-${base_key}
	fi
	if check_out=$("$drift_bin" check "$area/.drift" --json 2>&1); then
		rm -f "${TMPDIR:-/tmp}/drift-stop-check-${base_key}"* 2>/dev/null || true
	else
		check_status=$?
		fingerprint=$(printf '%s:%s' "$check_status" "$check_out" | cksum | awk '{print $1}')
		last=""
		[ ! -f "$stamp_file" ] || IFS= read -r last <"$stamp_file" || true
		if [ "$last" = "$fingerprint" ]; then
			printf '%s\n' 'drift: the same DRIFT area diagnostic is still unresolved; not repeated to avoid a correction loop. It is not treated as passing.' >&2
			exit 0
		fi
		printf '%s\n' "$fingerprint" >"$stamp_file" 2>/dev/null || true
		if [ "$check_status" = 1 ]; then
			first=$(printf '%s\n' "$check_out" | awk '
				function val(s) { sub(/^[^:]*:[[:space:]]*"/, "", s); sub(/",?[[:space:]]*$/, "", s); gsub(/\\"/, "\"", s); gsub(/\t/, " ", s); return s }
				/^[[:space:]]*"file":/ { file = val($0) }
				/^[[:space:]]*"code":/ { n++; if (n == 1) { f = file; code = val($0) } }
				n == 1 && /^[[:space:]]*"message":/ && msg == "" { msg = val($0) }
				n == 1 && /^[[:space:]]*"path":/ && path == "" { path = val($0) }
				END { printf "%d\037%s\037%s\037%s\037%s", n, f, path, code, msg }')
			IFS=$(printf '\037') read -r count f_file f_path f_code f_msg <<EOF_FIRST || true
$first
EOF_FIRST
			reason="DRIFT area check found ${count:-0} finding(s) in $area/.drift; relevance to the current task is unknown (no trusted task attribution). First: $f_file${f_path:+ ($f_path)}: $f_code $f_msg. Next: if this task changed that file, run drift explain $f_code and fix it; otherwise report it without editing unrelated contracts. The full-area check remains required before delivery."
		else
			cause=$(printf '%s\n' "$check_out" | awk 'NF { print; exit }' | cut -c1-200)
			reason="DRIFT area check could not run in $area/.drift (exit $check_status: invocation, input or environment): ${cause:-no diagnostic}. Next: run drift check $area/.drift to inspect the tooling or input error; formatting contracts will not fix it. No check verdict is available."
		fi
		printf '{"decision":"block","reason":"%s"}\n' "$(json_escape "$reason")"
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
			old_ifs=$IFS
			IFS=$(printf '\n\b')
			for f in $changed; do
				[ -f "$area/$f" ] || continue
				set -- "$@" --code "$f"
			done
			IFS=$old_ifs
			if [ "$#" -gt 0 ]; then
				imp_flat=""
				imp_ok=1
				if [ -d "$contracts_dir" ]; then
					if imp_raw=$("$drift_bin" impact "$contracts_dir" "$@" --json 2>/dev/null); then
						imp_flat=$(printf '%s' "$imp_raw" | tr -d '\n ')
					else
						imp_ok=0
					fi
				fi
				if [ "$imp_ok" = 1 ]; then
					[ -n "$imp_flat" ] || imp_flat='{"contracts":[],"unmatched_code":["uncontracted"]}'
					if printf '%s' "$imp_flat" | grep -q '"unmatched_code":\["'; then
						if [ -n "$contracts_dirty" ] || printf '%s' "$imp_flat" | grep -q '"contracts":\[\]'; then
							stamp_id=$(printf '%s:%s' "$area" "$changed" | cksum | awk '{print $1}')
							unowned_file=${TMPDIR:-/tmp}/drift-stop-unowned-${base_key}${turn_key:+-$turn_key}-${stamp_id}
							if [ ! -f "$unowned_file" ]; then
								: >"$unowned_file" 2>/dev/null || true
								printf '{"decision":"block","reason":"Changed source files in %s are not covered by any contract scope.code (unmatched_code); whether this task owns them is unknown (working-tree evidence, not task attribution). Next: if this task changed them, scaffold the baseline contract(s) (drift new --from-recall --code) or run drift sweep --root %s --sync-scope; otherwise report them and leave them unchanged."}\n' "$(json_escape "$area")" "$(json_escape "$area")"
								exit 0
							fi
						fi
					else
						rm -f "${TMPDIR:-/tmp}/drift-stop-unowned-${base_key}"* 2>/dev/null || true
					fi
				fi
			fi
		else
			rm -f "${TMPDIR:-/tmp}/drift-stop-unowned-${base_key}"* 2>/dev/null || true
		fi
	fi
	exit 0
	;;
esac
exit 0
