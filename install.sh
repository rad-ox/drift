#!/bin/sh
# DRIFT installer for Linux x86-64. It copies the drift command, the agent
# skill, the JUnit bridge and the Maven plugin to per-user locations and
# records them in a
# manifest, so that --uninstall removes exactly those. It needs no
# administrator rights and no network, and never edits shell profiles.
set -eu

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
tab=$(printf '\t')

prefix=$HOME/.local
prefix_set=0
skills=$HOME/.copilot/skills
skills_set=0
hooks_dir=
maven_repo=
with_skill=1
with_hooks=0
hooks_set=0
update_check=
update_yes=0
update_no=0
no_hooks=0
with_maven=1
dry=0
action=install
lang=${DRIFT_LANG:-}
bad=

need() { # option value...
	if [ $# -lt 2 ] || [ -z "$2" ]; then
		bad="$1"
		action=bad
		return 1
	fi
}

while [ $# -gt 0 ]; do
	case $1 in
	--prefix=*) prefix=${1#*=} prefix_set=1 ;;
	--prefix) need "$@" && prefix=$2 prefix_set=1 && shift ;;
	--skills-dir=*) skills=${1#*=} skills_set=1 ;;
	--skills-dir) need "$@" && skills=$2 skills_set=1 && shift ;;
	--hooks-dir=*) hooks_dir=${1#*=} with_hooks=1 hooks_set=1 ;;
	--hooks-dir) need "$@" && hooks_dir=$2 with_hooks=1 hooks_set=1 && shift ;;
	--hooks) with_hooks=1 hooks_set=1 ;;
	--no-hooks) with_hooks=0 hooks_set=1 no_hooks=1 ;;
	--update-check) update_check=1 update_yes=1 with_hooks=1 hooks_set=1 ;;
	--no-update-check) update_check=0 update_no=1 ;;
	--maven-repo=*) maven_repo=${1#*=} ;;
	--maven-repo) need "$@" && maven_repo=$2 && shift ;;
	--lang=*) lang=${1#*=} ;;
	--lang) need "$@" && lang=$2 && shift ;;
	--no-skill) with_skill=0 ;;
	--no-maven) with_maven=0 ;;
	--dry-run) dry=1 ;;
	--uninstall) action=uninstall ;;
	-h | --help) action=help ;;
	*) bad=$1 action=bad ;;
	esac
	[ "$action" = bad ] && break
	shift
done

# ---- language and output
if [ -z "$lang" ]; then
	case ${LANGUAGE:-}:${LC_ALL:-${LC_MESSAGES:-${LANG:-}}} in
	it* | *:it*) lang=it ;;
	*) lang=en ;;
	esac
fi
[ "$lang" = it ] || lang=en

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ] && [ "${TERM:-dumb}" != dumb ]; then
	bold=$(printf '\033[1m') green=$(printf '\033[32m') yellow=$(printf '\033[33m')
	red=$(printf '\033[31m') dim=$(printf '\033[2m') off=$(printf '\033[0m')
else
	bold='' green='' yellow='' red='' dim='' off=''
fi
case ${LC_ALL:-${LC_CTYPE:-${LANG:-}}} in
*[Uu][Tt][Ff]-8* | *[Uu][Tt][Ff]8*) g_ok='✓' g_note='!' g_fail='✗' ;;
*) g_ok='ok' g_note='!' g_fail='x' ;;
esac

