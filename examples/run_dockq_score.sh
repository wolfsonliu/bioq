#!/usr/bin/env bash
# Single (model, native) DockQ scoring via bioq.
#
# dockq is a CPU-only service; score one predicted complex against a known
# reference. Output is the raw DockQ JSON (<name>.json).
#
# Usage:
#   ./run_dockq_score.sh <model.pdb> <native.pdb> [mapping]
# Example:
#   ./run_dockq_score.sh design.pdb reference.pdb HLA:BCX
#
# Env:
#   BIOQ         override the bioq entrypoint (default: bioq on PATH, else `uv run bioq`)
#   BIOQ_PROFILE profile to use (default: default)
#   OUT          output dir (default: ./out)
set -euo pipefail

MODEL="${1:?usage: run_dockq_score.sh <model.pdb> <native.pdb> [mapping]}"
NATIVE="${2:?usage: run_dockq_score.sh <model.pdb> <native.pdb> [mapping]}"
MAPPING="${3:-}"

HERE="$(cd "$(dirname "$0")" && pwd)"
BIOQ="${BIOQ:-$(command -v bioq || echo "uv run bioq")}"
PROFILE="${BIOQ_PROFILE:-default}"
OUT="${OUT:-$HERE/out}"

mkdir -p "$OUT"

args=(--file "model=$MODEL" --file "native=$NATIVE" --set name=score)
[ -n "$MAPPING" ] && args+=(--set "mapping=$MAPPING")

$BIOQ --profile "$PROFILE" run dockq score "${args[@]}" --wait -o "$OUT"

echo "=== output tree ==="
ls -R "$OUT"
