#!/usr/bin/env bash
#
# Package UnrealMCPython as a precompiled binary plugin for one UE version on Linux,
# via RunUAT BuildPlugin. Linux counterpart of build-plugin.ps1.
#
# Produces a distributable zip (UnrealMCPython/ with Binaries + Source + Content + .uplugin)
# named UnrealMCPython_Linux_<engineLabel>_<pluginVersion>.zip. The platform is in the name
# because a release also carries the Win64 zips produced by build-plugin.ps1. Run once per UE
# version on a machine that has that engine installed — GitHub-hosted CI cannot do this
# (no Unreal Engine on the runner), so this is a local build step.
#
# Live Coding does not exist on Linux; the module compiles it out behind WITH_LIVE_CODING,
# so the packaged plugin simply has no livecoding_compile handler.
#
# Usage:
#   tools/build-plugin.sh --ue-root ~/UnrealEngine-5.8.1-src
#   tools/build-plugin.sh --ue-root /opt/UE_5.8 --engine-label 5.8 --out-dir /tmp/plugin-build
#
# Then attach the zip to a release:
#   gh release upload v2.2.0 Saved/PluginBuild/UnrealMCPython_Linux_5.8_2.2.0.zip

set -euo pipefail

ue_root=""
engine_label=""
out_dir=""

usage() {
    echo "usage: $0 --ue-root <path> [--engine-label <label>] [--out-dir <path>]" >&2
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        --ue-root)      ue_root="${2:-}"; shift 2 ;;
        --engine-label) engine_label="${2:-}"; shift 2 ;;
        --out-dir)      out_dir="${2:-}"; shift 2 ;;
        -h|--help)      usage ;;
        *)              echo "unknown argument: $1" >&2; usage ;;
    esac
done

[ -n "$ue_root" ] || usage
command -v zip >/dev/null || { echo "zip not found — install it (the plugin is shipped as a zip)" >&2; exit 1; }

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
uplugin="$repo/Plugins/UnrealMCPython/UnrealMCPython.uplugin"
runuat="$ue_root/Engine/Build/BatchFiles/RunUAT.sh"

[ -f "$runuat" ]  || { echo "RunUAT.sh not found at $runuat" >&2; exit 1; }
[ -f "$uplugin" ] || { echo ".uplugin not found at $uplugin" >&2; exit 1; }
[ -n "$out_dir" ] || out_dir="$repo/Saved/PluginBuild"

# plugin version from the .uplugin
ver="$(sed -n 's/.*"VersionName"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' "$uplugin" | head -1)"
[ -n "$ver" ] || { echo "Could not read VersionName from $uplugin" >&2; exit 1; }
# engine label: explicit, else derived from the UE_x.y folder name
[ -n "$engine_label" ] || engine_label="$(basename "$ue_root" | sed 's/^UE_//')"

pkg="$out_dir/UnrealMCPython"
rm -rf "$pkg"
mkdir -p "$out_dir"

echo "Building UnrealMCPython $ver for UE $engine_label (Linux) ..."
"$runuat" BuildPlugin -Plugin="$uplugin" -Package="$pkg" -TargetPlatforms=Linux -Rocket

# Intermediate is build scratch — not needed in the distributed plugin.
rm -rf "$pkg/Intermediate"

zip_path="$out_dir/UnrealMCPython_Linux_${engine_label}_${ver}.zip"
rm -f "$zip_path"
(cd "$out_dir" && zip -qr "$zip_path" UnrealMCPython)
echo "BUILT: $zip_path"
