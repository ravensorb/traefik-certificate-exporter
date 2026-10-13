# E015 "0.3.1": epic architecture gate, second review (architect)

- **Reviewer:** Winston (`bmad-agent-architect` persona). No menu workflow was run.
- **Date:** 2026-10-12.
- **Input under review:** `arch/arch-gate-review.md` (AG-1 … AG-6).
- **Binding rules, treated as constraints:**
  - the maintainer's "do NOT break lsio and the way they do things";
  - MD-19 … MD-23, except where AG-1 shows a stated rationale is false;
  - CI AD-4 and AD-5;
  - the global rules in `~/.claude/CLAUDE.md`.
- **Write scope:** this file only.

## Verdict table

| Item | First reviewer | Verdict | My severity | One-line reason |
|---|---|---|---|---|
| AG-1 | MAJOR | **Agree** (reproduced at the code level; fix refined) | **MAJOR** (blocks S01-001 start) | An absolute or `..` `filespec` from a `PUID`-writable file escapes `datapath`. Root then exports a forged store over the real `/certs` keys and restarts labelled containers. "Read only" is false as a rationale. |
| AG-2 | MAJOR | **Agree in part:** the evaluation is missing. **Disagree** with the preferred fix: ruff `S602`–`S606` is weaker than stated. | **MINOR** | Probed on ruff 0.16.5: `S603` exempts literal-argument `subprocess` calls, and the `S6xx` family misses `posix_spawn*`, `fork*`/`forkpty`, `pty` and `asyncio`. The ruff mechanism that fits is `TID251` banned-api. |
| AG-3 | MINOR | **Agree** | MINOR | `functools.lru_cache` hashes every argument, so a `dict` `record` raises `TypeError: unhashable type`. D4 (`E015-S01-002.md:51`) and the contract row (`:161`) disagree. |
| AG-4 | MINOR | **Agree** | MINOR | `< 2.0 s` is asserted in AC 11/12 (`E015-S01-002.md:100,103,281-282`), and the story calls it secondary (`:275`). The call-count spies are the real proof. |
| AG-5 | MINOR | **Agree** | MINOR | Three `docker/login-action` steps run first, then `git-action-docker-metadata@v6` and `git-action-docker-test@v2`, both at mutable major tags (verified in `.github/workflows/release.yaml:432-505`). The co-residence is not recorded, and token expiry is not tracked. |
| AG-6 | MINOR | **Agree**, with one wording addition | MINOR | The `any-source` rationales are prose, and AG-1 is the proof that one was wrong. "No privilege effect" should say "availability only" (see below). |

No item is raised to BLOCKER. Two new MINOR findings follow (AR-1, AR-2).

## AG-1: verification

### Is the attack real?

Yes. I checked each step against the code.

1. **The glob escapes `datapath`.** `exportCertificates` globs `os.path.join(str(dataPath), fileSpec)` (`src/traefik_certificate_exporter/libs/certificate_exporter.py:1176-1178`), and `filespec` is a bare `.as_str()` (`libs/settings.py:401`). `os.path.join` discards `dataPath` when `fileSpec` is absolute. Probe (stdlib `glob`, temporary directory):
   - `glob(join(d+'/data', d+'/config/forged.json'))` returned `[…/config/forged.json]`;
   - `'../config/*.json'` returned `[…/data/../config/forged.json]`;
   - a glob-magic `[.][.]/…` returned `[]`, because glob never lists `.` or `..`. A lexical check on the pattern is therefore sufficient.
2. **The image `ENV` does not cover `filespec`.** It sets `…_SETTINGS_DATAPATH=/data` and `…_OUTPUTPATH=/certs` only (`docker/Dockerfile:123-130`). A `filespec` in `config.yaml` therefore wins.
3. **Root mode can be forced from the same file.** Row 2 of `privilege-decision.sh:86-93` keeps root for `restartcontainers: true`, and MD-21 keeps that key file-settable.
4. **Root parses and writes the forged store.**
   - `exportCertificatesForFile` has no provenance check on the store file (`certificate_exporter.py:1077-1100`).
   - `__exportDomain` builds the artifacts from the store's base64 key and chain (`:970-985`).
   - The only containment check is on the *output* directory (`:999`).
   - It writes `privkey.pem` and `cert.pfx` `0600` root over the genuine files whenever bytes differ (`:1021-1063`).
   - A self-signed leaf for the real domain, with a matching key, passes `serialize_key_and_certificates`.
