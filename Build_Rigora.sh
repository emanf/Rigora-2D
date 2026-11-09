#!/usr/bin/env bash
# Compile a native Linux folder or macOS application using the shared builder.
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
case "$(uname -s)" in
    Linux|Darwin) ;;
    *) printf '%s\n' 'ERROR: Use Build_Rigora.bat on Windows.' >&2; exit 1 ;;
esac

if command -v uv >/dev/null 2>&1; then
    uv_path="$(command -v uv)"
elif [[ -x "$project_root/.build-tools/uv/uv" ]]; then
    uv_path="$project_root/.build-tools/uv/uv"
else
    mkdir -p "$project_root/.build-tools"
    installer="$project_root/.build-tools/install-uv.sh"
    if ! command -v curl >/dev/null 2>&1 && ! command -v wget >/dev/null 2>&1; then
        privilege=()
        if [[ "$EUID" -ne 0 ]]; then privilege=(sudo); fi
        if command -v apt-get >/dev/null 2>&1; then
            "${privilege[@]}" apt-get update
            "${privilege[@]}" apt-get install -y curl ca-certificates
        elif command -v dnf >/dev/null 2>&1; then
            "${privilege[@]}" dnf install -y curl ca-certificates
        elif command -v pacman >/dev/null 2>&1; then
            "${privilege[@]}" pacman -S --needed --noconfirm curl ca-certificates
        else
            printf '%s\n' 'ERROR: Install curl or wget, then run this script again.' >&2
            exit 1
        fi
    fi
    printf '%s\n' 'Installing uv locally for the Rigora build...'
    if command -v curl >/dev/null 2>&1; then
        curl --fail --location --proto '=https' --tlsv1.2 https://astral.sh/uv/install.sh -o "$installer"
    else
        wget --https-only https://astral.sh/uv/install.sh -O "$installer"
    fi
    UV_INSTALL_DIR="$project_root/.build-tools/uv" UV_NO_MODIFY_PATH=1 sh "$installer"
    uv_path="$project_root/.build-tools/uv/uv"
fi
exec "$uv_path" run --no-project --python 3.12 "$project_root/tools/build_app.py" --uv "$uv_path" "$@"