t() { if [ "$lang" = it ]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }
ok() { printf '  %s%s%s %s\n' "$green" "$g_ok" "$off" "$(t "$1" "$2")"; }
note() { printf '  %s%s%s %s\n' "$yellow" "$g_note" "$off" "$(t "$1" "$2")"; }
die() {
	printf '%s%s %s%s\n' "$red" "$g_fail" "$(t "$1" "$2")" "$off" >&2
	exit 1
}
tilde() { case $1 in "$HOME"/*) printf '~%s' "${1#"$HOME"}" ;; *) printf '%s' "$1" ;; esac; }
run() {
	if [ "$dry" = 1 ]; then
		printf '    %s%s%s\n' "$dim" "$*" "$off"
	else
		"$@"
	fi
}

usage() {
	if [ "$lang" = it ]; then
		cat <<'TXT'
Uso: ./install.sh [opzioni]

Installa DRIFT per l'utente corrente. Rieseguilo per aggiornare; non servono
diritti di amministratore né accesso alla rete.

Opzioni:
  --prefix DIR       installa drift in DIR/bin e guide/bridge/schemi in
                     DIR/share/drift (predefinito: ~/.local)
  --skills-dir DIR   cartella delle skill dell'agente
                     (predefinita: ~/.copilot/skills e ~/.agents/skills se presente)
  --no-skill         non installa la skill dell'agente
  --hooks            installa gli hook automatici per gli agenti rilevati
                     (pi, copilot, claude, codex, cursor, gemini)
  --no-hooks         non installa gli hook automatici
  --update-check     installa anche il controllo opzionale delle release GitHub
  --no-update-check  omette o rimuove solo il controllo delle release
  --hooks-dir DIR    installa l'hook automatico in DIR/drift.json
  --maven-repo DIR   repository Maven locale (predefinito: quello di
                     ~/.m2/settings.xml, altrimenti ~/.m2/repository)
  --no-maven         non installa il bridge JUnit e il plugin Maven
  --dry-run          mostra cosa cambierebbe, senza cambiare nulla
  --uninstall        rimuove quanto installato in precedenza
  --lang en|it       lingua dei messaggi (predefinita: da LANG)
  -h, --help         mostra questo aiuto
TXT
	else
		cat <<'TXT'
Usage: ./install.sh [options]

Installs DRIFT for the current user. Run it again to update; it needs no
administrator rights and no network access.

Options:
  --prefix DIR       install drift into DIR/bin and guides/bridges/schemas into
                     DIR/share/drift (default: ~/.local)
  --skills-dir DIR   agent skills directory
                     (default: ~/.copilot/skills and ~/.agents/skills when present)
  --no-skill         do not install the agent skill
  --hooks            install automatic hooks for detected agents
                     (pi, copilot, claude, codex, cursor, gemini)
  --no-hooks         do not install automatic hooks
  --update-check     also install optional GitHub release checks
  --no-update-check  omit or remove only the release-check component
  --hooks-dir DIR    install the automatic hook into DIR/drift.json
  --maven-repo DIR   local Maven repository (default: the one in
                     ~/.m2/settings.xml, else ~/.m2/repository)
  --no-maven         do not install the JUnit bridge and the Maven plugin
  --dry-run          show what would change, change nothing
  --uninstall        remove what a previous install put in place
  --lang en|it       language of messages (default: from LANG)
  -h, --help         show this help
TXT
	fi
}

case $action in
help)
	usage
	exit 0
	;;
bad)
	printf '%s\n\n' "$(t "Unknown or incomplete option: $bad" "Opzione sconosciuta o incompleta: $bad")" >&2
	usage >&2
	exit 2
	;;
esac

if [ "$action" = install ] && [ "$update_yes" = 1 ] && { [ "$update_no" = 1 ] || [ "$no_hooks" = 1 ]; }; then
	die "Conflicting --update-check and --no-update-check/--no-hooks options." \
		"Opzioni --update-check e --no-update-check/--no-hooks in conflitto."
fi

# The installed copy lives in PREFIX/share/drift next to its manifest.
data=$prefix/share/drift
if [ "$prefix_set" = 0 ] && [ -f "$here/manifest" ]; then
	data=$here
fi
manifest=$data/manifest

# Refuses to delete anything whose path does not end as expected.
remove() { # path suffix
	case $1 in
	/ | "" | "$HOME" | "$HOME/") die "Refusing to remove $1" "Rimozione di $1 rifiutata" ;;
	*"$2") ;;
	*) die "Refusing to remove $1: unexpected path" "Rimozione di $1 rifiutata: percorso inatteso" ;;
	esac
	run rm -rf "$1"
}

is_skill() { [ -f "$1/SKILL.md" ] && grep -qE '^name: drift$' "$1/SKILL.md"; }

unmerge_json_hook() { # file
	[ -f "$1" ] || return 0
	[ "$dry" = 0 ] || return 0
	if command -v python3 >/dev/null 2>&1; then
		python3 - "$1" <<'PY' || true
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
try:
    doc = json.loads(p.read_text(encoding='utf-8'))
except Exception:
    sys.exit(0)
hooks = doc.get('hooks')
if not isinstance(hooks, dict):
    sys.exit(0)
changed = False
for k in list(hooks.keys()):
    arr = hooks.get(k)
    if not isinstance(arr, list):
        continue
    kept = []
    for item in arr:
        s = json.dumps(item)
        if 'drift-hook' in s or item.get('_drift') is True:
            changed = True
            continue
        kept.append(item)
    if kept:
        hooks[k] = kept
    else:
        del hooks[k]
        changed = True
if changed:
    p.write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')
PY
	fi
}

# ---------------------------------------------------------------- uninstall
if [ "$action" = uninstall ]; then
	printf '%sDRIFT%s %s\n' "$bold" "$off" "$(t 'uninstall' 'disinstallazione')"
	[ "$dry" = 0 ] || note 'Dry run: nothing changes.' 'Prova: non cambia nulla.'
	[ -f "$manifest" ] || die "Nothing to uninstall: no manifest at $(tilde "$manifest"). Installed with --prefix? Pass the same --prefix." \
		"Niente da disinstallare: manca il manifest $(tilde "$manifest"). Installato con --prefix? Ripeti lo stesso --prefix."
	while IFS=$tab read -r kind path; do
		case $kind in
		bin)
			if [ -f "$path" ]; then
				bname=${path##*/}
				case $bname in
				drift | drift-pro | drift-enterprise) remove "$path" "/$bname" ;;
				esac
				ok "removed $(tilde "$path")" "rimosso $(tilde "$path")"
			fi
			;;
		skill)
			if is_skill "$path"; then
				sname=${path##*/}
				case $sname in
				drift) remove "$path" "/$sname" ;;
				esac
				[ "$dry" = 1 ] || rmdir "${path%/*}" "${path%/*/*}" 2>/dev/null || true
				ok "removed $(tilde "$path")" "rimossa $(tilde "$path")"
			fi
			;;
		hook)
			if [ -f "$path" ] || [ -L "$path" ]; then
				case $path in
				*/drift.json) remove "$path" /drift.json ;;
				*/drift.ts) remove "$path" /drift.ts ;;
				*/hooks.json) remove "$path" /hooks.json ;;
				*/settings.json) remove "$path" /settings.json ;;
				*) die "Refusing to remove unexpected hook file $path" "Rimozione del file hook inatteso $path rifiutata" ;;
				esac
				[ "$dry" = 1 ] || rmdir "${path%/*}" "${path%/*/*}" "${path%/*/*/*}" 2>/dev/null || true
				ok "removed $(tilde "$path")" "rimosso $(tilde "$path")"
			fi
			;;
		hook-merge)
			if [ -f "$path" ]; then
				unmerge_json_hook "$path"
				ok "removed DRIFT hook entry from $(tilde "$path")" "rimossa la voce hook DRIFT da $(tilde "$path")"
			fi
			;;
		maven)
			if [ -d "$path" ]; then
				# Older manifests tracked the version directory; remove only
				# the bridge files, never unrelated Maven metadata.
				v=${path##*/}
				for ext in jar pom; do
					f=$path/drift-junit-$v.$ext
					if [ -f "$f" ]; then
						remove "$f" "/io/github/rad-ox/drift-junit/$v/drift-junit-$v.$ext"
					fi
				done
				[ "$dry" = 1 ] || rmdir "$path" "${path%/*}" "${path%/*/*}" "${path%/*/*/*}" "${path%/*/*/*/*}" 2>/dev/null || true
				ok "removed DRIFT artifacts in $(tilde "$path")" "rimossi gli artefatti DRIFT in $(tilde "$path")"
			elif [ -f "$path" ]; then
				v=${path%/*}
				v=${v##*/}
				a=${path%/*/*}
				a=${a##*/}
				case $a:${path##*/} in
				drift-junit:"drift-junit-$v.jar" | drift-junit:"drift-junit-$v.pom") ;;
				drift-maven-plugin:"drift-maven-plugin-$v.jar" | drift-maven-plugin:"drift-maven-plugin-$v.pom") ;;
				*) die "Refusing to remove unexpected Maven artifact $path" "Rimozione dell'artefatto Maven inatteso $path rifiutata" ;;
				esac
				remove "$path" "/io/github/rad-ox/$a/$v/${path##*/}"
				[ "$dry" = 1 ] || rmdir "${path%/*}" "${path%/*/*}" "${path%/*/*/*}" "${path%/*/*/*/*}" "${path%/*/*/*/*/*}" 2>/dev/null || true
				ok "removed $(tilde "$path")" "rimosso $(tilde "$path")"
			fi
			;;
		esac
	done <"$manifest"
	remove "$data" /drift
	ok "removed $(tilde "$data")" "rimosso $(tilde "$data")"
	printf '%s\n' "$(t 'DRIFT is uninstalled. Your contracts and projects are untouched.' \
		'DRIFT è disinstallato. Contratti e progetti non sono stati toccati.')"
	exit 0