5. **Changed domains trigger the restart path,** which restarts the labelled containers.

### Impact, calibrated

- **Integrity and availability of root-owned output.** Real keys and certificates are replaced with attacker-chosen ones, and every start then restarts the labelled containers.
- **Not confidentiality.** Keys stay `0600` root.
- **Not code execution.** Domain names pass `_PATH_COMPONENT_PATTERN` (`:440-445`: `[A-Za-z0-9_-]` labels), so the names placed in `TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS` for an environment hook cannot carry shell metacharacters. The first review's remark about the hook is true only as "receives spurious names", not as injection.
- **No MITM against verifying clients,** because the forged leaf is not CA-issued.

MAJOR is the right severity, not BLOCKER. It is still a privilege-boundary crossing (`PUID` decides what root writes into a tree `PUID` cannot write), and it contradicts the story's own claim at `E015-S01-001.md:189`.

The code already treats an `abc`-writable store as a hazard: `privilege-decision.sh:117-130` emits a "writable store" note. The `filespec` escape turns `/config`, which is always `abc`-owned under the LinuxServer convention, into exactly such a store.

### Is the recommended fix right and minimal, and does it respect LinuxServer conventions?

**Yes for both parts, with three refinements.**

#### (a) `filespec` as a bare file-name glob, validated in every mode

This is the right contract, not only a security patch:
- `README.md:7` and `docker/README.md:5` document it as "defaults to `*.json` however can be set to a specific file name".
- The watcher uses it as a name pattern on a non-recursive observer of `datapath` (`certificate_exporter.py:1341-1346`, `app.py:254`), so a separator-bearing value never worked in watch mode anyway.
- No test in `tests/` uses a path-bearing `filespec` (grep).
- It touches nothing LinuxServer owns: no Dockerfile, s6, `/config` ownership or `lsiown` change.

#### (b) `datapath` as `environment-only-when-root`

This is a table entry, plus the AC 2 mechanism that already exists.
- **Image:** zero change, because `DATAPATH` comes from `ENV`.
- **PyPI root runs:** the same accepted cost as `outputpath`.
- **Why it is needed:** without it, a PyPI root run with a writable config file has the same reach via `datapath`.
- **Class rule:** add "or which file root trusts as the source of what it writes".

#### Refinement 1: put the check at the Settings edge, not a containment check in `exportCertificates`

The init resolver re-derives the store set with its own copy of the expression, `glob.glob(os.path.join(settings.dataPath, settings.fileSpec))` (`docker/root/etc/s6-overlay/s6-rc.d/init-traefik-certificate-exporter-config/run:85-88`). The watcher also consumes `fileSpec` directly. A containment filter on the glob results in `exportCertificates`:
- would leave the init resolver's view, and its privilege inputs (rows 4-5), computed from the escaped path;
- would contradict S01-001's "no change to `certificate_exporter.py`" contract (`E015-S01-001.md:146`).

Validating once in `SettingsManager.loadFromFile` covers all three consumers. One check, one place: global rule 4.

#### Refinement 2: drop `realpath` containment

Resolved-path (symlink) containment would reject legitimate symlinked stores. A symlink inside `datapath` requires write access to `datapath`, and that is already the full attack (AR-1). Lexical validation of the pattern is sufficient; the glob probe above shows glob magic cannot synthesise `..`.

The validator rejects:
- empty values;
- `os.sep` and `os.altsep` (when set);
- `/` explicitly;
- the values `.` and `..`;
- absolute values (`os.path.isabs`).

#### Refinement 3: falling back and telling users

