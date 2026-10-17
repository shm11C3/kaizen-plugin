#!/usr/bin/env bash
# Fake benchmarker for tests. Reads the score the deployed application
# "would get" from isu1's deployed go/score (an integer, or "fail"), adds a
# run counter so samples differ, and prints an ISUCON14-shaped result line.
set -eu
app="$KAIZEN_FAKE_REMOTE/isu1/webapp/go/score"
counter="$KAIZEN_FAKE_REMOTE/bench-count"
n=$(cat "$counter" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$counter"
want=$(cat "$app")
for i in $(seq 1 $((100 + n))); do echo "req $i"; done >> "$KAIZEN_FAKE_REMOTE/isu1/access.log"
echo "time=00:00:00.000 level=INFO msg=負荷走行を開始します"
if [ "$want" = fail ]; then
  echo 'time=00:01:00.000 level=INFO msg=結果 pass=false スコア=0 種別エラー数="map[30:1 25:4]"'
  exit 1
fi
echo "time=00:01:00.000 level=INFO msg=結果 pass=true スコア=$((want + n)) 種別エラー数=map[]"
