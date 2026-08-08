#!/bin/sh
# autopath installer — works on Linux and Termux (Android).
#
# Deliberately simple: this package is 100% pure-Python stdlib, no
# compiled extensions, so there is nothing for pip to build — the exact
# class of failure that broke a previous Termux install in this project
# (a C-extension wheel with no matching platform tag) cannot happen
# here. This script uses the system python3 directly; it does NOT rely
# on uv or any managed-Python downloader, since Termux has no managed
# CPython builds available.
#
# Usage:
#   curl -LsSf https://raw.githubusercontent.com/NRAEnterprises/autopath-package/main/install.sh | sh
#
# Override the source if needed:
#   AUTOPATH_REPO_URL=https://github.com/<user>/autopath-package/archive/refs/heads/main.tar.gz sh install.sh

set -eu

REPO_URL="${AUTOPATH_REPO_URL:-https://github.com/NRAEnterprises/autopath-package/archive/refs/heads/main.tar.gz}"

have_cmd() {
    command -v "$1" >/dev/null 2>&1
}

download() {
    url="$1"
    output="$2"
    if have_cmd curl; then
        curl -fsSL "$url" -o "$output"
    elif have_cmd wget; then
        wget -qO "$output" "$url"
    else
        echo "curl or wget is required to install autopath." >&2
        exit 1
    fi
}

find_python() {
    for candidate in python3 python; do
        if have_cmd "$candidate"; then
            echo "$candidate"
            return 0
        fi
    done
    echo "No python3 interpreter found on PATH. Install one first:" >&2
    echo "  Termux:  pkg install python" >&2
    echo "  Debian/Ubuntu: sudo apt install python3 python3-pip" >&2
    exit 1
}

main() {
    PY="$(find_python)"
    echo "Using interpreter: $($PY --version 2>&1) ($PY)"

    TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/autopath-install.XXXXXX")"
    trap 'rm -rf "$TMP_DIR"' EXIT INT TERM

    archive="$TMP_DIR/autopath.tar.gz"
    download "$REPO_URL" "$archive"

    tar -xzf "$archive" -C "$TMP_DIR"
    src_dir="$(find "$TMP_DIR" -maxdepth 1 -type d -name 'autopath-*' | head -n 1)"
    if [ -z "$src_dir" ]; then
        echo "Could not locate extracted package source directory." >&2
        exit 1
    fi

    # Pure stdlib package — pip has nothing to compile, so a plain
    # --user install works everywhere. Termux/newer Debian mark the
    # system Python as "externally managed"; --break-system-packages
    # is safe here specifically because there are no dependencies that
    # could clash with system packages.
    if "$PY" -m pip install --user "$src_dir" 2>/tmp/autopath-pip-err.log; then
        :
    else
        echo "Standard install failed, retrying with --break-system-packages..." >&2
        "$PY" -m pip install --user --break-system-packages "$src_dir"
    fi

    echo
    echo "autopath installed."
    echo
    echo "If the 'autopath' command isn't found in a new shell, add pip's"
    echo "user bin directory to PATH. Find it with:"
    echo "  $PY -m site --user-base"
    echo "then add \"$($PY -m site --user-base)/bin\" to your PATH."
    echo
    echo "Try it:"
    echo "  autopath sanitize 'Galaxy S25 Ultra!!'"
}

main "$@"