- **Fallback:** on rejection, log one ERROR naming `settings.filespec` and its source, in the line shape of AC 2 (the value is not secret, but the shape stays uniform), then fall back to the packaged default `*.json`. This is simpler than walking sources, and contained by construction.
- **Release notes:** this is a user-visible change in every mode, because an absolute `--file-spec` worked at start before. S01-001's release-note list and `docs/upgrading.md` need a bullet, and the `-fs GLOB` help text in `cli_args.py` and `README.md:37` must say "file-name glob inside the data path".

#### Is there a smaller alternative?

Classing `filespec` itself `environment-only-when-root`, as a table-only change, is smaller in code. I reject it:
- It leaves the escape open for PyPI root runs with a CLI-less config.
- It silently reverts root-mode operators' custom `filespec` to `*.json`.
- It does not fix the contract for the init resolver in dropped mode.

(a)+(b) is the minimal correct fix.

## AG-2: verification of the ruff claim

### What I tested

- **Tool:** ruff **0.16.5**, the pre-commit `rev` `1f1e8bf…` (frozen v0.16.5, `.pre-commit-config.yaml:198-213`), binary in the pre-commit cache.
- **Configuration:** `--isolated --select S602,S603,S604,S605,S606,S607`.
- **Probe:** throwaway files outside the repository.

### Results

| Spawn form | `S602`–`S606` (0.16.5) | `TID251` banned-api | AC 5 `ast` scan |
|---|---|---|---|
| `subprocess.run(argv)`, `sp.check_output(argv)`, `from subprocess import run as r; r(argv)`, `Popen(argv)` with **non-literal** args | caught (`S603`) | caught (import of banned module) | caught |
| `subprocess.run(["/bin/sh","-c","id"])`, **literal** args | **not caught**: `S603` exempts trusted literal input, and `S607` fires only on partial paths | caught | caught |
| `subprocess.run(cmd, shell=True)` | caught (`S602`) | caught | caught |
| `subprocess.getoutput`/`getstatusoutput`, `os.system`, `os.popen`, `from os import system as s; s()` | caught (`S605`) | caught | caught |
| `os.exec*`, `os.spawn*`, `os.startfile` | caught (`S606`) | caught (each name listed) | caught |
| `os.posix_spawn`, `os.posix_spawnp` | **not caught** | caught | caught |
| `os.fork`, `os.forkpty` | **not caught** | caught | caught |
| `pty.spawn` | **not caught** | caught (module ban) | caught |
| `asyncio.create_subprocess_exec`/`_shell` | **not caught** | caught | caught |
| `f = os.system; f(...)` | **not caught** | caught | depends on the implementation (an attribute *reference*, not a call) |
| `getattr(os,"system")`, `importlib.import_module("subprocess")`, `__import__` | not caught | not caught | not caught |

### What this means

- Current `src/` under `S6xx` produces exactly one finding: `libs/post_export.py:88:18 S603`. So per-file-ignores would work.
- But `S6xx` misses five spawn families that the story's guard covers, plus literal-argument `subprocess` calls. The first review's stated coverage limit listed only `pty`, `fork` and `asyncio`.
- Replacing AC 5 with `S6xx` would therefore weaken "the hook is the only spawn site".

### Severity

**MINOR, not MAJOR.** The AC 5 helper is a single test inside pytest. That is the "write that one helper inside the framework" case the global rule allows, and AD-4 binds policy over workflows and supply chain, not product-source tests. The real defect is the unrecorded evaluation, which global rule 1 requires.

### Recommended resolution

The maintainer picks one. Either is acceptable.

