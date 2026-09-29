# FH AECB Analyzer — Operations Runbook

This runbook covers how to build, package, install, configure, run and
maintain FH AECB Analyzer on the air-gapped UAT/production server. The
deployed entry point is `app_api.py`. The development harness `app.py`, the
AI brief and any model service (Ollama) are **not** deployed. The production
page renders without the AI Analysis panel.

## Deployment at a glance

```
user browser ──HTTPS──> reverse proxy (TLS + SSO) ──HTTP──> 127.0.0.1:8501  streamlit (app_api.py, user aecb)
                                                                  │
                                                                  ├──> bureau-report API (internal endpoint in config/api.json)
                                                                  ├──> /var/lib/aecb-analyzer/api_responses/  (archive, 0700/0600)
                                                                  └──> journald + /var/log/aecb-analyzer/aecb.log
```

| Path | Purpose | Owner / mode |
|---|---|---|
| `/opt/aecb-analyzer-releases/<release>/` | Unpacked release, with its own `.venv/` built in place | root, read-only to `aecb` |
| `/opt/aecb-analyzer` | Symlink to the active release (the unit's `WorkingDirectory`) | root |
| `/etc/aecb-analyzer/aecb.env` | Environment: API credentials, archive and log folders | `aecb:aecb` 0600, in a 0750 directory |
| `/var/lib/aecb-analyzer/api_responses/` | API response archive (`AECB_ARCHIVE_DIR`) | `aecb`, 0700 folder, 0600 files |
| `/var/log/aecb-analyzer/` | Rotating `aecb.log` (`AECB_LOG_DIR`) | `aecb`, 0750 |

These paths match `deploy/aecb-analyzer.service` and `deploy/aecb.env.example`.
If you change a path, change it in both files and in the unit's
`ReadWritePaths`.

## Build the wheel bundle (connected machine)

Run this from a clone of the repository at the commit being released:

```bash
bash deploy/build_wheels.sh              # downloads exactly what requirements.lock pins
```

The script produces `wheels/`, `wheels.tgz` and `wheels.tgz.sha256`. It
works as follows:

- It cross-downloads for CPython 3.9 on manylinux x86_64 (use
  `PLAT_ARCH=aarch64` for ARM). Nothing is compiled.
- It verifies every wheel against its sha256 in `requirements.lock`.
- It fails if any source archive is present, or if a compiled package
  (pyarrow, numpy, pandas, pillow, protobuf, tornado) resolved to the wrong
  ABI or architecture.
- It uses `./.venv/bin/python` or `python3`. Set `PYTHON=/path/to/python` to
  override.

**Changing dependencies.** `requirements.txt` holds the single runtime pin
(`streamlit==1.50.0`). `requirements.lock` is the committed, hashed full tree.
To change the dependency set:

1. Edit `requirements.txt` if the pin changes.
2. Run `bash deploy/build_wheels.sh --relock`. This re-resolves the tree and
   rewrites `requirements.lock`.
3. Review the lock diff, run the test suite on Python 3.9, run the
   [dependency audit](#dependency-audit), and commit the new lock.

`--relock` is the only way the deployed dependency set changes.

## Package a release (connected machine)

```bash
git tag <version>                         # optional; names the archive
bash deploy/make_release.sh
```

The release archive holds exactly what is committed, not the working tree:

- The script refuses to run while tracked files have uncommitted changes.
  It does not check for untracked files, and untracked files are never
  packaged. Before packaging, commit every file the server needs, such as a
  new file under `deploy/`, `.streamlit/` or `requirements.lock`.
- It runs `git archive HEAD`, minus the development-only paths listed in
  the script (`DEV_ONLY`): `app.py`, `tests/`, `scripts/`, `docs/`, the
  anonymized archive fixture, and the development config files. A GitHub
  "Download ZIP" or a `git clone` still contains everything.
- The release keeps `app_api.py`, `aecb/`, `config/`, `assets/`,
  `resources/`, `.streamlit/`, `deploy/`, `requirements.txt`,
  `requirements.lock`, and the synthetic fixture used by the install smoke
  test.

Output, in the repository root:

- `aecb-analyzer-<version>.tar.gz`
- `aecb-analyzer-<version>.tar.gz.sha256`

`<version>` comes from `git describe --tags --always --dirty`.

## Transfer

Move these four files to the server through the approved transfer channel:

```
aecb-analyzer-<version>.tar.gz        aecb-analyzer-<version>.tar.gz.sha256
wheels.tgz                            wheels.tgz.sha256
```

## Install (server)

**Prerequisites:**

- CPython 3.9.x (any patch release except 3.9.7), available as `python3.9`
  or `python3`. The bundled pip must be 20.3 or later.
- A system account `aecb`.
- The data folders:

```bash
install -d -m 0700 -o aecb -g aecb /var/lib/aecb-analyzer
install -d -m 0750 -o aecb -g aecb /var/log/aecb-analyzer
```

**Unpack and install.** The virtualenv is not relocatable, so build it in the
directory the release will run from:

```bash
cd /tmp/transfer
sha256sum -c aecb-analyzer-<version>.tar.gz.sha256
mkdir -p /opt/aecb-analyzer-releases
tar xzf aecb-analyzer-<version>.tar.gz -C /opt/aecb-analyzer-releases
cp wheels.tgz wheels.tgz.sha256 /opt/aecb-analyzer-releases/aecb-analyzer-<version>/
cd /opt/aecb-analyzer-releases/aecb-analyzer-<version>
bash deploy/install_offline.sh
```

`install_offline.sh` does the following:

1. Verifies `wheels.tgz` against `wheels.tgz.sha256` and unpacks it.
2. Refuses any Python other than 3.9, and refuses 3.9.7 exactly.
3. Creates a clean `.venv/`. Re-running the script rebuilds it; set `VENV`
   to change the path.
4. Installs with `pip install --no-index --require-hashes --no-deps -r
   requirements.lock`, so pip never reaches the network and rejects any wheel
   whose hash differs. Then it runs `pip check`.
5. Runs a smoke test: it renders the synthetic fixture with `ai_panel=False`
   and fails if the page contains any `http://` or `https://` reference.

## Configure

Create the environment file from the template and restrict it:

```bash
install -d -m 0750 /etc/aecb-analyzer
install -m 0600 -o aecb -g aecb deploy/aecb.env.example /etc/aecb-analyzer/aecb.env
vi /etc/aecb-analyzer/aecb.env
```

| Variable | Required | Value |
|---|---|---|
| `AECB_API_USERNAME` | Yes | Service account name. Give the domain separately in `AECB_API_DOMAIN`, because a backslash in the env file is read as an escape character. |
| `AECB_API_DOMAIN` | If the account is domain-qualified | Windows domain of the service account |
| `AECB_API_PASSWORD` | Yes | Service account password |
| `AECB_ARCHIVE_DIR` | Recommended | `/var/lib/aecb-analyzer/api_responses`. Must be outside the application folder; unset turns archiving off. |
| `AECB_LOG_DIR` | Recommended | `/var/log/aecb-analyzer`. If unset, logs go to journald only. |
| `AECB_AUDIT_USER_HEADER` | Recommended | The header the reverse proxy sets to the authenticated user (see [Reverse proxy](#reverse-proxy-required)) |

The API endpoint and timeout come from `config/api.json` in the release
(`base_url`, `timeout_seconds`). That file must not contain credentials: a
file with an `auth` block is refused. Policy files in `config/` are part of
the release. Change them in the repository and ship a new release, so every
change is reviewed and versioned.

Never commit a filled-in env file.

## Run

```bash
ln -sfn /opt/aecb-analyzer-releases/aecb-analyzer-<version> /opt/aecb-analyzer
cp /opt/aecb-analyzer/deploy/aecb-analyzer.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now aecb-analyzer
systemctl status aecb-analyzer
curl -s http://127.0.0.1:8501/_stcore/health          # expect: ok
```

The unit `deploy/aecb-analyzer.service` runs as follows:

- It runs `.venv/bin/python -m streamlit run app_api.py --server.address
  127.0.0.1 --server.port 8501` as user `aecb`, in
  `WorkingDirectory=/opt/aecb-analyzer`.
- It loads `EnvironmentFile=/etc/aecb-analyzer/aecb.env`.
- It restarts on failure after 5 seconds.
- Hardening: `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=strict`,
  `ProtectHome`, and `UMask=0077`. Only `/var/lib/aecb-analyzer` and
  `/var/log/aecb-analyzer` are writable (`ReadWritePaths`). If you move the
  archive or log folder, add the new path with `systemctl edit
  aecb-analyzer`.

**First-run check.** Through the proxy, query a known subject id. Then
confirm three things:

- the report renders;
- an audit line appears ([Logs and audit](#logs-and-audit));
- a new file appears in the archive folder, unless archiving is
  deliberately off (the sidebar then says why).

## Reverse proxy (required)

The application has **no login of its own**. It binds to `127.0.0.1` and must
be reached only through a reverse proxy on the same host that does the
following:

- terminates TLS;
- authenticates every request against the bank's SSO before anything reaches
  the app;
- forwards to `http://127.0.0.1:8501`, including WebSocket upgrades (Streamlit
  uses a WebSocket at `/_stcore/stream`) and cookies (Streamlit's XSRF
  protection is on);
- passes the authenticated user name in a request header, **overwriting any
  value the client sent**. Set `AECB_AUDIT_USER_HEADER` to that header's name
  so every audit line records who queried which subject.

Serve the app at the site root. A sub-path needs `--server.baseUrlPath` added
to the unit's command line.

Illustrative nginx location block. The SSO module and the variable that
carries the user depend on the bank's integration:

```nginx
location / {
    # ... SSO authentication directives ...
    proxy_pass http://127.0.0.1:8501;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Remote-User $sso_user;   # replaces any client-sent value
    proxy_read_timeout 3600;
}
```

## Streamlit settings (`.streamlit/config.toml`)

Streamlit reads this file from the working directory. Port and bind address
come from the unit's command line.

| Setting | Value | Why |
|---|---|---|
| `server.headless` | `true` | No browser or interactive prompts on a server |
| `server.runOnSave`, `server.fileWatcherType` | `false`, `"none"` | Code does not change under a running app |
| `server.enableXsrfProtection` | `true` | XSRF protection on |
| `server.maxUploadSize` | `10` (MB) | Caps uploads. The production entry has no uploader. |
| `browser.gatherUsageStats` | `false` | Air-gapped; no telemetry |
| `client.showErrorDetails` | `"none"` | No tracebacks, paths or code in the browser |
| `client.toolbarMode` | `"viewer"` | Hides developer options |
| `runner.magicEnabled` | `false` | No implicit output |
| `logger.level` | `"info"` | Streamlit's own log level |

## Logs and audit

- **Always:** stderr, collected by journald: `journalctl -u aecb-analyzer`.
- **With `AECB_LOG_DIR`:** `aecb.log` in that folder, rotated at 10 MB with
  10 backups (`aecb.log.1` … `aecb.log.10`).
- **Format:** `<timestamp> <LEVEL> <logger>: <message>`.

| Logger | Contents |
|---|---|
| `aecb.audit` | One line per query: `query subject='<id>' outcome=ok\|failed user='<user or ->' client_ip=<address or ->` |
| `aecb.api` | API failures: status, all response headers, and the body up to 16,000 characters. Also connection errors. |
| `aecb.app_api` | Rejected responses (with the reason) and render failures (full traceback) |
| `aecb.archive` | Each archived file (subject, path, bytes), or why a response was not archived |

The logs contain CB subject ids, because they are the audit trail. They never
contain payload content, and successful responses are never logged. Treat the
logs as confidential and retain them according to policy.

`user` comes from the header named by `AECB_AUDIT_USER_HEADER`. `client_ip` is
the address Streamlit sees. Behind a proxy on the same host that address is
the local proxy connection, which Streamlit reports as no address (`-`), so
use the proxy's access log for end-user addresses.

## API response archive

Each successful, validated response is written verbatim to
`$AECB_ARCHIVE_DIR/<subject>_<YYYYMMDD_HHMMSS>.json`:

- The timestamp is server local time.
- A same-second collision gets `_1`, `_2`, and so on. A file is never
  overwritten.
- The folder is created with mode 0700 and each file with mode 0600.
- If `AECB_ARCHIVE_DIR` is unset, or points inside the application folder,
  archiving is **off**. The report sidebar then shows the reason and the log
  records every unarchived response.
- A failed write is logged and does not affect the user.

**Retention is an operations task.** The application never deletes archived
files. Schedule a purge with the retention period **N days taken from the
data-retention policy**:

```bash
find "$AECB_ARCHIVE_DIR" -type f -name '*.json' -mtime +N -delete
```

Example cron entry (`/etc/cron.d/aecb-archive-purge`):

```
30 2 * * *  aecb  find /var/lib/aecb-analyzer/api_responses -type f -name '*.json' -mtime +N -delete
```

Or as a systemd timer:

```ini
# /etc/systemd/system/aecb-archive-purge.service
[Service]
Type=oneshot
User=aecb
ExecStart=/usr/bin/find /var/lib/aecb-analyzer/api_responses -type f -name '*.json' -mtime +N -delete

# /etc/systemd/system/aecb-archive-purge.timer
[Timer]
OnCalendar=daily
Persistent=true
[Install]
WantedBy=timers.target
```

Then run `systemctl enable --now aecb-archive-purge.timer`. The archive holds
real bureau data. Any backup of it must follow the same retention period.
Each file is a few hundred KB, so monitor disk usage.

## Dependency audit

Audit the exact deployed tree, `requirements.lock`, whenever the lock changes
and on the security team's schedule. On a connected machine:

```bash
python3 -m venv /tmp/audit && /tmp/audit/bin/pip install pip-audit
/tmp/audit/bin/pip-audit --disable-pip -r requirements.lock
```

Mend (or another scanner) should scan `requirements.lock`, not
`requirements.txt`. Findings on the Python 3.9 runtime are assessed in
[DEPENDENCY_RISK.md](DEPENDENCY_RISK.md). Update that register after each
review.

## Troubleshooting

The user sees a short message. The detail is always in the server log ([Logs and audit](#logs-and-audit)).

| Symptom (on screen or in the log) | Cause | Action |
|---|---|---|
| "…answered HTTP 401… The service-account credentials were rejected" | Wrong account, domain or password | Check `AECB_API_USERNAME`, `AECB_API_DOMAIN` and `AECB_API_PASSWORD` in `aecb.env`, then `systemctl restart aecb-analyzer`. |
| "The bureau-report API service account is not configured" | `AECB_API_USERNAME` is empty in the process environment | Check that `aecb.env` exists, is filled in, and is loaded by the unit (`systemctl show aecb-analyzer -p EnvironmentFiles`). |
| "config/api.json must not carry credentials…" | `config/api.json` still has an `auth` block | Remove the block. Credentials belong in `aecb.env`. |
| "config/api.json is missing", "…is not valid JSON", "…carries no base_url" | Broken endpoint config | Restore `config/api.json` from the release. |
| "The bureau-report API is not reachable" | Network, firewall, DNS or endpoint down; timeout | The `aecb.api` log line names the URL and the error. Test connectivity from the server. |
| "…closed the connection during authentication" / "The server did not offer an NTLM challenge" | The IIS endpoint is not keeping the connection alive, or is not offering NTLM | Raise it with the API team, including the logged response headers. |
| "…returned an oversized response" | Response over 20 MB | Raise it with the API team. This is not a bureau payload. |
| "…the response is not a readable AECB payload" | The response is not JSON, or not an AECB report. Also shown when a `config/*.json` policy value is invalid. | Read the logged reason in `aecb.app_api`. If it names a `config/…` key, the release's configuration is at fault, not the payload. |
| "Failed to render the report for subject `…`" | An exception while rendering | The `aecb.app_api` log has the traceback. Keep the archived response for the developers. |
| A generic Streamlit error page | An uncaught error, for example a missing `config/*.json` file | journald carries the traceback. Restore the release files. |
| Sidebar: "Response archiving is off…" | `AECB_ARCHIVE_DIR` is unset or inside the application folder | Set it to a folder outside the application folder that is writable under `ReadWritePaths`. |
| Log: "Could not archive API response…" | Permission or disk problem in the archive folder | Check ownership (`aecb`), free space and `ReadWritePaths`. |
| journald: "Cannot write logs to AECB_LOG_DIR=…" | The log folder is not writable | Fix ownership or `ReadWritePaths`. Logging continues to journald. |
| "A CB subject id is up to 40 letters, digits, hyphens or underscores." | Input validation | Enter the id without spaces or other characters. |
| "Subject id mismatch" warning above the report | The API returned a report for a different subject | Do not act on the report. Raise it with the API team, citing the audit line. |

## Upgrade and rollback

**Upgrade:**

1. [Build](#build-the-wheel-bundle-connected-machine) and [package](#package-a-release-connected-machine) the new release.
2. Install it into a new folder under `/opt/aecb-analyzer-releases/` ([Install](#install-server)).
   Leave the running release and its `.venv/` in place.
3. If `aecb.env.example` gained variables, update `aecb.env`.
4. If `deploy/aecb-analyzer.service` changed, copy it and run `systemctl
   daemon-reload`.
5. Switch the active release and restart:

   ```bash
   ln -sfn /opt/aecb-analyzer-releases/aecb-analyzer-<new> /opt/aecb-analyzer
   systemctl restart aecb-analyzer
   ```

6. Repeat the first-run check ([Run](#run)).

**Rollback:** point the symlink back to the previous release folder, which
still has its own `.venv/`, and restart. If the unit file changed, restore
the previous one and run `daemon-reload` first.

Keep at least the previous release folder until the new one has been accepted.
The archive and log folders are shared across releases and are not affected.

## Not deployed

- **`app.py`** (the fixture picker, uploader and CSS reload) is excluded from
  the release archive.
- **The AI brief** (`aecb/brief/`, Ollama, `scripts/check_brief.py`,
  `scripts/eval_brief.py`) is not part of UAT. The code ships inside the
  `aecb` package but `app_api.py` never imports it. The production page has
  no AI Analysis button or panel, and no model service is installed. See
  [AI_BRIEF_MRM.md](AI_BRIEF_MRM.md).
- **`scripts/`, `tests/`, `docs/`** are development and review material only.
