# Dependency vulnerability register

**Scope:** the exact dependency tree deployed to the UAT/production server, as pinned (with sha256 hashes) in [`requirements.lock`](../requirements.lock). That is CPython 3.9 on linux x86_64, with streamlit 1.50.0 and 35 transitive packages.

**Last reviewed:** 29 Sep 2026, against the PyPI advisory database (via `pip-audit`). Mend uses its own database, so its list may differ slightly. Re-run the audit whenever `requirements.lock` changes (see [OPERATIONS.md](OPERATIONS.md#dependency-audit)).

## Why these cannot be upgraded away

The server is air-gapped and fixed at **Python 3.9**. Every fixed version below requires Python 3.10 or later, so no fix can be installed on this runtime:

| Package | Shipped | First fixed version | Supports Python 3.9? |
|---|---|---|---|
| streamlit | 1.50.0 (last release for 3.9) | 1.53.1 / 1.54.0 | No |
| pillow | 11.3.0 | 12.1.1 – 12.3.0 | No |
| pyarrow | 20.0.0 | 23.0.1 | No |
| requests | 2.32.5 | 2.33.0 | No |
| urllib3 | 2.6.3 | 2.7.0 | No |
| click | 8.1.8 | 8.3.3 | No |

The same audit run against Python 3.11 with the current streamlit release reports **no known vulnerabilities**. Upgrading the server's Python is the only complete remediation. Python 3.9 itself reached end of life in October 2025.

## Exposure in this application

The application's own code (`aecb/`, `app.py`) imports **none** of these libraries directly. It uses Python's standard library for HTTP (`http.client`, `urllib.request`) and only `streamlit` from third-party code. It does not call Streamlit's image, chart, dataframe or caching APIs. The entry point, `app.py`, accepts exactly one input on a server: a CB subject id, validated against `^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$`. It has no file uploader.

| Package | Advisories | What is vulnerable | Reachable here? |
|---|---|---|---|
| **streamlit** | PYSEC-2026-212 (CVE-2026-10804) | Hashing in `st.cache_*` | **No.** The app uses no `st.cache_data`/`st.cache_resource`. |
| | PYSEC-2026-2285 (CVE-2026-33682) | Streamlit on **Windows** hosts | **No.** The server is Linux. |
| **pillow** | 19 advisories (PSD, FITS, PDF, JPEG2000, TGA, BDF/PCF/GD font parsing, ImageDraw/ImageCms/rank-filter coordinate handling, Windows viewer) | Decoding or drawing attacker-supplied images and fonts | **No.** The app never opens an image. The favicon is a static SVG data URI built by the app. Pillow is present only because streamlit depends on it for `st.image`, which is not used. |
| **pyarrow** | PYSEC-2026-113 (CVE-2026-25087) | Reading an Arrow IPC **file** | **No.** Nothing reads Arrow files. Streamlit uses Arrow only to serialise its own dataframes, which this app does not render. |
| **requests** | PYSEC-2026-2275 (CVE-2026-25645) | `requests.utils.extract_zipped_paths()` temp-file naming | **No.** The app does not use `requests`. |
| **urllib3** | PYSEC-2026-141, -142 (CVE-2026-44431, -44432) | Cross-origin redirects and the streaming decompression API | **No.** The app does not use urllib3. Its two HTTP clients are standard-library code: the bureau API uses `http.client`, and the local development model (Ollama) uses `urllib.request` with redirects refused. |
| **click** | PYSEC-2026-2132 (CVE-2026-7246) | `click.edit()` command injection | **No.** Click only parses the `streamlit run` command line on the server; `click.edit()` is never called. |

## Compensating controls

These reduce the residual risk while the runtime stays on Python 3.9:

- The server is air-gapped. Outbound traffic goes only to the internal bureau-report API. (Going live with the AI Analysis adds one egress route to Core42; the connector is a placeholder with no network code until Core42 is onboarded, DECISIONS OPEN-13.)
- `.streamlit/config.toml` hides tracebacks from browsers (`client.showErrorDetails = "none"`), disables usage statistics and file watching, and caps uploads.
- `app.py` validates its single input before use and has no file-upload surface.
- The rendered report carries a strict Content-Security-Policy and loads no external resources.
- Every installed wheel is verified against the sha256 hash in `requirements.lock` (`pip --require-hashes`).

## Recommendation

Raise a Mend policy exception for the 25 advisories above, citing this register (not reachable, runtime-locked). Track the Python 3.10+ upgrade of the UAT/production server as the remediation.
