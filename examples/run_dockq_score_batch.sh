#!/usr/bin/env bash
# Batch DockQ scoring via bioq: 1 reference native + N candidate models.
#
# dockq is CPU-only. Repeating --file models=<path> makes bioq send a list, so
# the service scores every candidate against the one native and returns a sorted
# scores.csv plus per-model JSON. Handy for ranking RFantibody/RFdiffusion output.
#
# Usage:
#   ./run_dockq_score_batch.sh <native.pdb> <model_1.pdb> [<model_2.pdb> ...]
# Example:
#   ./run_dockq_score_batch.sh reference.pdb design_*.pdb
#
# Env:
#   BIOQ         override the bioq entrypoint (default: bioq on PATH, else `uv run bioq`)
#   BIOQ_PROFILE profile to use (default: default)
#   OUT          output dir (default: ./out)
#   SORT_BY      scores.csv column to sort by, descending (default: DockQ)
set -euo pipefail

NATIVE="${1:?usage: run_dockq_score_batch.sh <native.pdb> <model_1.pdb> [...]}"
shift
[ "$#" -ge 1 ] || { echo "error: need at least one candidate model" >&2; exit 2; }

HERE="$(cd "$(dirname "$0")" && pwd)"
BIOQ="${BIOQ:-$(command -v bioq || echo "uv run bioq")}"
PROFILE="${BIOQ_PROFILE:-default}"
OUT="${OUT:-$HERE/out}"
SORT_BY="${SORT_BY:-DockQ}"

mkdir -p "$OUT"

args=(--file "native=$NATIVE")
for m in "$@"; do
    args+=(--file "models=$m")
done
args+=(--set "sort_by=$SORT_BY")

$BIOQ --profile "$PROFILE" run dockq score_batch "${args[@]}" --wait -o "$OUT"

echo "=== output tree ==="
ls -R "$OUT"
