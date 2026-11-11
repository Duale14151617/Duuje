#!/usr/bin/env bash
# Extracts every *.zip in the repo root into the repo root, then deletes the zip.
# Usage: scripts/unzip-zips.sh [zip-name ...]   (no arguments = every *.zip in the root)
set -euo pipefail
shopt -s nullglob

zips=("$@")
[ ${#zips[@]} -eq 0 ] && zips=(*.zip)
[ ${#zips[@]} -eq 0 ] && { echo "No zip files in the repo root."; exit 0; }

for z in "${zips[@]}"; do
  [ -f "$z" ] || { echo "Not found: $z"; exit 1; }
  echo "== $z"
  tmp=$(mktemp -d)
  unzip -q "$z" -d "$tmp"
  src="$tmp"
  entries=("$tmp"/* "$tmp"/.[!.]*)
  entries=($(for e in "${entries[@]}"; do [ -e "$e" ] && echo "$e"; done))
  # Strip a single wrapper folder (e.g. "Duale--main/" from GitHub's Download ZIP) but never a real project
  # folder such as "web/" or "src/": a zip holding only "web/..." must land in ./web, not in the root.
  if [ ${#entries[@]} -eq 1 ] && [ -d "${entries[0]}" ]; then
    name=$(basename "${entries[0]}")
    wrapper=no
    case "$name" in *-main|*-master) wrapper=yes ;; esac
    if [ ! -e "./$name" ]; then
      for m in README.md Dockerfile docker-compose.yml render.yaml .github; do [ -e "${entries[0]}/$m" ] && wrapper=yes; done
    fi
    [ "$wrapper" = yes ] && src="${entries[0]}"
  fi
  # .github is skipped: the default Actions token cannot push workflow files.
  (cd "$src" && tar cf - --exclude='./.github' .) | tar xf -
  rm -rf "$tmp"
  rm -f "$z"
  echo "   extracted and removed $z"
done