fi

# ------------------------------------------------------------------ install
if [ ! -x "$here/bin/drift" ] && [ -f "$here/VERSION" ]; then
	v_dl=$(sed -n '1p' "$here/VERSION")
	dl_os=$(uname -s)
	dl_arch=$(uname -m)
	case "$dl_os:$dl_arch" in
	Linux:x86_64 | Linux:amd64) dl_plat="linux-x64" ;;
	Darwin:arm64 | Darwin:aarch64) dl_plat="macos-arm64" ;;
	Darwin:x86_64) dl_plat="macos-x64" ;;
	*) die "Unsupported platform for automatic download: $dl_os $dl_arch" "Piattaforma non supportata per il download automatico: $dl_os $dl_arch" ;;
	esac
	pkg_n="drift-${v_dl}-${dl_plat}"
	base_u="https://github.com/rad-ox/drift/releases/download/v${v_dl}"
	note "Downloading ${pkg_n}.tar.gz from GitHub Releases..." "Scaricamento ${pkg_n}.tar.gz da GitHub Releases..."
	tmp_d=$(mktemp -d "${TMPDIR:-/tmp}/drift-dl.XXXXXX")
	curl -fsSL "$base_u/${pkg_n}.tar.gz" -o "$tmp_d/${pkg_n}.tar.gz"
	curl -fsSL "$base_u/SHA256SUMS" -o "$tmp_d/SHA256SUMS"
	(cd "$tmp_d" && grep "  ${pkg_n}\.tar\.gz$" SHA256SUMS > SHA256SUMS.one && (sha256sum --quiet -c SHA256SUMS.one 2>/dev/null || shasum -a 256 --status -c SHA256SUMS.one)) || { rm -rf "$tmp_d"; die "Downloaded archive failed SHA256SUMS verification." "Verifica SHA256SUMS dell'archivio scaricato fallita."; }
	tar -xzf "$tmp_d/${pkg_n}.tar.gz" -C "$here" --strip-components=1 "${pkg_n}/bin" "${pkg_n}/maven" 2>/dev/null || tar -xzf "$tmp_d/${pkg_n}.tar.gz" -C "$here" --strip-components=1 "${pkg_n}/bin"
	rm -rf "$tmp_d"
fi
if [ ! -x "$here/bin/drift" ] || [ ! -f "$here/VERSION" ]; then
	die "Run the installer from the extracted release package (bin/drift is missing here)." \
		"Esegui l'installer dal pacchetto estratto (qui manca bin/drift)."
fi
version=$(sed -n '1p' "$here/VERSION")

os=$(uname -s)
arch=$(uname -m)
case "$os:$arch" in
Linux:x86_64 | Linux:amd64 | Darwin:arm64 | Darwin:aarch64 | Darwin:x86_64) ;;
*)
	die "This package is for Linux x86-64 or macOS (arm64/x86-64), not $os $arch. See INSTALL.md to build from source." \
		"Questo pacchetto è per Linux x86-64 o macOS (arm64/x86-64), non $os $arch. Per compilare dai sorgenti vedi INSTALL.it.md."
	;;
esac
if [ -f "$here/SHA256SUMS" ] && [ -d "$here/skill" ]; then
	if command -v sha256sum >/dev/null 2>&1; then
		(cd "$here" && sha256sum --quiet -c SHA256SUMS) ||
			die "Package integrity check failed (SHA256SUMS); re-extract or download the archive again." \
				"Verifica di integrità del pacchetto fallita (SHA256SUMS); estrai o scarica di nuovo l'archivio."
	elif command -v shasum >/dev/null 2>&1; then
		(cd "$here" && shasum -a 256 --status -c SHA256SUMS) ||
			die "Package integrity check failed (SHA256SUMS); re-extract or download the archive again." \
				"Verifica di integrità del pacchetto fallita (SHA256SUMS); estrai o scarica di nuovo l'archivio."
	fi
