#!/usr/bin/env bash
# Stage a suite, run it through `claude plugin eval`, grade it, and log the cost.
#   run_eval.sh LABEL SUITE VARIANT ABLATION RUNS MAX_COST_USD [CASE_GLOB] [extra eval flags...]
# Every run pins the model (EVAL_MODEL, default Opus 5.5) so a rollout cannot be mistaken for an effect of the skill.
set -euo pipefail
# On a subscription the CLI defaults to a 1-hour cache, whose writes cost 1.6 times the 5-minute price, and these runs are short.
# Both arms get the same value. It changes the bill, not what the agent sees. Override it to reprice a comparison.
export CLAUDE_CODE_PROMPT_CACHE_TTL="${CLAUDE_CODE_PROMPT_CACHE_TTL:-5m}"
label=$1 suite=$2 variant=$3 ablation=$4 runs=$5 cap=$6 glob=${7:-*}
shift $(( $# < 7 ? $# : 7 ))
evals="$(cd "$(dirname "$0")" && pwd)"
out="$evals/results/$label"
if [ -e "$out" ]; then echo "refusing to overwrite $out" >&2; exit 1; fi
stage="$(mktemp -d)/stage"
python3 "$evals/stage.py" --suite "$suite" --variant "$variant" --out "$stage" --case "$glob" >/dev/null
mkdir -p "$out"
cd "$stage"
status=0
claude plugin eval "$stage" --scaffold --runs "$runs" --ablation "$ablation" --keep-temp --no-publish \
  --trust-plugin --model "${EVAL_MODEL:-claude-opus-5-5}" -j 4 --max-cost-usd "$cap" --threshold 0 --output-dir "$out" \
  --allow-tools Bash Write Edit "$@" > "$out/eval.log" 2>&1 || status=$?
# The money is spent whether or not grading works, so log it first: with pipefail, a failed grade would exit before this.
python3 - "$label" "$out/aggregate-result.json" "$evals/results/ledger.jsonl" "$variant" "$ablation" "$status" "$stage" "${EVAL_MODEL:-claude-opus-5-5}" <<'PY'
import hashlib, json, os, pathlib, sys
label, result, ledger, variant, ablation, status, stage, model = sys.argv[1:]
doc = json.load(open(result))
digest = hashlib.sha256()
parts = [pathlib.Path(stage) / name for name in ("skills", "hooks", "agents")]
for path in sorted(p for part in parts if part.exists() for p in part.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
    digest.update(str(path.relative_to(stage)).encode() + path.read_bytes())
entry = {"step": label, "variant": variant, "ablation": ablation, "cost_usd": doc["costUsd"],
         "partial": doc["partial"], "exit": int(status), "claude": doc["claudeVersion"], "model": model,
         "cache_ttl": os.environ["CLAUDE_CODE_PROMPT_CACHE_TTL"],
         "plugin_sha256": digest.hexdigest()[:16] if parts[0].exists() else None}
open(ledger, "a").write(json.dumps(entry) + "\n")
print(entry)
PY
python3 "$evals/grade_workspaces.py" "$out/aggregate-result.json" --suite "$suite" --out "$out/graded" | cut -c1-170
