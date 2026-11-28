#!/usr/bin/env bash
# Generates actions.lock for each repo in repos.txt and writes the result to out/<owner_repo>/
set -uo pipefail
mkdir -p out work
while read -r r; do
  [ -z "$r" ] && continue
  d=$(echo "$r" | tr / _)
  o="out/$d"; mkdir -p "$o"
  echo "::group::$r"
  rm -rf "work/$d"
  git clone -q --depth 1 "https://github.com/$r" "work/$d" || { echo clone-failed > "$o/status"; echo "::endgroup::"; continue; }
  git -C "work/$d" rev-parse HEAD > "$o/base"
  [ -f "pre/$d.patch" ] && git -C "work/$d" apply "$PWD/pre/$d.patch" && echo prepatched > "$o/prepatched"
  ( cd "work/$d" && gh actions-lock --no-interactive --no-narrow --json=valid,findings > "../../$o/fix.json" 2> "../../$o/fix.err"; echo $? > "../../$o/fix.rc" )
  if jq -e '[.findings[]? | select(.severity=="error" and .category=="local-action")] | length > 0' "$o/fix.json" >/dev/null; then
    echo migrate > "$o/migrated"
    ( cd "work/$d" && gh actions-lock --no-interactive --no-narrow --migrate-local-actions --json=valid,findings > "../../$o/fix.json" 2> "../../$o/fix.err"; echo $? > "../../$o/fix.rc" )
  fi
  ( cd "work/$d" && gh actions-lock --verify --json=valid,findings > "../../$o/verify.json" 2> "../../$o/verify.err"; echo $? > "../../$o/verify.rc" )
  ( cd "work/$d" && git add -A .github && git diff --cached --binary > "../../$o/change.patch"; git diff --cached --stat > "../../$o/stat" )
  echo "fix=$(cat $o/fix.rc) verify=$(cat $o/verify.rc) $(tail -1 $o/stat)"
  echo "::endgroup::"
done < repos.txt
