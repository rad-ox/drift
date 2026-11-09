#!/bin/sh
# Install only the optional component, also used by source installations.
set -eu
source_dir=$1 target=$2 choice=${3:-} lang=${4:-en} dry=${5:-0}
case $target in
/*/hooks/release) ;;
*) echo 'drift: invalid release component destination' >&2; exit 2 ;;
esac
case $choice in
'' | 0 | 1) ;;
*) echo 'drift: UPDATE_CHECK must be 0 or 1' >&2; exit 2 ;;
esac
if [ -z "$choice" ]; then
	if [ "$dry" = 0 ] && { { [ -t 0 ] && [ -t 1 ]; } || [ "${DRIFT_ASSUME_TTY:-0}" = 1 ]; }; then
		if [ "$lang" = it ]; then
			printf '  ? Installare il controllo opzionale delle release GitHub a inizio sessione? [S/n] '
		else
			printf '  ? Install optional GitHub release checks at session start? [Y/n] '
		fi
		if ! IFS= read -r answer; then
			echo 'drift: no installation answer; preserving the existing release-check choice' >&2
			choice=keep
		else
			case $answer in
			'' | [Yy] | [Yy][Ee][Ss] | [Ss] | [Ss][Ii]) choice=1 ;;
			*) choice=0 ;;
			esac
		fi
	else
		choice=keep
	fi
fi
if [ "$choice" = keep ]; then
	if [ -d "$target" ]; then choice=1; else choice=0; fi
fi
if [ "$dry" = 1 ]; then
	printf '    release check component: %s (%s)\n' "$choice" "$target"
elif [ "$choice" = 1 ]; then
	mkdir -p "$target"
	cp "$source_dir/check.py" "$source_dir/check.ps1" "$source_dir/release-policy.json" "$target/"
else
	for file in check.py check.ps1 release-policy.json; do
		rm -f "$target/$file"
	done
	if [ -d "$target" ]; then rmdir "$target"; fi
fi