fi

if [ -z "$maven_repo" ]; then
	maven_repo=$HOME/.m2/repository
	settings=$HOME/.m2/settings.xml
	if [ -f "$settings" ]; then
		v=$(awk '{ s = s $0 "\n" }
			END {
				while ((i = index(s, "<!--")) > 0) {
					j = index(substr(s, i), "-->")
					if (j == 0) { s = substr(s, 1, i - 1); break }
					s = substr(s, 1, i - 1) substr(s, i + j + 2)
				}
				if (match(s, /<localRepository>[^<]*<\/localRepository>/)) {
					v = substr(s, RSTART + 17, RLENGTH - 35)
					gsub(/^[ \t\r\n]+|[ \t\r\n]+$/, "", v)
					print v
				}
			}' "$settings")
		if [ -n "$v" ]; then
			# shellcheck disable=SC2016 # Maven placeholders, not shell expansions
			case $v in
			'${user.home}'* | '${env.HOME}'*) v=$HOME${v#*\}} ;;
			esac
			maven_repo=$v
		fi
	fi
fi

bindir=$prefix/bin
artifacts='drift-junit drift-maven-plugin'
mdir=$maven_repo/io/github/rad-ox/drift-junit/$version
mfile() { printf '%s/io/github/rad-ox/%s/%s/%s-%s.%s' "$maven_repo" "$1" "$version" "$1" "$version" "$2"; } # artifact ext
# Maven files this installer owns, tab-separated: only those are replaced and
# recorded; an identical file that was already there stays the user's.
owned=
owns() { case $tab$owned in *"$tab$1$tab"*) return 0 ;; esac; return 1; }
own() { owns "$1" || owned=$owned$1$tab; }
old=
if [ -x "$bindir/drift" ]; then
	old=$("$bindir/drift" version 2>/dev/null | sed -n 's/^drift \([^ ]*\).*/\1/p') || old=
fi

printf '%sDRIFT %s%s  %s\n' "$bold" "$version" "$off" "$(
	if [ -z "$old" ]; then
		t 'install' 'installazione'
	elif [ "$old" = "$version" ]; then
		t 'reinstall' 'reinstallazione'
	else
		t "update from $old" "aggiornamento da $old"
	fi
)"
[ "$dry" = 0 ] || note 'Dry run: nothing changes; these are the steps.' 'Prova: non cambia nulla; ecco i passi.'

# Entries of a previous install: paths that move are cleaned up, Maven
# versions are kept because projects may pin them.
old_skills='' old_bin='' old_mavens='' old_hooks='' old_hook_merges=''
if [ -f "$manifest" ]; then
	while IFS=$tab read -r kind path; do
		case $kind in
		bin) old_bin=$path ;;
		skill) old_skills="$old_skills$path$tab" ;;
		hook)
			old_hooks="$old_hooks$path$tab"
			[ "$hooks_set" = 1 ] || with_hooks=1
			;;
		hook-merge)
			old_hook_merges="$old_hook_merges$path$tab"
			[ "$hooks_set" = 1 ] || with_hooks=1
			;;
		maven)
			current=0
			for a in $artifacts; do
				for ext in jar pom; do
					if [ "$path" = "$(mfile "$a" "$ext")" ]; then
						current=1
						[ "$with_maven" = 0 ] || own "$path"
					fi
				done
			done
			# Older manifests tracked the bridge's version directory.
			if [ "$path" = "$mdir" ]; then
				current=1
				if [ "$with_maven" = 1 ]; then
					own "$(mfile drift-junit jar)"
					own "$(mfile drift-junit pom)"
				fi
			fi
			if [ "$with_maven" = 0 ] || [ "$current" = 0 ]; then
				[ -e "$path" ] || continue
				old_mavens="$old_mavens$path$tab"
			fi
			;;
		esac
	done <"$manifest"
fi

if [ "$with_maven" = 1 ]; then
	for a in $artifacts; do
		for ext in jar pom; do
			target=$(mfile "$a" "$ext")
			source=$here/maven/$a-$version.$ext
			if [ -e "$target" ] || [ -L "$target" ]; then
				[ -f "$target" ] || die "Maven artifact path is not a file: $target" "Il percorso dell'artefatto Maven non è un file: $target"
				if ! owns "$target" && ! cmp -s "$source" "$target"; then
					die "A different Maven artifact already exists at $target; back it up or use --maven-repo DIR." \
						"Esiste già un artefatto Maven diverso in $target; fanne una copia o usa --maven-repo DIR."
				fi
			fi
		done
	done
fi

run mkdir -p "$bindir"
new_bins=''
for bname in drift drift-pro drift-enterprise; do
	[ -x "$here/bin/$bname" ] || continue
	if [ -e "$bindir/.$bname.new" ] || [ -L "$bindir/.$bname.new" ]; then
		remove "$bindir/.$bname.new" "/.$bname.new"
	fi
	run cp "$here/bin/$bname" "$bindir/.$bname.new"
	run chmod 0755 "$bindir/.$bname.new"
	run mv -f "$bindir/.$bname.new" "$bindir/$bname"
	new_bins="$new_bins$bindir/$bname$tab"
	ok "$bname $version → $(tilde "$bindir/$bname")" "$bname $version → $(tilde "$bindir/$bname")"
