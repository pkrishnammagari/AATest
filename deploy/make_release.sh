#!/usr/bin/env bash
#
# Package a release of the committed tree for the server:
#
#   bash deploy/make_release.sh
#
# Writes aecb-analyzer-<version>.tar.gz and its .sha256 next to the
# repository. The archive is `git archive HEAD`, so it holds exactly what is
# committed -- nothing from the working tree -- minus the development-only
# paths marked export-ignore in .gitattributes (tests, dev tooling, docs, the
# development harness app.py). Pair it with the wheel bundle from
# deploy/build_wheels.sh; docs/OPERATIONS.md has the full procedure.

set -euo pipefail

cd "$(dirname "$0")/.."

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "ERROR: uncommitted changes. Commit (and tag) before packaging a release." >&2
  exit 1
fi

VERSION="$(git describe --tags --always --dirty)"
NAME="aecb-analyzer-${VERSION}"

git archive --format=tar.gz --prefix="${NAME}/" -o "${NAME}.tar.gz" HEAD
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "${NAME}.tar.gz" > "${NAME}.tar.gz.sha256"
else
  shasum -a 256 "${NAME}.tar.gz" > "${NAME}.tar.gz.sha256"
fi

echo "==> ${NAME}.tar.gz ($(du -h "${NAME}.tar.gz" | cut -f1)), checksum in ${NAME}.tar.gz.sha256"
echo "    Contents:"
tar tzf "${NAME}.tar.gz" | sed -n '1,200p' | sed 's/^/      /'
