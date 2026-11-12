#!/bin/sh
# Downloads, SHA-256-verifies, and installs the matching DRIFT Free release
# package for Linux (x86_64) or macOS (arm64 / x86_64) when the skill was
# installed standalone (e.g. via `npx skills add rad-ox/drift`).
set -eu

DEFAULT_VERSION="0.6.0"
REPO="${DRIFT_GITHUB_REPO:-rad-ox/drift}"
force=0
custom_prefix=""
prev=""

for arg in "$@"; do
	if [ "$prev" = "--prefix" ]; then
		custom_prefix=$arg
		prev=""
		continue
	fi
	case "$arg" in
	-h | --help)
		cat <<'EOF'
Usage: sh scripts/install-cli.sh [--force] [install.sh options...]

Downloads, verifies (SHA256SUMS), and installs the matching DRIFT release binary
and bridges for Linux (x86_64) or macOS (arm64 / x86_64) from GitHub Releases.
Additional options (--prefix DIR, --no-maven, --hooks, --dry-run, ...) are
forwarded to the release package's install.sh with --no-skill.
EOF
		exit 0
		;;
	--force)
		force=1
		;;
	--prefix)
		prev="--prefix"
		;;
	--prefix=*)
		custom_prefix=${arg#--prefix=}
		;;
	esac
done

n=$#
i=0
while [ "$i" -lt "$n" ]; do
	arg=$1
	shift
	if [ "$arg" != "--force" ]; then
		set -- "$@" "$arg"
	fi
	i=$((i + 1))
done

if [ "$force" = 0 ]; then
	if [ -n "$custom_prefix" ]; then
		if [ -x "$custom_prefix/bin/drift" ]; then
			"$custom_prefix/bin/drift" version
			exit 0
		fi
	elif command -v drift >/dev/null 2>&1; then
		drift version
		exit 0
	elif [ -x "${HOME:-}/.local/bin/drift" ]; then
		"$HOME/.local/bin/drift" version
		exit 0
	fi
fi

here=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
ver=${DRIFT_VERSION:-}
if [ -z "$ver" ]; then
	if [ -f "$here/../../../VERSION" ]; then
		ver=$(sed -n '1p' "$here/../../../VERSION" | tr -d '\r\n')
	elif [ -f "$here/../../VERSION" ]; then
		ver=$(sed -n '1p' "$here/../../VERSION" | tr -d '\r\n')
	else
		ver=$DEFAULT_VERSION
	fi
fi

os=$(uname -s)
arch=$(uname -m)
case "$os:$arch" in
Linux:x86_64 | Linux:amd64) plat="linux-x64" ;;
Darwin:arm64 | Darwin:aarch64) plat="macos-arm64" ;;
Darwin:x86_64) plat="macos-x64" ;;
*)
	printf 'drift: unsupported platform for automatic download: %s %s\n' "$os" "$arch" >&2
	exit 1
	;;
esac

pkg_n="drift-${ver}-${plat}"
base_u=${DRIFT_RELEASE_BASE_URL:-"https://github.com/${REPO}/releases/download/v${ver}"}
tmp_d=$(mktemp -d "${TMPDIR:-/tmp}/drift-cli-dl.XXXXXX")
trap 'rm -rf "$tmp_d"' EXIT INT TERM

curl -fsSL "$base_u/${pkg_n}.tar.gz" -o "$tmp_d/${pkg_n}.tar.gz"
curl -fsSL "$base_u/SHA256SUMS" -o "$tmp_d/SHA256SUMS"
(
	cd "$tmp_d"
	grep "  ${pkg_n}\\.tar\\.gz$" SHA256SUMS >SHA256SUMS.one
	if command -v sha256sum >/dev/null 2>&1; then
		sha256sum --quiet -c SHA256SUMS.one
	elif command -v shasum >/dev/null 2>&1; then
		shasum -a 256 --status -c SHA256SUMS.one
	else
		printf 'drift: neither sha256sum nor shasum found to verify %s.tar.gz\n' "$pkg_n" >&2
		exit 1
	fi
) || {
	printf 'drift: downloaded archive %s.tar.gz failed SHA256SUMS verification\n' "$pkg_n" >&2
	exit 1
}

tar -xzf "$tmp_d/${pkg_n}.tar.gz" -C "$tmp_d"
"$tmp_d/${pkg_n}/install.sh" --no-skill "$@"