done
if [ -n "$old_bin" ] && [ "$old_bin" != "$bindir/drift" ] && [ -f "$old_bin" ]; then
	remove "$old_bin" /drift
fi

run mkdir -p "$data"
remove "$data/example" /example
run cp -R "$here/example" "$data/example"
if [ -d "$here/bridges" ]; then
	remove "$data/bridges" /bridges
	run cp -R "$here/bridges" "$data/bridges"
	ok "JS and Python bridges → $(tilde "$data/bridges")" "bridge JS e Python → $(tilde "$data/bridges")"
fi
if [ -d "$here/schemas" ]; then
	remove "$data/schemas" /schemas
	run cp -R "$here/schemas" "$data/schemas"
fi
if [ -d "$here/hooks" ]; then
	run mkdir -p "$data/hooks"
	run cp "$here/hooks/drift-hook.sh" "$here/hooks/drift-hook.ps1" "$here/hooks/drift-pi.ts" "$data/hooks/"
	[ ! -f "$here/hooks/drift-notify-wsl.sh" ] || run cp "$here/hooks/drift-notify-wsl.sh" "$data/hooks/"
	run chmod 0755 "$data/hooks/drift-hook.sh"
	[ ! -f "$data/hooks/drift-notify-wsl.sh" ] || run chmod 0755 "$data/hooks/drift-notify-wsl.sh"
fi
for f in install.sh VERSION INSTALL.md INSTALL.it.md SHA256SUMS; do
	[ ! -f "$here/$f" ] || run cp "$here/$f" "$data/$f"
done

install_skill_dir() { # target_skills_root
	for sname in drift; do
		[ -d "$here/skill/$sname" ] || continue
		target_skill=$1/$sname
		if [ -L "$target_skill" ]; then
			note "replacing the development link $(tilde "$target_skill")" "sostituisco il link di sviluppo $(tilde "$target_skill")"
			run rm -f "$target_skill"
		fi
		run mkdir -p "$1"
		remove "$1/.$sname.new" "/.$sname.new"
		run cp -R "$here/skill/$sname" "$1/.$sname.new"
		remove "$target_skill" "/$sname"
		run mv "$1/.$sname.new" "$target_skill"
		new_skills="$new_skills$target_skill$tab"
		ok "agent skill → $(tilde "$target_skill")" "skill dell'agente → $(tilde "$target_skill")"
	done
}

# Detect existing vendor-agnostic and agent directories in HOME.
pi_dir=${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}
detected_agents=''
[ ! -d "$HOME/.agents" ] || detected_agents="${detected_agents}agents "
if [ -d "$HOME/.pi" ] || [ -d "$pi_dir" ]; then detected_agents="${detected_agents}pi "; fi
[ ! -d "$HOME/.copilot" ] || detected_agents="${detected_agents}copilot "
[ ! -d "$HOME/.claude" ] || detected_agents="${detected_agents}claude "
[ ! -d "$HOME/.codex" ] || detected_agents="${detected_agents}codex "
[ ! -d "$HOME/.cursor" ] || detected_agents="${detected_agents}cursor "
[ ! -d "$HOME/.gemini" ] || detected_agents="${detected_agents}gemini "
detected_agents=${detected_agents% }

if [ "$hooks_set" = 0 ] && [ "$dry" = 0 ]; then
	if { [ -t 0 ] && [ -t 1 ]; } || [ "${DRIFT_ASSUME_TTY:-0}" = 1 ]; then
		agent_label=${detected_agents:-pi, copilot, agents}
		printf '  %s?%s %s ' "$yellow" "$off" "$(t "Install automatic DRIFT hooks for agents ($agent_label)? [Y/n]" \
			"Installare gli hook automatici di DRIFT per gli agenti ($agent_label)? [S/n]")"
		ans=''
		read -r ans || ans=''
		case $ans in
		"" | [Yy] | [Yy][Ee][Ss] | [Ss] | [Ss][Ii] | [Ss][Ìì]) with_hooks=1 ;;
		*) with_hooks=0 ;;
		esac
	fi
fi

if [ "$with_hooks" = 0 ]; then update_check=0; fi
sh "$here/release-component.sh" "$here/release" "$data/hooks/release" "$update_check" "$lang" "$dry"

new_skills=''
if [ "$with_skill" = 1 ]; then
	install_skill_dir "$skills"
	if [ "$skills_set" = 0 ]; then
		if [ -d "$HOME/.agents" ] || [ -d "$HOME/.pi" ] || [ -d "$pi_dir" ] || [ -d "$HOME/.codex" ] || [ -d "$HOME/.cursor" ] || [ "$with_hooks" = 1 ]; then
			if [ "$skills" != "$HOME/.agents/skills" ]; then
				install_skill_dir "$HOME/.agents/skills"
			fi
		fi
		if [ -d "$HOME/.claude" ] && [ "$skills" != "$HOME/.claude/skills" ]; then
			install_skill_dir "$HOME/.claude/skills"
		fi
	fi
fi
if [ -n "$old_skills" ]; then
	saved_ifs=$IFS
	IFS=$tab
	for s_old in $old_skills; do
		[ -n "$s_old" ] || continue
		case $tab$new_skills in
		*"$tab$s_old$tab"*) ;;
		*)
			if is_skill "$s_old"; then
				sname_old=${s_old##*/}
				case $sname_old in
				drift) remove "$s_old" "/$sname_old" ;;
				esac
				[ "$dry" = 1 ] || rmdir "${s_old%/*}" "${s_old%/*/*}" 2>/dev/null || true
				ok "removed the previous skill $(tilde "$s_old")" "rimossa la skill precedente $(tilde "$s_old")"
			fi
			;;
		esac
	done
	IFS=$saved_ifs
