# Security review notes

**Audience:** reviewers triaging the SonarQube and Mend results for this repository.
**Last reviewed:** 29 Sep 2026.
**Scope:** what `sonar-project.properties` scans (`aecb/`, `app_api.py`, `app.py`, `deploy/`, with `tests/` as test code), plus the dependency tree in `requirements.lock`.

## Expected security hotspots and their disposition

| Location | Rule (typical) | What it flags | Disposition |
|---|---|---|---|
| `aecb/ntlm.py`: `hashlib.new("md4")`, `_md4_pure`, `hmac.new(..., "md5")` | Weak hashing algorithm (python:S4790) | MD4 and HMAC-MD5 | **Safe, protocol-mandated.** The bureau-report API uses IIS Windows authentication, and NTLMv2 (MS-NLMP 3.3.2) is defined over MD4 (NT hash) and HMAC-MD5 (proofs). Nothing is stored, and the password never goes on the wire. The implementation is verified against the RFC 1320 and MS-NLMP 4.2.4 test vectors (`tests/test_ntlm.py`) and a proof-checking server (`tests/test_api.py`). |
| `aecb/api.py`: `http.client.HTTPConnection` when `base_url` is `http://` | Clear-text protocol (python:S5332) | The internal bureau API is currently configured over HTTP | **Accepted for UAT, with a recommendation.** The endpoint is internal to the air-gapped estate, and NTLM means no password is sent. Bureau payloads do travel in clear text on the internal network, so switch `base_url` to `https://` as soon as the API team offers TLS. The client supports that with no code change, and certificate verification stays on (default SSL context). |
| `aecb/brief/client.py`: `http://127.0.0.1:11434` | Clear-text protocol | Local Ollama endpoint | **Safe.** Loopback only, with proxies ignored and redirects refused. The AI brief is not deployed on UAT. |
| `aecb/brief/client.py`: `_OPENER.open(...)` | URL-open audit | Opening a URL | **Safe.** The URL is a constant loopback address and the path is fixed. |
| `aecb/ui.py`, `app_api.py`: `st.markdown(..., unsafe_allow_html=True)` | (Streamlit HTML) | Raw HTML into the page | **Safe.** Only static CSS and constant markup; no payload or user data is interpolated. |
| `aecb/render/report.js`: `innerHTML` | DOM XSS review | HTML built in script | **Safe.** Every payload-derived value is passed through `esc()`; `tests/test_security.py` fuzzes every payload field and asserts no raw markup reaches the page. The page's Content-Security-Policy admits only its own hashed inline script. |
| `tests/test_browser.py`: `subprocess.run([chrome, ...])` | OS command (python:S4721) | Starts Chrome | **Safe, test only.** Argument list (no shell); the executable is a local Chrome found by path. |
| `tests/test_api.py`: literal test credentials | Hard-coded secrets | Fixed account and password for a local stub server | **Safe, test only.** Test data for a server bound to 127.0.0.1 inside the test. |

## Controls that address common findings

| Concern | Control | Where |
|---|---|---|
| Cross-site scripting from bureau data | Escaping at every sink; script-safe JSON (`<`, `>`, `&`, U+2028/9 escaped); per-page CSP with the script's SHA-256 | `aecb/render/components.py`, `aecb/render/js.py`, `aecb/render/page.py`; `tests/test_security.py`, `tests/test_browser.py` |
| Error details reaching the browser (CWE-209) | User-facing messages carry no URLs, bodies or tracebacks; `client.showErrorDetails = "none"` | `aecb/api.py`, `app_api.py`, `.streamlit/config.toml`; `tests/test_api.py` |
| Credentials in source | Service account read from the environment only; a config file carrying credentials is refused | `aecb/api.py`, `deploy/aecb.env.example`; `tests/test_api.py` |
| Personal data at rest | API response archive outside the application tree, directory `0700`, files `0600`, off unless configured; retention by operations | `aecb/archive.py`, `docs/OPERATIONS.md`; `tests/test_archive.py` |
| Accountability | One audit log line per query (subject, outcome, user header when behind SSO, client IP) | `app_api.py` |
| Input validation | Subject ID restricted to `^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$`; malformed JSON, NaN/Infinity and non-object rows are handled without crashing | `app_api.py`, `aecb/loader.py`; `tests/test_loader.py`, `tests/test_apps.py` |
| Resource exhaustion | API and model responses are size-capped; timeouts on every network call | `aecb/api.py`, `aecb/brief/client.py` |
| Supply chain | Every wheel pinned by version and sha256 (`pip --require-hashes`); bundle checksum verified at install; offline install (`--no-index`) | `requirements.lock`, `deploy/` |
| Model data minimisation (AI brief, dev only) | Digest instead of raw payload; no subject ID or birth month sent; prohibited fields enforced at runtime; payload text sanitised against prompt injection | `aecb/brief/`, `aecb/derive/brief_facts/`; `tests/test_brief.py` |

## Items outside the application's control

- **Authentication and TLS for users.** The Streamlit app has no login of its own. Put it behind the TLS-terminating, SSO-authenticating reverse proxy described in [OPERATIONS.md](OPERATIONS.md), and bind it to localhost (`deploy/aecb-analyzer.service` does).
- **Runtime.** The server stays on Python 3.9 (air-gapped). The known advisories in the pinned dependency tree, and why none of them is reachable, are recorded in [DEPENDENCY_RISK.md](DEPENDENCY_RISK.md).
