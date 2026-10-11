# Research brief — 0.3.0 release-readiness epic

- **Date:** 2026-10-10
- **Repository:** traefik-certificate-exporter @ `2139ad8` (`main`)
- **Inputs:** `_bmad-output/implementation-artifacts/review-all-epics-2026-10-10/` (SUMMARY.md; review-product.md B1, B2, M1–M8; review-cicd.md F-07, F-09, F-10, F-11, F-18)
- **Method:** every fact below was checked against an upstream source (`gh api` on the named repo@ref, PyPI JSON, OSV, official docs) or a local probe on 2026-10-10. Throwaway probe files lived under `/tmp` and have been deleted. No repository source was modified.
- **Assumption recorded:** where the brief says "recommended", the brief makes the choice. Each choice is marked so that planning can overturn it. Nothing here is an ADR. Items that need one say so.

---

## 1. Docker SDK for Python (B1)

### Facts

| Fact | Source |
|---|---|
| Latest release: **7.2.0** (2026-07-09). Earlier: 7.1.0 (2024-05-23), 7.0.0 (2023-12-08), 6.1.3 (2023-06-01). | `gh api repos/docker/docker-py/releases` |
| Fix for `Not supported URL scheme http+docker` with requests ≥ 2.32: **7.1.0**, "Fixed an issue due to an update in the requests package breaking docker-py by applying the suggested fix" (PR docker/docker-py#3257, "Fix for requests 2.32"). | docker/docker-py release `7.1.0` notes |
| 7.2.0 runtime constraints: `requires_python >=3.8`; `requests>=2.26.0`, `urllib3>=1.26.0`, `pywin32>=304` (win32 only). Extras: `ssh` (paramiko), `websockets` (websocket-client). | `https://pypi.org/pypi/docker/7.2.0/json` |
| 6.1.3 required `packaging`, `requests>=2.26.0`, `urllib3>=1.26.0`, `websocket-client>=0.32.0`. **Neither 6.1.3 nor 7.x depends on `docker-pycreds`.** docker-py has shipped its own `docker/credentials/` package (present at 7.2.0) | `https://pypi.org/pypi/docker/6.1.3/json`; `gh api repos/docker/docker-py/git/trees/7.2.0?recursive=1` |
| `docker-pycreds` latest is 0.4.0, released 2018-11-29. Nothing in `src/` imports it (review m8). | PyPI JSON; review-product.md m8 |

**Breaking changes from 6.1.3 to 7.2.0, checked against `src/traefik_certificate_exporter/libs/docker.py`.** The module calls `docker.from_env()`, `client.containers.list(filters={"label": …})`, `c.labels`, `c.id` and `c.restart()`.

- 7.0.0 removed `ssl_version` and `assert_hostname`, made websocket support an opt-in extra, and dropped Python 3.7. The code uses none of these. **No impact.**
- 7.0.0 now consistently raises `docker.errors.NotFound` on a 404. This is relevant to a deferred restart (Q6), because the container can disappear between list and restart. The code already catches `Exception`.
- 7.1.0 raised the minimum Engine API to 1.24 and the default to 1.44. `from_env()` negotiates the version (`version=None` → auto). **No impact** for supported engines.
- **7.2.0 behaviour change:** "`docker.from_env()` now honors the active Docker CLI context when `DOCKER_HOST` is not set." The source has a new kwarg, `use_context` (default `True`), and falls back to `ContextAPI.kwargs_from_context` when `DOCKER_HOST` is unset (docker/docker-py@7.2.0:docker/client.py `from_env`).
  - In the container, `HOME` is the tmpfs `/run/traefik-certificate-exporter/home` or `/root`, with no `~/.docker/config.json`, so the client stays on the default socket.
  - A PyPI install on a workstation with a non-default context (for example Docker Desktop or a remote context) would now restart containers on **that** daemon. It previously targeted `unix:///var/run/docker.sock`.
  - **Recommendation:** call `docker.DockerClient.from_env(use_context=False)` so behaviour does not change silently. The other option is to accept context support and document it. Either way, record the choice in the restart ADR (see Q6).

### Local probe (2026-10-10, Python 3.11.11, fresh venv per combination, `/var/run/docker.sock` present)

| Combination | `DockerClient(base_url="unix:///var/run/docker.sock").ping()` | `containers.list(filters={"label": DOCKER_LABEL})` | Client on a missing socket |
|---|---|---|---|
| docker 6.1.3 + requests 2.32.3 + urllib3 2.2.2 (the lock) | `DockerException: Error while fetching server API version: Not supported URL scheme http+docker` | n/a | the same scheme error |
| docker 7.1.0 + requests 2.34.2 + urllib3 2.8.0 | `True` | `0` | `DockerException … ('Connection aborted.', FileNotFoundError(2, …))` |
| docker 7.2.0 + requests 2.34.2 + urllib3 2.8.0 | `True` | `0` | same as 7.1.0 |

### Recommended fix

1. In `pyproject.toml`: set `docker = "^7.2"`, set `requests = "^2.34"`, and lock.
   - Better still, **remove `requests`** from the direct dependencies. Nothing in `src/` imports it (review m8), and it comes in transitively through docker and apprise.
   - **Remove `docker-pycreds`.** Nothing depends on it.
2. In `docker.py`: use `docker.DockerClient.from_env(use_context=False)` (recommended; see above).

### Risks

- Engine API floor 1.24: engines older than Docker 1.12 cannot be reached. This is acceptable.
- The 7.2 context behaviour (above).
- `requests` 2.33+ and `urllib3` 2.5+ also move apprise's transitive set. Run the apprise tests after relocking.

### Minimal test that would have caught B1

An **unmocked** test:

- build `docker.DockerClient(base_url=f"unix://{tmp_path}/missing.sock")`;
- call `.ping()`;
- assert that it raises `docker.errors.DockerException` and that `"Not supported URL scheme"` is **not** in `str(exc)`.

The test needs no daemon. It fails on the shipped lock and passes on ≥ 7.1. A second, optional test: if `/var/run/docker.sock` exists, `ping()` is `True` (mark it skip-if-absent).

**Verified on:** 2026-10-10. Sources: GitHub docker/docker-py releases 7.0.0, 7.1.0 and 7.2.0, plus `docker/client.py@7.2.0`; PyPI JSON for docker 6.1.3 and 7.2.0; local venv probe.

---

## 2. cryptography and PKCS#12 (B2)

### Facts

| Fact | Source |
|---|---|
| Lock: `cryptography` **50.0.1**. Latest: **50.0.2** (2026-09-30). 50.0.2 only rebuilds wheels against OpenSSL 4.0.3, adds `abi3.abi3t` wheels and moves to PyO3 0.29.2. | `poetry.lock`; PyPI JSON; `pyca/cryptography` CHANGELOG.rst (main) |
| No OSV advisories against 50.0.1. | OSV `querybatch` |
| `load_pem_private_key(unencrypted_pem, password=b"…")` raises `TypeError: Password was given but private key is not encrypted.` | local probe, cryptography 50.0.2 |
| `serialize_key_and_certificates(name, key, cert, cas, BestAvailableEncryption(pw))` produces: MAC sha256 (2048 iterations); certificates and key in **PBES2 / PBKDF2 / AES-256-CBC, 20000 iterations, PRF hmacWithSHA256**. | local probe, then `openssl pkcs12 -info` (OpenSSL 3.5.5) |
| `PrivateFormat.PKCS12.encryption_builder().kdf_rounds(50000).key_cert_algorithm(pkcs12.PBES.PBESv1SHA1And3KeyTripleDESCBC).hmac_hash(hashes.SHA1()).build(pw)` produces: MAC sha1; `pbeWithSHA1And3-KeyTripleDES-CBC`. | same probe |
| cryptography's own documentation: "With OpenSSL 3.0.0+ the defaults for encryption when serializing PKCS12 have changed and some versions of Windows and macOS will not be able to read the new format. Maximum compatibility … SHA1 … PBESv1SHA1And3KeyTripleDESCBC … users should avoid this unless required for compatibility." | `pyca/cryptography@50.0.2:docs/hazmat/primitives/asymmetric/serialization.rst:911-918` |
| Windows: "Microsoft only supports two encryption/hash algorithms for importing a PFX: TripleDES-SHA1, AES256-SHA256." "Windows 11, Windows 2019, and later versions of Windows support AES256-SHA256 encrypted PFX files." The AES256 export parameters require Windows 10 1709 or Server 2019 at minimum. | learn.microsoft.com: `PFXImportCertStore` remarks; "Can't import an AES256-SHA256-encrypted PFX certificate"; `PKCS12_PBES2_EXPORT_PARAMS` |

### The exact bug (B2)

**Where:** `certificate_exporter.py:625`, in `PemToPfxConverter.export_to_pkcs12`:

```python
key = serialization.load_pem_private_key(key_data, password=passphrase)
```

**Why it fails:**

- The ACME key read from `acme.json` is an **unencrypted** PEM (`b64decode(c["key"])`, `:420`).
- `passphrase` is the *output* PFX passphrase (`settings.pkcs12passphrase`).
- So any non-`None` passphrase raises `TypeError`.

**What happens next:**

- The exception escapes to the per-certificate `except` (`:524-525`), which runs *after* `privkey.pem`, `cert.pem`, `chain.pem` and `fullchain.pem` (or their flat equivalents) were already replaced atomically.
- `names.append(name)` (`:515`) is skipped, so the domain is never reported.
- As a result, the restart, the post-export hook and the notification are all skipped for that domain.

### Two adjacent defects found while reading (not in the review; verified by probe)

- **PFX has no chain.** `export_to_pkcs12` receives `cert` (the leaf slice) and passes `cas=None` (`:483-488`, `:508-513`, `:653`), so the `.pfx` holds the leaf only. Windows/IIS and Java consumers then have to fetch the intermediates themselves.
  - Fix: parse `fullchain` with `x509.load_pem_x509_certificates(...)`; this probe returned 2 certificates for a 2-cert bundle.
  - Then pass `certs[0]` as `cert` and `certs[1:]` as `cas`.
- **Single-certificate `fullchain` is sliced wrongly.** `fullchain.find("-----BEGIN CERTIFICATE-----", 1)` returns `-1`.
  - The probe gave `cert = fullchain[0:-1]`, which drops the final newline, and `chain = "\n"`.
  - Parsing the list as above fixes this as well.

### Recommended fix

```python
key = serialization.load_pem_private_key(key_data, password=None)   # ACME keys are unencrypted
certs = x509.load_pem_x509_certificates(fullchain_bytes)
enc = serialization.BestAvailableEncryption(passphrase) if passphrase else serialization.NoEncryption()
pkcs12.serialize_key_and_certificates(name, key, certs[0], certs[1:] or None, enc)
```

- **Algorithm choice (recommended):** keep `BestAvailableEncryption`, which gives AES-256/SHA-256. Every OpenSSL 3, Windows 10 1709+/Server 2019+ and current macOS consumer reads it.
- **Optional:** add a setting `pkcs12legacy` (bool, default false) that switches to the documented 3DES/SHA1 builder for Server 2016 and older. Ship it only if a user asks; YAGNI otherwise.
- Treat `""` as "no passphrase" (the snippet's truthiness test). Today an empty env value would encrypt with an empty password.

### Risks

- Adding `cas` changes the `.pfx` contents. That is the intended improvement, and the release note should mention it.
- The legacy algorithm is weak by design and should be opt-in only.

### Minimal tests that would have caught B2

1. **Round trip.** Generate an EC key plus a CA-signed leaf in the test, base64 them into an ACME v2 fixture, export with `pkcs12Passphrase="s3cret"`, and assert all of:
   - `pkcs12.load_key_and_certificates(pfx, b"s3cret")` returns a key, the leaf, and `len(cas) == 1`;
   - the domain **is** in the returned list.
2. **Single-cert fullchain.** Export, then assert that `cert.pem` equals the input byte for byte.

**Verified on:** 2026-10-10. Sources: PyPI JSON; OSV; `serialization.rst@50.0.2`; Microsoft Learn (3 pages); local probe with cryptography 50.0.2 and OpenSSL 3.5.5.

---

## 3. Traefik ACME store format (M3, M4)

### Facts

| Fact | Source |
|---|---|
| Latest v3: **v3.7.14** (2026-10-06). Latest v2: **v2.11.58** (2026-10-06). Master read at `6e722fee4ed4`. | `gh api repos/traefik/traefik/releases` |
| The file is `map[resolverName]*StoredData`; `json.Unmarshal(file, &s.storedData)`. | `traefik@master:pkg/provider/acme/local_store.go:91-118` (identical logic at v3.7.14 and v2.11.58; only the logger calls differ) |
| `type StoredData struct { Account *Account; Certificates []*CertAndStore }`. There are **no JSON tags**, so the keys are `"Account"` and `"Certificates"`. | `pkg/provider/acme/store.go:4-7` (master = v3.7.14 = v2.11.58) |
| `type Account struct { Email string; Registration *Resource; PrivateKey []byte }`; `type Resource struct { Body acme.Account \`json:"body"\`; URI string \`json:"uri,omitempty"\` }`. | `pkg/provider/acme/account.go:17-26` (master) |
| `CertAndStore { Certificate; Store string }`. The embedded `Certificate` has `Domain types.Domain \`json:"domain,omitempty"\``, `Certificate []byte \`json:"certificate,omitempty"\``, `Key []byte \`json:"key,omitempty"\``. `types.Domain { Main \`json:"main,omitempty"\`; SANs \`json:"sans,omitempty"\` }`. | `pkg/provider/acme/provider.go:87-98` (master), `:60-71` (v2.11.58); `pkg/types/domains.go:10-15` |
| `[]byte` encodes as base64. **A nil slice or pointer encodes as `null`**, so `"Certificates": null`, `"Account": null` and `"Registration": null` are all valid stores. `sans` is omitted when empty. `"Store"` is usually `"default"`. | local Go probe that marshals copies of the structs above |
| On load, Traefik drops entries whose certificate or key is empty, then rewrites the file. | `local_store.go` `get()` |
| `Registration.uri` is the **account URL at the CA**, for example `https://acme-v02.api.letsencrypt.org/acme/acct/…` or a ZeroSSL, Google or step-ca URL. It identifies the CA, **not** the ACME protocol version; every current CA speaks RFC 8555. | account.go `GetRegistration` uses it as `Location` |
| Traefik v1.7 (the "uppercase" form the parser also handles) had a single unkeyed `StoredData { Account, Certificates []*Certificate, HTTPChallenges, TLSChallenges }` with `Certificate { Domain types.Domain; Certificate; Key }` and no tags (`"Domain":{"Main","SANs"}`). The legacy ACME-v1 `Account` carried `DomainsCertificate.Certs`. | `traefik@v1.7.34:provider/acme/store.go:4-9`, `provider.go:74-78`, `acme/account.go:25-33,156-159` |

### Defects confirmed against the parser (`certificate_exporter.py:335-358`, `:543-586`)

- **Version detection (`:335`).** `"acme-v02" in data["Account"]["Registration"]["uri"]`:
  - a non-Let's-Encrypt CA is treated as v1, which gives `KeyError 'DomainsCertificate'`;
  - `Account: null` or `Registration: null` gives `TypeError`.
- **Null certificates (`:356-358`).** `certs = data["Certificates"]` is `None` when the value is `null`, and `for c in None` raises **outside** the per-cert `try`.
  - The exception reaches `exportCertificatesForFile`'s `except` (`:584-586`), which returns `None`.
  - Domains already written by earlier resolvers are discarded from the result (M4).
- **Resolver auto-detect (`:563-569`).** It tests only `elementNames[0]`; an empty `{}` file raises `IndexError` there.

### Recommended parsing (CA-agnostic, shape-based)

```text
def resolver_entries(data):                      # data = parsed acme.json (dict)
    if is_resolver_node(data): yield (None, data); return     # v1.7 single store
    for name, node in data.items():
        if isinstance(node, dict) and is_resolver_node(node): yield (name, node)
        else: log WARNING "skipping non-resolver key"
def is_resolver_node(n):  return any(k.lower() in ("certificates", "account") for k in n)
def certificates(node):
    certs = case_insensitive_get(node, "Certificates")
    if certs is None:      # v2/v3 null, or legacy v1
        legacy = (case_insensitive_get(node, "Account") or {}).get("DomainsCertificate") \
                 or node.get("DomainsCertificate")
        certs = (legacy or {}).get("Certs") or []
    return certs
```

- **Field access per entry:**
  - Read the domain as `domain.main`, falling back to `Domain.Main`.
  - Read the key as `key`, falling back to `Key`.
  - Read the certificate as `certificate`, falling back to `Certificate`, which may be a nested object in legacy v1 (`Certificate.Certificate`/`PrivateKey`/`Domain`).
  - The lower/upper choice should come from **which keys exist**, not from whether a resolver id was configured (today `keys` is chosen at `:551-569`).
- **Never read `Account.Registration.uri`.** The CA identity is informational only; log it at DEBUG, null-safe.
- **Per-resolver isolation (M4).** Wrap each resolver in its own `try`. A failure logs ERROR with the resolver name and moves on.
  - `exportCertificatesForFile` returns the union of domains that actually wrote at least one artifact.
  - It also returns the per-resolver failure count, so a caller can WARN.
  - Report a domain as soon as its first artifact is replaced (review M4), or build the PFX in memory **before** any rename so that all five files commit together. Recommended: build the PFX first, then write all files, then report. That removes the B2 class of partial rotation entirely.

### Risks

- Accepting more shapes widens the attack surface on untrusted input. The existing `_is_safe_path_component` checks on resolver and domain names must stay ahead of any path join; they already do.
- `Store` other than `"default"` is not modelled. Ignoring it is fine.

### Minimal tests that would have caught M3/M4

Fixtures written as JSON literals:

- **(a)** A v3 store with `uri: "https://acme.zerossl.com/v2/DV90/account/x"` → its domain is exported.
- **(b)** Two resolvers, the second with `"Certificates": null` → the first resolver's domains are returned, not `None`.
- **(c)** `"Account": null` → no crash.
- **(d)** `{}` → `[]`.

**Verified on:** 2026-10-10. Sources: traefik/traefik@master (6e722fee4ed4), @v3.7.14, @v2.11.58 and @v1.7.34; local `go run` probe of the struct encoding.

---

## 4. s6-overlay and the container service (M5)

### Facts

| Fact | Source |
|---|---|
| The pinned base `ghcr.io/linuxserver/baseimage-alpine:3.24@sha256:e17494fc…` contains **s6-overlay 3.2.1.0**, s6 2.13.2.0, s6-rc 0.5.6.0 and Alpine 3.24.1. Label: `aa9e94e5-ls8`, build 2026-08-29. Env: `S6_STAGE2_HOOK=/docker-mods`, `S6_VERBOSITY=1`, `S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0`. `S6_BEHAVIOUR_IF_STAGE2_FAILS` is **unset**, so the default 0 applies. | local `docker pull` + `ls /package/admin`; `docker inspect`; `docker/Dockerfile:6` |
| The upstream branch `3.24` currently also pins `S6_OVERLAY_VERSION="3.2.1.0"`. The latest s6-overlay is v3.2.3.2 (2026-07-16). The floating `ghcr.io/linuxserver/baseimage-alpine:3.24` tag has moved on to `sha256:d2deff7a…`, so Dependabot has a bump pending. | `gh api repos/linuxserver/docker-baseimage-alpine/contents/Dockerfile?ref=3.24`; `gh api repos/just-containers/s6-overlay/releases/latest`; `docker buildx imagetools inspect` |
| s6-supervise: "When ./run dies, s6-supervise spawns ./finish … When ./finish dies, s6-supervise … restarts ./run unless it has been told not to." "**If ./finish exits 125** … it does not restart the service, as if s6-svc -O had been called. This can be used to signify permanent failure." There is a minimum 1-second delay between `./run` spawns. | skarnet.org/software/s6/s6-supervise.html; servicedir.html |
| s6-overlay: a finish script that should end the container writes the exit code to `/run/s6-linux-init-container-results/exitcode` and runs `/run/s6/basedir/bin/halt`. The README notes "If a service is so important that the container needs to stop when it dies, we really recommend running it as the CMD." `S6_BEHAVIOUR_IF_STAGE2_FAILS` covers oneshot failures and readiness timeouts only, **not** a longrun that exits. | `just-containers/s6-overlay@v3.2.1.0:README.md:368-416,539-575,829-839` |
| **Local probe** on the pinned base with two s6-rc longruns that `exit 0`: `svc-loop` (no finish) was respawned **every second, 20 times in 20 s**, and `s6-svstat` showed "want up". `svc-once` (finish `exit 125`) ran once and stayed `down (exitcode 0) … normally up`. The container kept running. | local probe, image built `FROM` the pinned digest |

### Current behaviour

`svc-traefik-certificate-exporter/run:14` tests the **raw env var** `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES` against `true` or `1`. Otherwise it prints "Skipping start of application..." and exits 0.

- **Env false:** the probe shows a 1 Hz respawn loop of that message.
- **Config file says `watchforchanges: false` but the env default `true` from the Dockerfile (`:127`) wins:** the env outranks the file, so it runs.
- **Env unset by the operator and file false:** this cannot happen in the image (the Dockerfile sets it), but a `-e …=false` reaches the loop.
- **Env `yes` or `True`:** confuse accepts these but the shell test does not → loop.

So run-once is unusable. Worse, if the test passed, the exporter would exit after one pass and be re-run every second, repeating exports, hooks and notifications.

### Recommended fix (recommended choice: run-once ends the container)

1. Init resolver (`init-traefik-certificate-exporter-config/run`, the Python heredoc at lines ~49-81) appends `"true" if settings.watchForChanges else "false"` to the resolved file. This uses the same `SettingsManager` and is ADR-0030's "ask the installed package" principle.
2. The service `run` reads that line instead of the env var. It always `exec`s the exporter: in watch mode it runs forever, in run-once mode it runs one pass.
3. Add `svc-traefik-certificate-exporter/finish`:

   ```sh
   #!/bin/sh
   # $1 = exit code (256 if killed by signal), $2 = signal
   mode="$(sed -n '<line>p' /run/traefik-certificate-exporter/resolved 2>/dev/null)"
   [ "$mode" = "true" ] && exit 0                 # watch mode: normal s6 respawn
   if [ "$1" -eq 256 ]; then e=$((128 + $2)); else e="$1"; fi
   echo "$e" > /run/s6-linux-init-container-results/exitcode
   exec /run/s6/basedir/bin/halt                  # run-once: container exits with the pass's code
   ```

   - **Alternative (rejected as default):** `exit 125` keeps the container up and idle. That suits an always-on compose stack but hides the run-once result.
   - With `halt`, an orchestrator `restart: unless-stopped` policy re-runs the pass on its own schedule. **Document that run-once wants `restart: "no"`** (or a cron or systemd timer).
4. Document the container run-once contract in `docker/README.md`.

### Risks

- `halt` under a `restart: always` policy turns into a container-level loop, slower than 1 Hz but real. The documentation is the mitigation.
- The resolved file is missing (init failed) → treat it as watch mode, which is the long-standing default, and log.

### Minimal test

Extend `tests/test_s6_privilege_drop.py`'s script-level harness, or add a container smoke test in `just image`:

- with `…_WATCHFORCHANGES=false`, `docker run` exits within N seconds with code 0;
- the log shows exactly one "Processing file" pass.

A unit-level check: the service `run` script contains no reference to `$TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_` (a pygrep hook). That stops the second parser coming back.

**Verified on:** 2026-10-10. Sources: pinned base image inspection; linuxserver/docker-baseimage-alpine@3.24; s6-overlay README@v3.2.1.0; skarnet s6-supervise and servicedir pages; local s6 probe.

---

## 5. Settings naming (M1, M2, BL-E013-042)

### Mechanics

- **confuse 2.2.1 (lock; latest 2.3.0, 2026-09-22).** `EnvSource(prefix, sep="__", lower=True, handle_lists=True, parse_yaml_docs=False)`:
  - strips the prefix, **lowercases**, splits on `sep`, and parses values as YAML scalars;
  - integer-keyed sub-dicts become lists.
  - Source: `beetbox/confuse@v2.2.1:confuse/sources.py:110-182`.
- **This project:** `set_env(prefix="TRAEFIK_CERTIFICATE_EXPORTER_", sep="_")` (`settings.py:308`).
  - Every `_` is a nesting separator, so config keys can never contain `_`. This is why keys are concatenated lowercase.
- **CLI:** `set_args(namespace, dots=True)` splits `dest` on `.` (`confuse/core.py:164-182`).
- **Precedence:** CLI > env > file > default (`settings.py:287-320`).

### Authoritative table (derived from `settings.py:352-376` reads, `cli_args.py`, `config_default.yaml`)

| Setting key | CLI flag (`dest`) | Env var | Default |
|---|---|---|---|
| `settings.datapath` | `-d/--data-path` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DATAPATH` | `./data` (image `/data`) |
| `settings.filespec` | `-fs/--file-spec` | `…_SETTINGS_FILESPEC` | `*.json` |
| `settings.outputpath` | `-o/--output-path` | `…_SETTINGS_OUTPUTPATH` | `./certs` (image `/certs`) |
| `settings.traefikresolverid` | `--traefik-resolver-id` | `…_SETTINGS_TRAEFIKRESOLVERID` | unset (commented out in config_default) |
| `settings.resolverinpathname` | `--include-resolvername-in-outputpath` | `…_SETTINGS_RESOLVERINPATHNAME` | `true` |
| `settings.flat` | `--flat` | `…_SETTINGS_FLAT` | `false` |
| `settings.dryrun` | `--dry-run` | `…_SETTINGS_DRYRUN` | `false` |
| `settings.restartcontainers` | **`--restart-container` writes `settings.restartcontainer` — DEAD (M1)** | `…_SETTINGS_RESTARTCONTAINERS` | `false` |
| `settings.domains.include` | `-id/--include-domains` | `…_SETTINGS_DOMAINS_INCLUDE` (comma list, split by `_parse_domain_list`) | `[]` |
| `settings.domains.exclude` | `-xd/--exclude-domains` | `…_SETTINGS_DOMAINS_EXCLUDE` | `[]` |
| `settings.watchforchanges` | `-w/--watch-for-changes` | `…_SETTINGS_WATCHFORCHANGES` | `false` (image `true`) |
| `settings.runatstart` | `-r/--run-at-start` | `…_SETTINGS_RUNATSTART` | `false` (image `true`) |
| `settings.watchinterval` | none | `…_SETTINGS_WATCHINTERVAL` | `60` |
| `settings.pkcs12passphrase` | `--pkcs12-passphrase` | `…_SETTINGS_PKCS12PASSPHRASE` | unset |
| `settings.postexportcommand` | `--post-export-command` | `…_SETTINGS_POSTEXPORTCOMMAND` | unset |
| `settings.appriseurls` | none | `…_SETTINGS_APPRISEURLS_0`, `_1`, … | `[]` |
| (not confuse) config file path | `-c/--config-file` (`dest=configfile`) | **none.** `…_CONFIGFILE` lands in confuse as key `configfile`, but nothing reads it; `app.py` uses `globalArgs.configfile` | `config.yaml` (image `/config/config.yaml` via svc argv) |
| (not confuse) log level | `-ll/--log-level` (`dest=logginglevel`) | **none.** `app.py:85-92` reads only `globalArgs.logginglevel` | `INFO` |
| (not confuse) logger selection | — | `…_LOGGING_CONSOLEONLY` (`os.getenv`, `logging_utils.py:279`) | image `true` |
| (not confuse) console JSON | — | `…_LOGGING_CONSOLEJSON` (`logging_utils.py:199`) | image `false` |
| (not confuse) logging config file | — | `…_LOGGING_CFGFILE` (`app.py:88`) | packaged `logging.yaml` |
| (hook output, not input) | — | `…_EXPORTED_DOMAINS`, `…_CORRELATION_ID` (set for the hook's env, `post_export.py:24,64`) | — |

### Documented names that map to nothing (scan of README.md, docker/README.md, docker/docker-compose.yml, docs/**/*.md)

| Location | Documented name | Should be |
|---|---|---|
| README.md:22,42; docs/operational.md:63 | `--restart-container` (works as a flag, writes a dead key) | fix `dest` → `settings.restartcontainers` |
| docker/README.md:138 | `…_CONFIGFILE` | delete (the path is fixed to `/config/config.yaml` by the svc argv) |
| docker/README.md:144 | `…_SETTINGS_RESTARTCONTAINER` | `…_SETTINGS_RESTARTCONTAINERS` |
| docker/README.md:150 | `…_LOGGINGLEVEL` | new setting (below) |
| docker/docker-compose.yml:7 | `…_CONFIG_FILE` | delete |
| docker/docker-compose.yml:8 | `…_FILESPEC` | `…_SETTINGS_FILESPEC` |
| docker/docker-compose.yml:9 | `…_RESOLVERID` | `…_SETTINGS_TRAEFIKRESOLVERID` |
| docker/docker-compose.yml:10 | `…_RESOLVERID_INOUTPUTPATHNAME` | `…_SETTINGS_RESOLVERINPATHNAME` |
| docker/docker-compose.yml:11 | `…_DRYRUN` | `…_SETTINGS_DRYRUN` |
| docker/docker-compose.yml:12 | `…_FLAT` | `…_SETTINGS_FLAT` |
| docker/docker-compose.yml:13 | `…_RESTART_CONTAINERS` | `…_SETTINGS_RESTARTCONTAINERS` |
| docker/docker-compose.yml:14-15 | `…_INCLUDE_DOMAINS` / `…_EXCLUDE_DOMAINS` | `…_SETTINGS_DOMAINS_INCLUDE` / `…_SETTINGS_DOMAINS_EXCLUDE` |
| docs/operational.md:207 | `…_NOTIFY_*` (Apprise URLs) | `…_SETTINGS_APPRISEURLS_<n>` |
| docs/operational.md:39; docker/README.md:115 | `-ll DEBUG` / `--log-level DEBUG` for the container | the container cannot pass argv (`svc run:26,31`); use the new env setting |

- **Also:** `docker/docker-compose.yml:1` uses the obsolete `version:` key.
- **Compose quoting (probe, Docker Compose v5.6.0):** in list form, `- FOO="/data"` gives the value `"/data"` *including the quotes*.
  - confuse's YAML-scalar parsing strips them.
  - The raw `os.getenv` readers (`LOGGING_*`) and the current svc `run` test do **not**.
  - Drop the quotes in the examples.

### How the container's log level is set today

It cannot be changed:

- `-ll` is CLI-only;
- the s6 service hard-codes `traefik-certificate-exporter -c /config/config.yaml`;
- `…_LOGGINGLEVEL` is read by nothing.

**Recommended:** add `logging.level` as a confuse key (env `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL`, config `logging: {level: INFO}`) with CLI `-ll` as the higher-precedence override. This fits the existing `LOGGING_*` env family.

The catch is that logging is set up **before** settings load (`app.py:85`). So either:

- load settings first with a bootstrap logger, or
- read `os.getenv("TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL")` in `app.py` as the fallback when `-ll` was not given. This is simplest and matches how `LOGGING_CONSOLEONLY` and `CONSOLEJSON` already work.

Recommended: the env fallback, with `-ll`'s argparse default changed to `None` so "not given" can be detected.

### Minimal tests (scope derived, global rule 4)

1. **Every parser `dest` is a known key.** For every action in `globalArgParser._actions` whose `dest` starts with `settings.`, assert the dotted path exists among the keys `SettingsManager` reads.
   - Derive that set by declaring every key in `config_default.yaml`: uncomment `traefikresolverid`, `pkcs12passphrase` and `postexportcommand` as `null` so the YAML is the single source.
   - Without that change, a scan reports those three as false positives (observed in this research).
2. **Every documented env name maps.** Regex-scan `README.md`, `docker/README.md`, `docker/docker-compose.yml` and `docs/**/*.md` for `TRAEFIK_CERTIFICATE_EXPORTER_[A-Z0-9_]+`.
   - Map each through confuse's rule (strip prefix, lowercase, split `_`, drop a trailing integer index).
   - Assert it is a `config_default.yaml` path or one of the explicit `os.getenv` names (`LOGGING_CONSOLEONLY`, `LOGGING_CONSOLEJSON`, `LOGGING_CFGFILE`, `LOGGING_LEVEL`) or a hook-output name.
   - This test, run today, reports exactly the rows above.

**Verified on:** 2026-10-10. Sources: confuse@v2.2.1 `sources.py` and `core.py`; PyPI confuse; repo files at `2139ad8`; `docker compose config` probe.

---

## 6. Restart cooldown semantics (M6)

### Current behaviour

From `docker.py:28,47-122`:

- `_reserveRestart` returns `False` inside 300 s, and the restart is **dropped** with an INFO log.
- A second rotation (for example, two resolvers or SAN changes renewing minutes apart, or a quick reissue after a revocation) leaves the container serving the stale certificate until an unrelated later ACME write.

The threading model is safe to extend:

- one `DockerManager` instance is shared by the start-up pass (`app.py:132`) and the watch handler, which receives it by injection (`certificate_exporter.py:722-726`);
- drains already run on daemon `threading.Timer` threads (`certificate_exporter.py:1021-1024`);
- shutdown cancels the pending drain (`app.py:186-192`, ADR-0026).

### Recommended design: defer, don't drop

- Keep `__lastRestart` and add `__pending: dict[str, threading.Timer]`, both under `self.__lock`.
- When a restart is denied:
  - if no timer is pending for that container id, arm `threading.Timer(remaining + 1, self._deferredRestart, args=(cid,))` with `daemon=True` and store it;
  - if one is pending, do nothing (coalesced: at most **one** trailing restart per container per window).
- `_deferredRestart(cid)`:
  - under the lock, pop the pending entry;
  - outside the lock, build a fresh client (`from_env`), `client.containers.get(cid)`, then `restart()`;
  - on `docker.errors.NotFound`, log INFO "container gone" and stop;
  - on any other error, log the exception and release the reservation as today;
  - on success, record `__lastRestart[cid] = now`.
  - Re-check the label at fire time, so a container whose label was removed is not restarted.
- Add `DockerManager.cancel()`, which cancels all pending timers, and call it from the same shutdown path as `event_handler.cancel()`.
- **Dry run:** log "[DRYRUN] would schedule deferred restart" and arm nothing.

### Is `threading.Timer` safe here? Yes, with these conditions (from reading the code, not a probe)

- The timers must be daemon threads (as the drain timers are), so shutdown is never blocked.
- The callback must not hold `self.__lock` across the Docker round trip; this matches the existing reserve/release pattern.
- The callback must tolerate `NotFound` (7.0.0 made 404 → `NotFound` consistent; see Q1).
- It must be cancellable at shutdown.
- In run-once mode a process runs one pass, so `__lastRestart` is empty and no deferral can arise. A deferral that is pending at exit is lost by design, and the next process start is "always eligible" (`docker.py:36-38`).
- **Record the cooldown and the defer semantics in an ADR.** Today the cooldown has none (review M6).

### Minimal test

- Patch `time.time` and use a fake client, **not** a patched `from_env` returning a MagicMock for everything; a small fake container class is enough.
- Call `restartLabeledContainers(["a.example"])` twice inside the window.
- Assert one immediate restart and one `Timer` armed.
- Call it a third time and assert there is still one timer (coalesced).
- Fire the timer callback directly and assert the second restart happened.
- `cancel()` → no restart.

**Verified on:** 2026-10-10. Sources: repo code at `2139ad8` (`docker.py`, `app.py`, `certificate_exporter.py`); docker-py 7.0.0 release notes (NotFound).

---

## 7. CI facts (F-07, F-09, F-10, F-11, F-18)

### (a) `type=semver,pattern={{major}}` on 0.x (F-11)

- **Both actions produce `0`.** Upstream `docker/metadata-action` (latest v6.2.0, 2026-07-02) `src/meta.ts` `procSemver` (lines 155-195 on master) compiles the pattern with no special case for major 0.
- The LiquidLogicLabs fork (`@v6` → `cb7a8cc34789`; latest v6.2.1, 2026-09-22) has the same `procSemver` at `src/meta.ts:156` and no major-zero handling.
- Its README §"Major version zero" (`README.md:988-1004` at `v6`) states: "Docker tag `0` **should not** be generated if you're using `type=semver` with `{{major}}` pattern. You can manage this behavior like this: … `type=semver,pattern={{major}},enable=${{ !startsWith(github.ref, 'refs/tags/v0.') }}`."
- **Recommended:** `release.yaml:290` passes `value=${{ needs.build.outputs.image-version }}`, so gate on that value rather than `github.ref`:

  ```yaml
  type=semver,pattern={{major}},value=${{ needs.build.outputs.image-version }},enable=${{ !startsWith(needs.build.outputs.image-version, '0.') }}
  ```

  Record it in AD-8.
- **Test:** an `act` dry run of `release.yaml` for tag `v0.3.0`, asserting the metadata `tags` output has no `:0`. Or a pygrep that every `pattern={{major}}` line carries `enable=`.

### (b) `concurrency` with `cancel-in-progress: false` (F-10)

- **GitHub docs** (`github/docs` `data/reusables/actions/actions-group-concurrency.md`, main):
  - "there can be at most one running job or workflow in a concurrency group at any time … By default, any existing `pending` job or workflow in the same concurrency group will be canceled and the new queued job or workflow will take its place."
  - The newer `queue` property: `single` (default: at most one pending; an existing pending run "is canceled and replaced") or `max` (up to 100 pending; "When the queue is full, any additional … are canceled").
  - "The combination of `queue: max` and `cancel-in-progress: true` is not allowed."
- So `release.yaml:12`'s comment "Releases queue; one is never cancelled mid-flight" is true only of the *running* release. With three tags pushed quickly, the **middle one is cancelled while pending**.
- **Fix option:** `queue: max` would give true FIFO on GitHub. But **actionlint v1.7.12 (latest, 2026-03-30) rejects it**: `parse.go:821-824` allows only `group` and `cancel-in-progress` under `concurrency` and reports other keys as unexpected.
  - Gitea runner support for `queue` is unverified.
- **Recommended for 0.3.0:** correct the comment and the walkthrough to "at most one running and one pending release; a third tag cancels the pending one — re-run it". Optionally make the group `release-${{ github.ref }}`; distinct tags then never cancel each other, at the cost of parallel releases.
  - Revisit `queue: max` when actionlint supports it.

### (c) zizmor `ref-pin` (F-07)

- **Latest zizmor is v1.30.1** (2026-09-09). The repo pins `v1.30.1` in `.pre-commit-config.yaml:104-105`.
- `unpinned-uses` policies are exactly `hash-pin`, `ref-pin` ("must be pinned either symbolic or SHA reference") and `any` (`zizmorcore/zizmor@v1.30.1:docs/audits.md` §unpinned-uses; unchanged on `main`).
- **There is no tag-only policy.** A branch ref passes `ref-pin`.
- `ref-version-mismatch` and `stale-action-refs` exist but address different problems.
- `.github/zizmor.yml` already says "NOT MECHANICALLY ENFORCED".
- **Recommended:** a `pygrep` hook over `^\.github/workflows/.*\.ya?ml$` that fails on `uses:\s*LiquidLogicLabs/[^@\s]+@(?!v\d+\s*(#.*)?$)` (review F-07). Then update the `zizmor.yml` comment, AD-5 and ADR-0035 to name the hook.
- **Test:** plant `LiquidLogicLabs/x@main` and `@v6.2.1` in a scratch workflow and confirm the hook fails on both. This attacks the scope as well as the rule.

### (d) Token off argv (F-09)

- **curl `-H/--header`:** "This option can take an argument in @filename style, which then adds a header for each line in the input file. Using @- makes curl read the header file from stdin. (Added in 7.55.0)" (`curl/curl@master:docs/cmdline-opts/header.md:48-50`). The local curl is 8.18.0.
- **Masking does not cover argv:**
  - GitHub masks registered secrets in logs.
  - The gitea/act runner's logger replaces every secret value with `***` (`gitea/act@main:pkg/runner/logger.go:160-172`, `valueMasker`).
  - Neither hides argv from `/proc/<pid>/cmdline` or `ps` on the runner host. GitHub's own guidance: "Avoid passing secrets between processes from the command line … consider using environment variables, `STDIN`" (`github/docs` `use-secrets.md:197`).
- **Recommended** for `dev.yaml:99` and `release.yaml:145`:

  ```sh
  code="$(printf 'Authorization: token %s\n' "$TWINE_PASSWORD" | curl -sS -o existing.json -w '%{http_code}' -H @- "$files_url")"
  ```

  `printf` is a bash builtin, so the token never appears in an exec'd argv.
- **Test:** a pygrep hook that fails on `curl[^\n]*-H\s+"Authorization:` in workflows.

### (e) ghcr.io anonymous pulls (F-18)

- **No published numeric limit.** A search of `github/docs` content for a ghcr anonymous pull rate limit found nothing. The only evidence is the observed `429 Too Many Requests` (run 38001947526, per review-cicd F-18).
- The linuxserver base image is **not** on Docker Hub: `hub.docker.com/v2/repositories/linuxserver/baseimage-alpine/tags/3.24` → not found. For comparison, Docker Hub documents 100 pulls per 6 h per IPv4 or IPv6 /64 for unauthenticated users (docs.docker.com/docker-hub/usage).
- **Trade-off.** Logging in to ghcr with `GITHUB_TOKEN` for the pull:
  - would need `packages: read`, which contradicts AD-13 ("no job widens" `contents: read`);
  - would put a credential into AD-2's credential-free build ("One build, no credentials"). That build runs for fork PRs too, where `GITHUB_TOKEN` is read-only anyway;
  - has no direct Gitea equivalent, so the forge behaviour diverges.
  - Reading is a lesser risk than publishing, but it still breaks two adopted rules and needs an ADR. Whether a `contents: read`-only token authenticates public ghcr pulls was **not verified**.
- **Recommended (credential-free, AD-2-consistent):**
  - (1) Pre-pull the pinned `BASE_IMAGE` digest with a bounded retry and backoff, for example 4 attempts at 15/30/60 s, before `docker buildx build`. Buildx then uses the local copy.
  - (2) Document "re-run on 429" in `docs/ci/pipeline-walkthrough.md`.
  - A pull-through registry mirror is an option only on self-hosted runners.
- **Test:** none practical for a 429. Assert by pygrep that the build job's pull step has the retry wrapper.

**Verified on:** 2026-10-10. Sources: docker/metadata-action@master `src/meta.ts`; LiquidLogicLabs/git-action-docker-metadata@v6 `README.md` and `src/meta.ts`; github/docs reusable + use-secrets; rhysd/actionlint@main `parse.go` and releases; zizmorcore/zizmor@v1.30.1 and @main `docs/audits.md`; curl/curl@master `header.md`; gitea/act@main `logger.go`; Docker Hub API and docs.

---

## 8. Runtime dependencies: lock vs latest, advisories

PyPI JSON was used for the latest versions. OSV `v1/query` and `v1/querybatch` were used against every locked package (main and dev).

| Package | Constraint | Locked | Latest (PyPI) | Advisories affecting locked version | Action |
|---|---|---|---|---|---|
| watchdog | `^2.1.9` | 2.3.1 | 6.0.0 | none | Raise to `^6.0`. Breaks 5.0 (keyword-only args, renames in inotify/watchmedo, Py3.8 drop) do not touch this code; `PatternMatchingEventHandler.__init__` is already called with keywords (`certificate_exporter.py:754-759`). Re-run the watch tests |
| docker | `^6.0.0` | 6.1.3 | 7.2.0 | none (functional blocker B1) | `^7.2` (Q1) |
| requests | `^2.28.1` | 2.32.3 | 2.34.2 | GHSA-9hjg-9r4m-mvj7 (MODERATE, .netrc leak, fixed 2.32.4); GHSA-gc5v-m9x4-r6x2 (MODERATE, temp-file reuse, fixed 2.33.0) | drop as a direct dep (unused); the transitive lock goes to ≥ 2.33.0 |
| docker-pycreds | `^0.4.0` | 0.4.0 | 0.4.0 (2018) | none | **remove** (unused, not required by docker) |
| confuse | `^2.0.1` | 2.2.1 | 2.3.0 | none | relock; re-run the precedence tests |
| python-dotenv | `^1.0.1` | 1.0.1 | 1.2.4 | GHSA-mf9w-mj56-hr94 (MODERATE, symlink follow in `set_key`, fixed 1.2.2). The code uses only `load_dotenv`, so it is not reachable, but upgrade anyway | `^1.2.2` |
| importlib-resources | `^6.4.0` | 6.4.0 | 7.1.0 | none | optional. Python ≥ 3.10 has `importlib.resources.files`; consider dropping the backport |
| jsonpickle | `^3.0.3` | 3.2.2 | 4.1.3 | none | relock within ^3 or evaluate 4 (major) |
| coloredlogs | `^15.0.1` | 15.0.1 | 15.0.1 (2021) | none | none (unmaintained; note) |
| logging-tree | `^1.9` | 1.10 | 1.10 | none | none |
| expandvars | `^0.12.0` | 0.12.0 | 1.1.2 | none | **remove** (unused, review m8) |
| cryptography | `^50.0.1` | 50.0.1 | 50.0.2 | none | relock to 50.0.2 |
| python-json-logger | `^4.2.0` | 4.2.0 | 4.2.0 | none | none |
| apprise | `^1.9.0` | 1.13.1 | 2.0.1 (2026-10-03) | none | stay on 1.x for 0.3.0; evaluate 2.0 (major) separately |
| *transitive* urllib3 | — | 2.2.2 | 2.8.0 | 8 GHSAs; 6 HIGH. Includes GHSA-2xpw-w6gg-jr37 and GHSA-gm62-xv2j-4w53 (decompression, fixed 2.6.0), GHSA-38jv-5279-wg99 (fixed 2.6.3), GHSA-qccp-gfcp-xxvc (fixed 2.7.0), GHSA-8988-9cw3-xx77 and GHSA-vxq7-64xx-v4gw (fixed 2.8.0) | relock to ≥ 2.8.0 |
| *transitive* idna | — | 3.7 | 3.20 | GHSA-65pc-fj4g-8rjx (MODERATE, fixed 3.15) | relock |
| *transitive* oauthlib (via apprise) | — | 3.3.1 | 4.0.0 | GHSA-hj66-6f7g-4r5v, GHSA-xpv3-w29h-x7cv (MODERATE; server-side endpoints, fixed 4.0.0) | relock if apprise permits; low reachability |
| *transitive* pyyaml | — | 6.0.1 | 6.0.3 | none | relock |
| *dev* virtualenv | — | 21.7.7 | — | 4 GHSAs (dev only) | relock dev group |

**Recommended:** run `poetry update` (all groups) after the constraint changes above, then `just check`.

**Gap:** no gate catches a vulnerable lock today. Add `pip-audit` (PyPA-maintained) as a pre-commit or `just check` step over `poetry export --only main`. If it is added, record it in the CI/CD spine; this is the global rule 3 "write the check with the rule".

**Verified on:** 2026-10-10. Sources: `https://pypi.org/pypi/<pkg>/json`; `https://api.osv.dev/v1/query`, `/v1/querybatch` and `/v1/vulns/<id>`; `poetry.lock` at `2139ad8`; watchdog `changelog.rst` (master).

---

## Recommended changes

| Finding | Change | Source |
|---|---|---|
| B1 | `docker = "^7.2"`; remove `docker-pycreds` and the direct `requests`; `from_env(use_context=False)`; unmocked missing-socket test | docker-py 7.1.0/7.2.0 release notes; `client.py@7.2.0`; local probe |
| B2 | Load the ACME key with `password=None`; passphrase only in `BestAvailableEncryption`; `""` = none; round-trip test | `serialization.rst@50.0.2`; local probe |
| B2-adjacent (new) | Parse `fullchain` with `load_pem_x509_certificates`; pass intermediates as `cas`; fix the single-cert slice | local probe |
| M1 | `--restart-container` `dest="settings.restartcontainers"`; parser-dest-vs-config test | `cli_args.py:73`, `settings.py:363` |
| M2 | Correct every env name in docker/README.md, docker-compose.yml and docs/operational.md:207; drop quotes and `version:`; add `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL` (env fallback for `-ll`); doc-env-names test; declare all keys in `config_default.yaml` | confuse@v2.2.1 `sources.py`; compose probe |
| M3 | Shape-based store detection (no `acme-v02`); null-safe `Account`/`Registration`/`Certificates`; key case chosen by keys present; fixtures (ZeroSSL URI, null certs, null account, `{}`) | traefik@master/v3.7.14/v2.11.58 `pkg/provider/acme/*`; Go encoding probe |
| M4 | Per-resolver `try`; build the PFX before any rename; report each domain whose artifacts were written; update ADR-0014/0023 contract text | parser read |
| M5 | Init emits resolved `watchforchanges`; svc `run` reads it and always `exec`s; `finish` writes the exit code and runs `/run/s6/basedir/bin/halt` in run-once (choice; alternative `exit 125`); document `restart: "no"`; pygrep against raw `SETTINGS_` env in s6 scripts | s6-overlay README@v3.2.1.0; skarnet s6-supervise; local s6 probe |
| M6 | Defer-not-drop: one daemon `threading.Timer` per container, coalesced, re-checked at fire time, `NotFound`-tolerant, cancelled on shutdown; new ADR for cooldown + defer | `docker.py`, `app.py`, `certificate_exporter.py` |
| F-07 | pygrep hook enforcing `LiquidLogicLabs/*@vN`; fix `zizmor.yml`, AD-5 and ADR-0035 prose | zizmor@v1.30.1 `docs/audits.md` |
| F-09 | `printf 'Authorization: token %s\n' … \| curl -H @-`; pygrep against `-H "Authorization:` | curl `header.md`; github/docs use-secrets |
| F-10 | Correct the comment and walkthrough (one running + one pending; a third cancels the pending one); optional per-ref group; `queue: max` blocked by actionlint 1.7.12 | github/docs concurrency reusable; actionlint `parse.go` |
| F-11 | `enable=${{ !startsWith(needs.build.outputs.image-version, '0.') }}` on the `{{major}}` line; record in AD-8 | LLL README §Major version zero; `meta.ts` |
| F-18 | Credential-free retry pre-pull of the pinned base digest + re-run note; GHCR login rejected under AD-2/AD-13 unless an ADR says otherwise | github/docs (no published limit); Docker Hub usage docs |
| Q8 / m8 | Relock: urllib3 ≥ 2.8.0, requests ≥ 2.33.0 (transitive), python-dotenv ≥ 1.2.2, idna ≥ 3.15, cryptography 50.0.2, watchdog ^6; remove `expandvars`; add `pip-audit` gate | OSV; PyPI |
| Base image | Accept the pending Dependabot bump of `baseimage-alpine:3.24` (tag now `sha256:d2deff7a…`) | `docker buildx imagetools inspect` |
