#!/usr/bin/env bash
# verify.sh <git-ref>
# Every file the ref holds under LOCAL_SYNC_PATHS, the common overlay, and
# each host's own overlay is byte-identical on that host. deploy.sh and
# recover.sh rely on this, so a half-synced host is never reported as stable
# or as the candidate. A per-host overlay file wins over the common one.
# (bash 3.2 cannot parse `case` inside $(...), hence the helper functions.)

. "$(dirname "${BASH_SOURCE[0]}")/lib.sh"
load_config

ref=${1:?usage: verify.sh <git-ref>}
rev=$(git_rev "$ref") || die "unknown revision $ref"

blob_md5() {
  git -C "$KAIZEN_PROJECT" show "$rev:$1" | python3 -c 'import hashlib,sys; print(hashlib.md5(sys.stdin.buffer.read()).hexdigest())'
}

# expected_sums <host>: "<md5>  <path as the host sees it>" per file; the
# host-specific overlay is printed last so it overrides the common one.
expected_sums() {
  local host=$1 root f target
  root=$(overlay_root "$host")
  for f in $files; do
    case "$f" in
      "$OVERLAY_DIR-$host"/*) continue ;;
      "$OVERLAY_DIR"/*) target="$root/$f" ;;
      *) target="$f" ;;
    esac
    printf '%s  %s\n' "$(blob_md5 "$f")" "$target"
  done
  for f in $files; do
    case "$f" in
      "$OVERLAY_DIR-$host"/*) printf '%s  %s\n' "$(blob_md5 "$f")" "$root/$OVERLAY_DIR/${f#"$OVERLAY_DIR-$host"/}" ;;
    esac
  done
}

dedupe_last_wins() {
  python3 -c '
import sys
seen = {}
for line in sys.stdin.read().splitlines():
    if line:
        h, p = line.split("  ", 1)
        seen[p] = h
print("\n".join(sorted(f"{h}  {p}" for p, h in seen.items())))'
}

failed=0
for host in $APP_HOSTS; do
  # shellcheck disable=SC2086
  files=$(git -C "$KAIZEN_PROJECT" ls-tree -r --name-only "$rev" -- $LOCAL_SYNC_PATHS "$OVERLAY_DIR" "$OVERLAY_DIR-$host" 2>/dev/null | grep -Ev "$VERIFY_EXCLUDE_REGEX" || true)
  [ -n "$files" ] || die "no files under $LOCAL_SYNC_PATHS in $ref"
  expected=$(expected_sums "$host" | dedupe_last_wins)
  paths=$(printf '%s\n' "$expected" | awk '{print $2}' | tr '\n' ' ')
  actual=$(remote "$host" "cd $REMOTE_APP_DIR && sudo md5sum $paths" | awk '{print $1"  "$2}' | sort)
  if [ "$expected" = "$actual" ]; then
    echo "$host: deployed files match $ref ($(short "$rev"))"
  else
    echo "$host: deployed files differ from $ref:" >&2
    diff <(echo "$expected") <(echo "$actual") >&2 || true
    failed=1
  fi
done
exit $failed