1. **Preferred (maintained tool, no custom scanner):** add `[tool.ruff.lint]` `extend-select = ["TID251"]` with `flake8-tidy-imports.banned-api` entries for:
   - the modules `subprocess` and `pty`;
   - `os.system`, `os.popen`, every `os.exec*`/`os.spawn*` name, `os.posix_spawn`, `os.posix_spawnp`, `os.fork` and `os.forkpty`;
   - `asyncio.create_subprocess_exec` and `asyncio.create_subprocess_shell`.

   Add `per-file-ignores` for `src/traefik_certificate_exporter/libs/post_export.py` and `tests/**`, because `tests/test_s6_*.py` and `tests/test_app.py` spawn processes.

   Banned-api has no wildcard, so the `os` names are a hand-kept list (global rule 4). Close that with one product-surface pytest. It derives the spawn-capable `os` names from `dir(os)` by prefix (`exec`, `spawn`, `posix_spawn`, `fork`, plus `system` and `popen`) and asserts that each appears in the banned-api table read from `pyproject.toml` with `tomllib`. Prove the scope with a Verification row that plants `os.posix_spawn` and a literal `subprocess.run([...])` in a scratch copy, and shows `ruff check` failing.

2. **Or keep the AC 5 `ast` test unchanged,** and add to S01-001's Existing-library check and the new ADR:
   - ruff 0.16.5 `S602`–`S606` were evaluated, and rejected for the six gaps above (cite this table);
   - `TID251` was evaluated, and rejected (state why);
   - cost: about 30 lines of test helper, owned by the S01-001 owner;
   - revisit: ruff gains a wildcard banned-api, or the scan's own planted test is ever skipped.

Either way, write the dynamic-import limit (`getattr`/`importlib`/`__import__`) where the rule lives (global rule 3).

## AG-3 … AG-6

- **AG-3:** agree. Adopt the split into `_passphrase_matches` (validating, uncached) and `@lru_cache _scrypt_verifies(passphrase, salt, n, r, p, digest)`. Note that `passphrase: bytes` in the cache key keeps the passphrase alive for the life of the process; that is already accepted at D4 ("already lives in process memory").
- **AG-4:** agree. Prefer the relative bound (the unchanged pass takes less than ¼ of the first validating pass, measured in the same process), so the performance claim stays mechanically checked, as global rule 3 requires.
- **AG-5:** agree as written. The logout-before-test change belongs in the backlog, not in S02-002 ("no workflow change").
- **AG-6:** agree. Also correct the wording of the last `any-source` row (spine `ARCHITECTURE-SPINE.md:170`; story `:193`).
  - `pkcs12passphrase` from a file sets the passphrase on root's `.pfx`.
  - `dryrun` and `domains.exclude` from a file stop exports.

  These are availability effects that `PUID` can already cause by breaking `config.yaml`, not privilege effects. Say "availability only, no read/write/execute reach" rather than "no privilege effect", so the next reviewer checks the right property.

## New findings

### AR-1 — MINOR — E015-S01-001 (residual of AG-1; product spine AD-2; `docs/operational.md:373-376`)

- **Finding:** After the AG-1 fix, the same forged-store reach remains whenever the store directory itself is writable by `PUID` in root mode:
  1. Row 2 (`restartcontainers: true`, file-settable per MD-21) returns at `privilege-decision.sh:86-93`.
  2. That is **before** the writable-store note is computed (`:117-130`), so a root-mode start never says the store is `abc`-writable.
  3. `docs/operational.md:373` states the `/data:ro` requirement only for *unprivileged* mode.

  A deployment whose Traefik directory is owned by `PUID` (a common compose layout when Traefik itself runs as `PUID`) therefore lets `abc` forge `/data/acme.json`. A file-forced root exporter then writes it over `/certs`, and restarts containers, with no log line.
- **Why MINOR:** it depends on the deployment. A stock Traefik writes `acme.json` `0600 root`, so the default is safe. It is also LinuxServer-neutral to fix in documentation.
- **Recommended resolution:**
  - In S01-001's Security considerations, the new ADR's residual list and `docs/operational.md` "Trust boundary", state: "in either mode the ACME store must not be writable by `PUID`; mount `/data:ro`".
  - File a Low backlog item to emit the existing writable-store note in row 2 as well. That is an s6 script change, which S01-001's non-goals exclude, and the "exactly one WARNING" invariant of `tests/test_s6_privilege_drop.py` must be considered (the note is a separate line).

### AR-2 — MINOR — E015-S01-001 (scope of the AG-1 change)