fi

write_dropin_hook() { # target_file
	run mkdir -p "${1%/*}"
	if [ "$dry" = 0 ]; then
		cat >"$1.new" <<JSON
{
  "version": 1,
  "hooks": {
    "sessionStart": [
      {
        "type": "command",
        "bash": "$data/hooks/drift-hook.sh session",
        "command": "$data/hooks/drift-hook.sh session",
        "powershell": "powershell -NoProfile -ExecutionPolicy Bypass -Command \"& \\\"\\\$env:LOCALAPPDATA\\\\Programs\\\\drift\\\\hooks\\\\drift-hook.ps1\\\" -Mode session\"",
        "timeoutSec": 5
      }
    ],
    "userPromptSubmitted": [
      {
        "type": "command",
        "bash": "$data/hooks/drift-hook.sh prompt",
        "command": "$data/hooks/drift-hook.sh prompt",
        "powershell": "powershell -NoProfile -ExecutionPolicy Bypass -Command \"& \\\"\\\$env:LOCALAPPDATA\\\\Programs\\\\drift\\\\hooks\\\\drift-hook.ps1\\\" -Mode prompt\"",
        "timeoutSec": 5
      }
    ],
    "agentStop": [
      {
        "type": "command",
        "bash": "$data/hooks/drift-hook.sh stop",
        "command": "$data/hooks/drift-hook.sh stop",
        "powershell": "powershell -NoProfile -ExecutionPolicy Bypass -Command \"& \\\"\\\$env:LOCALAPPDATA\\\\Programs\\\\drift\\\\hooks\\\\drift-hook.ps1\\\" -Mode stop\"",
        "timeoutSec": 10
      }
    ],
    "notification": [
      {
        "type": "command",
        "bash": "$data/hooks/drift-hook.sh notify",
        "command": "$data/hooks/drift-hook.sh notify",
        "powershell": "powershell -NoProfile -ExecutionPolicy Bypass -Command \"& \\\"\\\$env:LOCALAPPDATA\\\\Programs\\\\drift\\\\hooks\\\\drift-hook.ps1\\\" -Mode notify\"",
        "timeoutSec": 5
      }
    ]
  }
}
JSON
		mv -f "$1.new" "$1"
	fi
	new_hooks="$new_hooks$1$tab"
	ok "agent hook → $(tilde "$1")" "hook dell'agente → $(tilde "$1")"
}

