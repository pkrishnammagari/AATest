#!/usr/bin/env bash
#
# Package a release of the committed tree for the server:
#
#   bash deploy/make_release.sh
#
# Writes aecb-analyzer-<version>.tar.gz and its .sha256 in the repository
# root. The archive is `git archive HEAD`, so it holds exactly what is
# committed -- nothing from the working tree -- minus the development-only
# paths in DEV_ONLY below. Pair it with the wheel bundle from
# deploy/build_wheels.sh; docs/OPERATIONS.md has the full procedure.
#
# The exclusions live HERE, not as export-ignore in .gitattributes: GitHub's
# "Download ZIP" is also built with git archive, and export-ignore would
# silently drop the tests, tools and docs from every developer download.

set -euo pipefail

cd "$(dirname "$0")/.."

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "ERROR: uncommitted changes. Commit (and tag) before packaging a release." >&2
  exit 1
fi

# Never shipped to the server: tests, developer tooling, documentation, the
# anonymized archive fixture (the install smoke test uses the synthetic one)
# and development/scan configuration.
DEV_ONLY=(
  tests
  scripts
  docs
  ReferenceJSON/aecb_payload_archive_170623.json
  requirements-dev.txt
  pytest.ini
  .coveragerc
  sonar-project.properties
  .gitattributes
  .gitignore
)
PATHSPEC=(.)
for path in "${DEV_ONLY[@]}"; do
  PATHSPEC+=(":(exclude)${path}")
done

VERSION="$(git describe --tags --always --dirty)"
NAME="aecb-analyzer-${VERSION}"

git archive --format=tar.gz --prefix="${NAME}/" -o "${NAME}.tar.gz" HEAD -- "${PATHSPEC[@]}"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "${NAME}.tar.gz" > "${NAME}.tar.gz.sha256"
else
  shasum -a 256 "${NAME}.tar.gz" > "${NAME}.tar.gz.sha256"
fi

echo "==> ${NAME}.tar.gz ($(du -h "${NAME}.tar.gz" | cut -f1)), checksum in ${NAME}.tar.gz.sha256"
echo "    Contents:"
tar tzf "${NAME}.tar.gz" | sed -n '1,200p' | sed 's/^/      /'
