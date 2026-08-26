#!/usr/bin/env bash
set -euo pipefail
GATE=.ci/v3836_ai_director_context_hardening
OLD=.ci/v3834_ai_director_context
BASE=.ci/v3831_ai_director_review/frozen
RUN="$GATE/runtime"

python "$GATE/verify_base.py" | tee "$GATE/base_verify.log"
grep -q 'W22_4_2_BASE_VERIFY=PASS' "$GATE/base_verify.log"
grep -q 'BASE_SOURCE_SHA256=5/5 PASS' "$GATE/base_verify.log"
grep -q 'HARDENING_PATCH_SHA256=PASS' "$GATE/base_verify.log"

rm -rf "$RUN"
mkdir -p "$RUN/app/providers" "$RUN/app/services" "$RUN/scripts" "$RUN/tests"
cp "$BASE/app/__init__.py" "$RUN/app/__init__.py"
cp "$BASE/app/ai_director.py" "$RUN/app/ai_director.py"
cp "$BASE/app/ai_director_config.py" "$RUN/app/ai_director_config.py"
cp "$BASE/app/providers/__init__.py" "$RUN/app/providers/__init__.py"
cp "$BASE/app/providers/ai_director_groq.py" "$RUN/app/providers/ai_director_groq.py"
cp "$OLD/source/app/ai_director_context.py" "$RUN/app/ai_director_context.py"
cp "$OLD/source/app/services/ai_director_context.py" "$RUN/app/services/ai_director_context.py"
touch "$RUN/app/services/__init__.py"
cp "$OLD/source/app/providers/ai_director_context_groq.py" "$RUN/app/providers/ai_director_context_groq.py"
cp "$OLD/source/scripts/ai_director_tier2_context_review.py" "$RUN/scripts/ai_director_tier2_context_review.py"
cp "$OLD/source/tests/test_w22_4_context_core_ci.py" "$RUN/tests/test_w22_4_context_core_ci.py"
(cd "$RUN" && patch -p1 < "$GITHUB_WORKSPACE/$GATE/w2242.patch")

echo 'bb0467990316d04c769ef6c7fdaaea0d86d6d9e70033d1adfd39560c777d610b  '"$RUN/app/ai_director_context.py" | sha256sum -c -
echo '49f6210ceca7e351c26405495fcca39f299fd3a5825f3f7a4e685702155bec12  '"$RUN/app/services/ai_director_context.py" | sha256sum -c -
echo '16ecd246c2e9e695a334b79688699e3e682374c70a65a0c6998b8edf1fd9aec8  '"$RUN/app/providers/ai_director_context_groq.py" | sha256sum -c -
echo 'bc00ab5c522e296b0539fc3286397bee29c09dab5b50a629983b2ea5936793de  '"$RUN/scripts/ai_director_tier2_context_review.py" | sha256sum -c -
echo '73eeadf2e7e2fd6e6065a82679bd303629664f17fc8d4d54ccc789cd86104875  '"$RUN/tests/test_w22_4_context_core_ci.py" | sha256sum -c -
echo 'POST_PATCH_SOURCE_SHA256=5/5 PASS' | tee "$GATE/post_patch_verify.log"

(cd "$RUN" && PYTHONPATH=. pytest -q tests/test_w22_4_context_core_ci.py) | tee "$GATE/core_pytest.log"
grep -Eq '30 passed' "$GATE/core_pytest.log"
if grep -Eqi '[1-9][0-9]* skipped|[1-9][0-9]* failed|[1-9][0-9]* error' "$GATE/core_pytest.log"; then exit 1; fi

(cd "$RUN" && PYTHONPATH=. python scripts/ai_director_tier2_context_review.py --mode fixture --output "$GITHUB_WORKSPACE/$GATE/fixture_review")
grep -q 'Yoru v3.83.6 W22.4.2' "$GATE/fixture_review/YORU_AI_DIRECTOR_TIER2_CONTEXT_REVIEW_RESULT.txt"
grep -q 'STATUS=PENDING_HUMAN' "$GATE/fixture_review/YORU_AI_DIRECTOR_TIER2_CONTEXT_REVIEW_RESULT.txt"
grep -q 'AI_VALIDATED=14' "$GATE/fixture_review/YORU_AI_DIRECTOR_TIER2_CONTEXT_REVIEW_RESULT.txt"
grep -q 'FALLBACKS=0' "$GATE/fixture_review/YORU_AI_DIRECTOR_TIER2_CONTEXT_REVIEW_RESULT.txt"
grep -q 'DUPLICATE_GROUPS=0' "$GATE/fixture_review/YORU_AI_DIRECTOR_TIER2_CONTEXT_REVIEW_RESULT.txt"

(cd "$RUN" && PYTHONPATH=. python scripts/ai_director_tier2_context_review.py --mode live --model openai/gpt-oss-120b --reasoning-effort low --output "$GITHUB_WORKSPACE/$GATE/live_review")
cat "$GATE/live_review/YORU_AI_DIRECTOR_TIER2_CONTEXT_REVIEW_RESULT.txt"
grep -q 'STATUS=PENDING_HUMAN' "$GATE/live_review/YORU_AI_DIRECTOR_TIER2_CONTEXT_REVIEW_RESULT.txt"
grep -q 'TOTAL=14' "$GATE/live_review/YORU_AI_DIRECTOR_TIER2_CONTEXT_REVIEW_RESULT.txt"
grep -q 'AI_VALIDATED=14' "$GATE/live_review/YORU_AI_DIRECTOR_TIER2_CONTEXT_REVIEW_RESULT.txt"
grep -q 'FALLBACKS=0' "$GATE/live_review/YORU_AI_DIRECTOR_TIER2_CONTEXT_REVIEW_RESULT.txt"
grep -q 'DUPLICATE_GROUPS=0' "$GATE/live_review/YORU_AI_DIRECTOR_TIER2_CONTEXT_REVIEW_RESULT.txt"
grep -q 'GAMEPLAY_AUTHORITY=NONE' "$GATE/live_review/YORU_AI_DIRECTOR_TIER2_CONTEXT_REVIEW_RESULT.txt"

python -m compileall -q "$RUN" "$GATE/verify_base.py"
echo 'COMPILEALL=PASS' > "$GATE/compileall.log"
cat > "$GATE/W22_4_2_AUTOMATED_RESULT.txt" <<'EOF'
BASE_SOURCE_SHA256=5/5 PASS
HARDENING_PATCH_SHA256=PASS
POST_PATCH_SOURCE_SHA256=5/5 PASS
HUMAN_QA_REGRESSIONS=3/3 ENCODED
W22_4_2_CI_CORE=30/30 PASS
FIXTURE_CONTEXT_REVIEW=14/14 PASS
LIVE_PROVIDER_CANDIDATES=14/14 VALIDATED
EXACT_DUPLICATES=0
AUTOMATED_GATE=PENDING_HUMAN
PLAYER_FACING_SCOPE=TEST_GUILD_ONLY_DEFAULT_OFF
GAMEPLAY_AUTHORITY=NONE
LIVE_DEPLOY=UNCHANGED
W22_4_2_HUMAN_REVIEW=REQUIRED
EOF