write_or_merge_shared_hook() { # target_file
	if [ ! -f "$1" ]; then
		run mkdir -p "${1%/*}"
		if [ "$dry" = 0 ]; then
			cat >"$1.new" <<JSON
{
  "hooks": {
    "SessionStart": [
      {
        "_drift": true,
        "hooks": [
          {
            "type": "command",
            "command": "$data/hooks/drift-hook.sh session",
            "commandWindows": "powershell -NoProfile -ExecutionPolicy Bypass -Command \"& \\\"\\\$env:LOCALAPPDATA\\\\Programs\\\\drift\\\\hooks\\\\drift-hook.ps1\\\" -Mode session\"",
            "timeout": 5
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "_drift": true,
        "hooks": [
          {
            "type": "command",
            "command": "$data/hooks/drift-hook.sh prompt",
            "commandWindows": "powershell -NoProfile -ExecutionPolicy Bypass -Command \"& \\\"\\\$env:LOCALAPPDATA\\\\Programs\\\\drift\\\\hooks\\\\drift-hook.ps1\\\" -Mode prompt\"",
            "timeout": 5
          }
        ]
      }
    ],
    "Stop": [
      {
        "_drift": true,
        "hooks": [
          {
            "type": "command",
            "command": "$data/hooks/drift-hook.sh stop",
            "commandWindows": "powershell -NoProfile -ExecutionPolicy Bypass -Command \"& \\\"\\\$env:LOCALAPPDATA\\\\Programs\\\\drift\\\\hooks\\\\drift-hook.ps1\\\" -Mode stop\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
JSON
			mv -f "$1.new" "$1"
		fi
		new_hooks="$new_hooks$1$tab"
		ok "agent hook → $(tilde "$1")" "hook dell'agente → $(tilde "$1")"
		return 0
	fi
	case $tab$old_hooks in
	*"$tab$1$tab"*)
		new_hooks="$new_hooks$1$tab"
		ok "agent hook → $(tilde "$1")" "hook dell'agente → $(tilde "$1")"
		return 0
		;;
	esac
	if [ "$dry" = 0 ] && command -v python3 >/dev/null 2>&1; then
		python3 - "$1" "$data/hooks/drift-hook.sh" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
hook_sh = sys.argv[2]
try:
    doc = json.loads(p.read_text(encoding='utf-8'))
except Exception:
    sys.exit(0)
if not isinstance(doc, dict):
    sys.exit(0)
hooks = doc.setdefault('hooks', {})
if not isinstance(hooks, dict):
    sys.exit(0)
win_cmd = r'powershell -NoProfile -ExecutionPolicy Bypass -Command "& \"$env:LOCALAPPDATA\Programs\drift\hooks\drift-hook.ps1\"'
for ev, mode, tmo in [('SessionStart', 'session', 5), ('UserPromptSubmit', 'prompt', 5), ('Stop', 'stop', 10)]:
    arr = hooks.setdefault(ev, [])
    if not isinstance(arr, list):
        continue
    arr[:] = [x for x in arr if 'drift-hook' not in json.dumps(x) and (not isinstance(x, dict) or x.get('_drift') is not True)]
    arr.append({
        '_drift': True,
        'hooks': [{
            'type': 'command',
            'command': f'{hook_sh} {mode}',
            'commandWindows': f'{win_cmd} -Mode {mode}"',
            'timeout': tmo,
        }],
    })
p.write_text(json.dumps(doc, indent=2) + '\n', encoding='utf-8')
PY
	fi
	new_hook_merges="$new_hook_merges$1$tab"
	ok "agent hook entry → $(tilde "$1")" "voce hook dell'agente → $(tilde "$1")"
}

stage_pi_extension() {
	if [ -d "$data/hooks/release" ]; then
		python3 "$here/configure-pi.py" "$here/hooks/drift-pi.ts" "$1" "$data/hooks/release"
	else
		cp "$here/hooks/drift-pi.ts" "$1"
	fi
}

new_hooks='' new_hook_merges=''
if [ "$with_hooks" = 1 ] && [ -d "$here/hooks" ]; then
	if [ -n "$hooks_dir" ]; then
		write_dropin_hook "$hooks_dir/drift.json"
	else
		any_agent=0
		if [ -d "$HOME/.pi" ] || [ -d "$pi_dir" ]; then
			any_agent=1
			pi_ext=$pi_dir/extensions/drift.ts
			run mkdir -p "${pi_ext%/*}"
			[ "$dry" = 1 ] || stage_pi_extension "$pi_ext.new"
			[ "$dry" = 1 ] || mv -f "$pi_ext.new" "$pi_ext"
			new_hooks="$new_hooks$pi_ext$tab"
			ok "Pi extension → $(tilde "$pi_ext")" "estensione Pi → $(tilde "$pi_ext")"
		fi
		if [ -d "$HOME/.copilot" ]; then
			any_agent=1
			write_dropin_hook "$HOME/.copilot/hooks/drift.json"
		fi
		if [ -d "$HOME/.cursor" ]; then
			any_agent=1
			write_dropin_hook "$HOME/.cursor/hooks/drift.json"
		fi
		if [ -d "$HOME/.codex" ]; then
			any_agent=1
			write_or_merge_shared_hook "$HOME/.codex/hooks.json"
		fi
		if [ -d "$HOME/.claude" ]; then
			any_agent=1
			write_or_merge_shared_hook "$HOME/.claude/settings.json"
		fi
		if [ -d "$HOME/.gemini" ]; then
			any_agent=1
			write_or_merge_shared_hook "$HOME/.gemini/settings.json"
		fi
		if [ "$any_agent" = 0 ]; then
			pi_ext=$pi_dir/extensions/drift.ts
			run mkdir -p "${pi_ext%/*}"
			[ "$dry" = 1 ] || stage_pi_extension "$pi_ext.new"
			[ "$dry" = 1 ] || mv -f "$pi_ext.new" "$pi_ext"
			new_hooks="$new_hooks$pi_ext$tab"
			ok "Pi extension → $(tilde "$pi_ext")" "estensione Pi → $(tilde "$pi_ext")"
			write_dropin_hook "$HOME/.copilot/hooks/drift.json"
		fi
	fi
fi
if [ -n "$old_hooks" ]; then
	saved_ifs=$IFS
	IFS=$tab
	for h_old in $old_hooks; do
		[ -n "$h_old" ] || continue
		case $tab$new_hooks in
		*"$tab$h_old$tab"*) ;;
		*)
			if [ -f "$h_old" ] || [ -L "$h_old" ]; then
				case $h_old in
				*/drift.json) remove "$h_old" /drift.json ;;
				*/drift.ts) remove "$h_old" /drift.ts ;;
				*/hooks.json) remove "$h_old" /hooks.json ;;
				*/settings.json) remove "$h_old" /settings.json ;;
				esac
				[ "$dry" = 1 ] || rmdir "${h_old%/*}" "${h_old%/*/*}" "${h_old%/*/*/*}" 2>/dev/null || true
				ok "removed the previous hook $(tilde "$h_old")" "rimosso l'hook precedente $(tilde "$h_old")"
			fi
			;;
		esac
	done
	IFS=$saved_ifs
fi
if [ -n "$old_hook_merges" ]; then
	saved_ifs=$IFS
	IFS=$tab
	for hm_old in $old_hook_merges; do
		[ -n "$hm_old" ] || continue
		case $tab$new_hook_merges in
		*"$tab$hm_old$tab"*) ;;
		*)
			if [ -f "$hm_old" ]; then
				unmerge_json_hook "$hm_old"
				ok "removed DRIFT hook entry from $(tilde "$hm_old")" "rimossa la voce hook DRIFT da $(tilde "$hm_old")"
			fi
			;;
		esac
	done
	IFS=$saved_ifs
fi

if [ "$with_maven" = 1 ]; then
	for a in $artifacts; do
		run mkdir -p "$maven_repo/io/github/rad-ox/$a/$version"
		for ext in jar pom; do
			target=$(mfile "$a" "$ext")
			source=$here/maven/$a-$version.$ext
			if [ ! -e "$target" ] || { owns "$target" && ! cmp -s "$source" "$target"; }; then
				if [ -e "$target.new" ] || [ -L "$target.new" ]; then
					remove "$target.new" "/io/github/rad-ox/$a/$version/$a-$version.$ext.new"
				fi
				run cp "$source" "$target.new"
				run mv -f "$target.new" "$target"
				own "$target"
			fi
		done
	done
	ok "JUnit bridge io.github.rad-ox:drift-junit:$version → $(tilde "$mdir")" \
		"bridge JUnit io.github.rad-ox:drift-junit:$version → $(tilde "$mdir")"
	ok "Maven plugin io.github.rad-ox:drift-maven-plugin:$version → $(tilde "$maven_repo/io/github/rad-ox/drift-maven-plugin/$version")" \
		"plugin Maven io.github.rad-ox:drift-maven-plugin:$version → $(tilde "$maven_repo/io/github/rad-ox/drift-maven-plugin/$version")"