- **Finding:** As written, the AG-1 resolution changes S01-001's contracts in four places the first review does not list:
  - "No change to … `certificate_exporter.py`" stays true only if the check lives in `settings.py`, which this review recommends.
  - `filespec` validation is a user-visible change in **every** mode, not only root, so it needs a release-note bullet and an `upgrading.md` line.
  - The `--file-spec` help text and `README.md:37` must state the contract.
  - AC 6's classification test must class `filespec` explicitly. It stays `any-source` once validated, and the one-line comment should say "validated as a file-name glob at load, AG-1", not "read only".
- **Recommended resolution:** fold these into the S01-001 edit that closes AG-1. Add these to Verification:
  - unit tests that reject `/abs.json`, `../x.json`, `sub/x.json`, `..` and `x\\y.json` (on Windows semantics where applicable), each with one ERROR and the effective value `*.json`;
  - a root plus file `datapath` test withheld with the AC 2 ERROR;
  - AC 7 (v), forged-store replay on the image. uid 1000 writes `/config/forged.json` and a `config.yaml` with `filespec: /config/forged.json` and `restartcontainers: true`. Assert:
    - the genuine `/certs/<domain>/privkey.pem` keeps its `(inode, mtime_ns, bytes)`;
    - the log carries the `filespec` ERROR;
    - no `Processing file: /config/…` line.

## Recommended resolution for blocking items

Only **AG-1** blocks; it gates the start of E015-S01-001.

1. **Maintainer re-decides MD-21** for two keys:
   - `datapath` → `environment-only-when-root`;
   - `filespec` stays `any-source`, but becomes a validated file-name glob in every mode.

   Replace the rationale "read only" with the amended class rule: "a setting whose value root executes, writes to, **or trusts as the source of what it writes** is environment-only when root, unless it is validated at load to stay inside an environment-only path".
2. **Same change:** update PRD FR-18/FR-10 (key list), product spine AD-2 (trust-class table, `:164`, `:170`) and `maintainer-decisions.md` MD-21.
3. **Amend E015-S01-001:**
   - AC 1 table;
   - new AC for `filespec` validation in `SettingsManager.loadFromFile`;
   - AC 7 (v);
   - release notes;
   - Security considerations: "content integrity", plus the AR-1 residual;
   - ADR content.

   No Dockerfile, s6 or `/config` ownership change: the LinuxServer constraint holds.

AG-2 is downgraded to MINOR here. If the maintainer keeps it MAJOR, the resolution is either option above, recorded before S01-001 starts.

## Sections read

- `epic-015/arch/arch-gate-review.md` (all).
- `epic-015/sprint-01/stories/E015-S01-001.md` (all).
- `E015-S01-002.md`, grep for D4, AC 11/12/16a and the contract row (`:33-57, 100-117, 161, 275-282`).
- `maintainer-decisions.md:95-115` (MD-20 … MD-23).
- PRD `prd.md` FR-10/FR-12 (`:77, :79`).
- Product spine `ARCHITECTURE-SPINE.md:160-172`.
- CI spine AD-4/AD-5 (`:122-134`).
- Source:
  - `src/traefik_certificate_exporter/libs/certificate_exporter.py:440-475, 691-775, 950-1185, 1300-1400`;
  - `libs/settings.py`, grep for `fileSpec`/`dataPath`;
  - `config_default.yaml`, grep;
  - `docker/Dockerfile:110-135`;
  - `docker/root/usr/local/lib/traefik-certificate-exporter/privilege-decision.sh:54-170`;
  - `init-traefik-certificate-exporter-config/run:75-95`;
  - `.pre-commit-config.yaml:198-213`;
  - `.github/workflows/release.yaml:425-510`, grep for logins and `uses:`;
  - `README.md`, `docker/README.md` and `docs/operational.md`, grep for `filespec` and `:ro`;
  - `tests/`, grep for `filespec`.
- Probes:
  - stdlib `glob` escape (absolute, `..`, `[.][.]`);
  - ruff 0.16.5 `S602`–`S607` and `TID251` over throwaway spawn-form files;
  - ruff `S6xx` over `src/` (one finding, `post_export.py:88`).
