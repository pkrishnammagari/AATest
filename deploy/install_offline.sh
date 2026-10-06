#!/usr/bin/env bash
#
# Install FH AECB Analyzer on the air-gapped Linux server, from the uploaded
# wheel bundle only. Run from the unpacked release directory:
#
#   bash deploy/install_offline.sh
#
# Expects wheels.tgz and wheels.tgz.sha256 (from deploy/build_wheels.sh) in
# the release directory, or an already-unpacked wheels/ directory.
#
# --no-index guarantees pip never reaches for PyPI, and --require-hashes makes
# it refuse any wheel whose sha256 differs from requirements.lock. Re-running
# the script rebuilds the virtualenv from scratch.

set -euo pipefail

cd "$(dirname "$0")/.."

WHEELS="wheels"
VENV="${VENV:-.venv}"
LOCK="requirements.lock"

fail() { echo "ERROR: $*" >&2; exit 1; }

# --- bundle ------------------------------------------------------------------
if [ -f wheels.tgz ]; then
  [ -f wheels.tgz.sha256 ] || fail "wheels.tgz.sha256 is missing; copy it with the bundle."
  echo "==> Verifying wheels.tgz checksum"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c wheels.tgz.sha256
  else
    shasum -a 256 -c wheels.tgz.sha256
  fi
  rm -rf -- "./${WHEELS}"
  tar xzf wheels.tgz
elif [ -d "${WHEELS}" ]; then
  echo "WARNING: using an already-unpacked ${WHEELS}/ (bundle checksum not verified;"
  echo "         per-wheel hashes are still enforced by requirements.lock)."
else
  fail "neither wheels.tgz nor ${WHEELS}/ found in $(pwd)."
fi
[ -f "${LOCK}" ] || fail "${LOCK} not found in $(pwd)."

# --- interpreter -------------------------------------------------------------
PY="$(command -v python3.9 || command -v python3 || true)"
[ -n "${PY}" ] || fail "no python3.9 / python3 on PATH."
echo "==> Python: ${PY} ($("${PY}" -V 2>&1))"

# The bundle is built for CPython 3.9 (cp39) only, and streamlit 1.50.0
# excludes 3.9.7 exactly (!=3.9.7,>=3.9).
"${PY}" - <<'PY' || exit 1
import sys
v = sys.version_info
if v[:2] != (3, 9):
    sys.exit("ERROR: the wheel bundle is built for CPython 3.9; found %d.%d." % v[:2])
if v[:3] == (3, 9, 7):
    sys.exit("ERROR: Python 3.9.7 is excluded by streamlit 1.50.0; use another 3.9.x.")
PY

# --- virtualenv --------------------------------------------------------------
echo "==> Creating ${VENV} (clean)"
"${PY}" -m venv --clear "${VENV}"

# Wheels tagged manylinux_2_17 need pip 20.3 or later; the pip bundled with
# early 3.9.x releases is older, and upgrading it would need the network.
"${VENV}/bin/python" - <<'PY' || exit 1
import sys
import pip
major, minor = (int(x) for x in pip.__version__.split(".")[:2])
if (major, minor) < (20, 3):
    sys.exit("ERROR: pip %s in the venv is older than 20.3 and cannot install "
             "manylinux_2_17 wheels. Use a newer Python 3.9.x patch release."
             % pip.__version__)
PY

echo "==> Installing from ${WHEELS}/ (no network, hashes enforced)"
"${VENV}/bin/python" -m pip install --no-index --find-links="./${WHEELS}" \
  --require-hashes --no-deps -r "${LOCK}"

# requirements.lock is resolved on macOS, where streamlit does not need
# watchdog, so on Linux pip check reports exactly one known line. watchdog
# only watches source files for changes, and .streamlit/config.toml sets
# fileWatcherType = "none". That line is accepted; anything else stops the
# install.
KNOWN_PIP_CHECK="streamlit 1.50.0 requires watchdog, which is not installed."
echo "==> Checking installed requirements"
if ! PIP_CHECK="$("${VENV}/bin/python" -m pip check 2>&1)"; then
  if [ "${PIP_CHECK}" != "${KNOWN_PIP_CHECK}" ]; then
    echo "${PIP_CHECK}" >&2
    fail "pip check found broken requirements."
  fi
  echo "    ${PIP_CHECK}"
  echo "    (expected: file watching is off in .streamlit/config.toml)"
fi

# --- smoke test --------------------------------------------------------------
echo
echo "==> Verifying"
"${VENV}/bin/python" - <<'PY'
import os
import sys

import streamlit

sys.path.insert(0, os.getcwd())
from aecb import context, runtime
from aecb.render.page import render_page

print("    streamlit", streamlit.__version__, "on Python", sys.version.split()[0])
fixture = "ReferenceJSON/1_SyntheticJSONPayload_Delinquent_MultiFacility.json"
# The shipped default on a server: the AI panel shows "coming soon".
html = render_page(context.from_file(fixture), ai_mode=runtime.AI_SOON)
if "http://" in html or "https://" in html:
    sys.exit("ERROR: the rendered report contains an external reference -- it "
             "will not work offline.")
print("    rendered the synthetic fixture: %d bytes, no external references"
      % len(html))
PY

echo
echo "==> Installed. Next (docs/OPERATIONS.md):"
echo "    1. Create /etc/aecb-analyzer/aecb.env from deploy/aecb.env.example (mode 0600)."
echo "    2. Install deploy/aecb-analyzer.service and start it with systemctl."