fi

if [ "$dry" = 1 ]; then
	printf '%s\n' "$(t 'Dry run complete: nothing was changed.' 'Prova completata: non è cambiato nulla.')"
	exit 0
fi

{
	printf 'version\t%s\n' "$version"
	printf '%s' "$new_bins" | tr '\t' '\n' | sed '/^$/d; s/^/bin\t/'
	printf '%s' "$new_skills" | tr '\t' '\n' | sed '/^$/d; s/^/skill\t/'
	printf '%s' "$new_hooks" | tr '\t' '\n' | sed '/^$/d; s/^/hook\t/'
	printf '%s' "$new_hook_merges" | tr '\t' '\n' | sed '/^$/d; s/^/hook-merge\t/'
	for a in $artifacts; do
		for ext in jar pom; do
			if owns "$(mfile "$a" "$ext")"; then printf 'maven\t%s\n' "$(mfile "$a" "$ext")"; fi
		done
	done
	printf '%s' "$old_mavens" | tr '\t' '\n' | sed '/^$/d; s/^/maven\t/'
} >"$manifest.new"
mv -f "$manifest.new" "$manifest"

if [ -n "${WSL_DISTRO_NAME:-}" ] || grep -qsi microsoft /proc/version 2>/dev/null; then
	note 'WSL detected: Linux binary and WSL paths are installed; run install.cmd on Windows if you also run agents natively on Windows' \
		'Rilevato WSL: installati binario Linux e percorsi WSL; esegui install.cmd su Windows se usi agenti anche su Windows nativo'
fi

# ---- verification and environment
got=$("$bindir/drift" version 2>&1) || got=
case $got in
"drift $version"*) ;;
*) die "The installed drift does not run: $got" "Il drift installato non parte: $got" ;;
esac
if "$bindir/drift" check "$data/example/.drift" >/dev/null 2>&1; then
	ok 'self-test: drift checks the bundled example' 'autotest: drift verifica l'"'"'esempio incluso'
else
	die 'self-test failed: drift check of the bundled example' 'autotest fallito: drift check sull'"'"'esempio incluso'
fi

java_major=
if command -v java >/dev/null 2>&1; then
	jv=$(java -version 2>&1 | sed -n 's/.*version "\([^"]*\)".*/\1/p' | sed -n '1p') || jv=
	case $jv in
	1.*) java_major=${jv#1.} java_major=${java_major%%.*} ;;
	*) java_major=${jv%%[.+-]*} ;;
	esac
fi
mvn_version=
if command -v mvn >/dev/null 2>&1; then
	mvn_version=$(mvn -v 2>/dev/null | sed -n '1s/.*Maven \([0-9][0-9.]*\).*/\1/p') || mvn_version=
fi
if [ "$with_maven" = 1 ]; then
	if [ -z "$java_major" ]; then
		note 'Java not found: the JUnit bridge needs JDK 17+ (sudo apt install openjdk-21-jdk)' \
			'Java non trovato: il bridge JUnit richiede JDK 17+ (sudo apt install openjdk-21-jdk)'
	elif [ "$java_major" -lt 17 ] 2>/dev/null; then
		note "Java $java_major found: the JUnit bridge needs JDK 17+" "Trovato Java $java_major: il bridge JUnit richiede JDK 17+"
	else
		ok "Java $java_major" "Java $java_major"
	fi
	if [ -z "$mvn_version" ]; then
		note 'Maven not found: needed only to run your tests (sudo apt install maven)' \
			'Maven non trovato: serve solo per eseguire i test (sudo apt install maven)'
	else
		ok "Maven $mvn_version" "Maven $mvn_version"
	fi
fi

case :$PATH: in
*:"$bindir":* | *:"$bindir/":*)
	found=$(command -v drift 2>/dev/null || true)
	if [ -n "$found" ] && [ "$found" != "$bindir/drift" ]; then
		note "another drift comes first on PATH: $found; remove it or move $(tilde "$bindir") before it" \
			"un altro drift viene prima nel PATH: $found; rimuovilo o metti $(tilde "$bindir") prima"
	fi
	use=drift
	;;
*)
	use=$(tilde "$bindir/drift")
	if [ "$bindir" = "$HOME/.local/bin" ] && grep -qs '\.local/bin' "$HOME/.profile"; then
		note "$(tilde "$bindir") enters PATH at your next login; in this terminal run:" \
			"$(tilde "$bindir") entra nel PATH al prossimo login; in questo terminale esegui:"
		printf '      . ~/.profile\n'
	else
		note "$(tilde "$bindir") is not on PATH; add it with:" "$(tilde "$bindir") non è nel PATH; aggiungilo con:"
		# shellcheck disable=SC2016 # $PATH is for the user's shell
		printf '      echo '"'"'export PATH="%s:$PATH"'"'"' >> ~/.bashrc && . ~/.bashrc\n' "$bindir"
	fi
	;;
esac

printf '\n%s\n' "$(t 'Ready. Try:' 'Pronto. Prova:')"
printf '  %s check %s\n' "$use" "$(tilde "$data/example/.drift")"
printf '  %s help\n' "$use"
printf '%s %s\n' "$(t 'Guide:    ' 'Guida:      ')" "$(tilde "$data/$(t INSTALL.md INSTALL.it.md)")"
printf '%s %s --uninstall\n' "$(t 'Uninstall:' 'Rimozione:  ')" "$(tilde "$data/install.sh")"
