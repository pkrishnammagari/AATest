#!/usr/bin/env bash
#
# Install on the air-gapped Linux server, from the uploaded wheel bundle only.
#
#   tar xzf wheels.tgz
#   bash scripts/install_offline.sh
#
# --no-index guarantees pip never reaches for PyPI: if something is missing from
# the bundle, this fails loudly here rather than hanging on a network timeout.

set -euo pipefail

cd "$(dirname "$0")/.."

WHEELS="${WHEELS:-wheels}"
VENV="${VENV:-.venv}"

if [ ! -d "${WHEELS}" ]; then
  echo "ERROR: ${WHEELS}/ not found. Unpack wheels.tgz first:  tar xzf wheels.tgz"
  exit 1
fi

PY="$(command -v python3.9 || command -v python3)"
echo "==> Python: ${PY} ($(${PY} -V 2>&1))"

# streamlit 1.50.0 declares !=3.9.7 upstream. Catch it here rather than in a
# confusing resolver error.
if ${PY} -c 'import sys; sys.exit(0 if sys.version_info[:3]==(3,9,7) else 1)'; then
  echo "ERROR: Python 3.9.7 is excluded by streamlit 1.50.0 (!=3.9.7,>=3.9)."
  echo "       Use any other 3.9.x patch release."
  exit 1
fi

if ! ${PY} -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,9) else 1)'; then
  echo "WARNING: expected Python 3.9; the wheel bundle was built for cp39."
fi

echo "==> Creating ${VENV}"
${PY} -m venv "${VENV}"

# pip/setuptools/wheel upgrades would need the network. The venv's bundled pip
# is sufficient to install pre-built wheels.
echo "==> Installing from ${WHEELS}/ (no network)"
"${VENV}/bin/pip" install --no-index --find-links="./${WHEELS}" -r requirements.txt

echo
echo "==> Verifying"
"${VENV}/bin/python" - <<'PY'
import streamlit, sys
print("    streamlit", streamlit.__version__, "on Python", sys.version.split()[0])
PY

# Prove the renderer works before anyone opens a browser.
"${VENV}/bin/python" - <<'PY'
import glob, os, sys
sys.path.insert(0, os.getcwd())
from aecb import context
from aecb.render.page import render_page
payloads = sorted(glob.glob("ReferenceJSON/*.json"))
if not payloads:
    print("    no payloads in ReferenceJSON/ -- skipping render check")
else:
    html = render_page(context.from_file(payloads[0]))
    assert "http://" not in html and "https://" not in html, \
        "render produced an external reference -- it will break offline"
    print("    rendered %s: %d bytes, no external references" %
          (os.path.basename(payloads[0]), len(html)))
PY

echo
echo "==> Done. Start with:"
echo "    ${VENV}/bin/python -m streamlit run app.py --server.port 8501 \\"
echo "        --server.address 0.0.0.0 --server.headless true \\"
echo "        --browser.gatherUsageStats false"
