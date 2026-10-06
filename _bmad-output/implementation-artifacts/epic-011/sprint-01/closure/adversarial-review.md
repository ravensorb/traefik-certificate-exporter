# Sprint E011-S01 closure review — adversarial + clean-release

- **Skill:** `bmad-review`, `lenses=adversarial`, `also_consider = clean-release checklist`
- **Content:** `_bmad-output/implementation-artifacts/epic-011/sprint-01/closure/sprint-01.diff` (2,927 lines; code diff)
- **Governing decisions read:** ADR-0023, ADR-0024, ADR-0025, ADR-0026, ADR-0027
- **Date:** 2026-10-06
- **Report only — nothing was changed.**

Line references are to the current state of the changed files (the diff's post-image).

---

## clean-release scope

### CR-01 — No secrets, debug artifacts, or stray markers introduced *(clean-release, Low — informational)*
**Location:** whole diff
**Problem:** Scanned every added line for `TODO`/`FIXME`/`XXX`/`HACK`, `print(`, `breakpoint()`/`pdb`, and credential-shaped literals. The only hits are documentation prose about secrets, the pre-existing `pkcs12passphrase` comment in `config.sample.yml`, and test fixtures that deliberately plant obviously-fake values (`PLANTED-UNDECLARED`, `tgram://PLANTED-TOKEN/chat`, `SECRETTOKEN`). No real credential, no commented-out code block, no debug print.
**Remedy:** None required. Recorded so the clean-release checklist has an explicit, evidenced answer rather than silence.

### CR-02 — `_atomic_write_text` / `_atomic_write_bytes` are redundant pass-through layers *(clean-release, Low)*
**Location:** `src/traefik_certificate_exporter/libs/certificate_exporter.py:118-124`
**Problem:** `_atomic_write` already dispatches on `isinstance(data, bytes)` (line 59). The two wrappers add a call frame each and no behaviour, type narrowing, or validation — `_atomic_write_text(p, b"x")` happily writes bytes. ADR-0024 permitted "one helper with a mode parameter, **or** two thin functions sharing one core body"; this is both at once.
**Remedy:** Either delete the wrappers and call `_atomic_write` at the 10 sites, or make them the only public entry points by giving them real signatures (`text: str` / `data: bytes`) and having each build the mode itself, so the type in the name is actually enforced.

### CR-03 — Redundant exception tuple `(PermissionError, OSError)` *(clean-release, Low)*
**Location:** `src/traefik_certificate_exporter/libs/certificate_exporter.py:103`
**Problem:** `PermissionError` is a subclass of `OSError`; naming both reads as if two distinct cases are handled when one clause already swallows everything. It also hides that the clause is a blanket `except OSError: pass` over an ownership restore.
**Remedy:** `except OSError:` alone, with the comment stating that *all* restore failures are deliberately non-fatal; or narrow to `(PermissionError, LookupError)` and let a genuinely unexpected `OSError` surface.

### CR-04 — Vendored-file counts drift between CODEOWNERS and the test that enforces them *(clean-release, Low)*
**Location:** `.github/CODEOWNERS:32-48` vs `tests/ci/test_gates.py` (vendored-integrity section header comment)
**Problem:** CODEOWNERS states "142 of the 2,364 files" and "The other 2,222". The comment block introducing the guard in `test_gates.py` says "They are 2,354 tracked files". One of the two numbers is stale, and the prose that the gate *recomputes* (CODEOWNERS) is not the one a reader hits first.
**Remedy:** Delete the count from the test comment (it is unenforced prose) or derive it in the failure message only; keep exactly one place — the CODEOWNERS paragraph the gate asserts against — stating a number.

### CR-05 — `config.sample.yml` claims both logging switches "default to off", but the image ships one on *(clean-release, Low)*
**Location:** `config.sample.yml:17-21` vs `docker/Dockerfile:110-113`
**Problem:** The sample config says "Both switches are opt-in and default to off", while the shipped image sets `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEONLY=true`. A container operator reading the sample concludes a log file exists; it does not.
**Remedy:** Reword to "default to off for a bare `pip` install; the container image ships `CONSOLEONLY=true` (see `docker/Dockerfile`)", so the two audiences are distinguished.

### CR-06 — Extracted `_notify` / `_run` helpers open with a stray blank line and carry no docstring *(clean-release, Low)*
**Location:** `src/traefik_certificate_exporter/libs/notify.py:48-49`, `src/traefik_certificate_exporter/libs/post_export.py:45-46`
**Problem:** Both private bodies begin `def _run(...) -> None:` followed by an empty line, which is a refactor leftover from the split, and neither says what it is or why the public wrapper exists. Every other function in both modules is documented.
**Remedy:** Drop the blank line and add a one-line docstring ("the body of `run_post_export_command`, run with the correlation id already bound").

### CR-07 — `app.py` imports `globalArgs` only to shadow it immediately *(clean-release, Low)*
**Location:** `src/traefik_certificate_exporter/app.py:15-18, 53-54`
**Problem:** The import exists purely so `app.globalArgs` is defined for non-`main()` importers (ADR-0025 Option B), carries `# noqa: F401`, and is unconditionally rebound as the first statement of `main()`. It is correct but reads as dead on inspection, and the `noqa` suppresses the one signal that would reveal a future accidental removal.
**Remedy:** Keep the import, drop the `noqa` by referencing it explicitly (e.g. `globalArgs = parse_args_strict() or globalArgs` is wrong — instead add a module-level `__all__` entry or a `_IMPORT_TIME_DEFAULT_ARGS = globalArgs` alias), and move the eight-line explanation to the import site where a deleter will see it.

---

## adversarial scope

### AD-01 — Shutdown cancellation is unreachable under SIGTERM, which is how the container actually stops *(adversarial, High)*
**Location:** `src/traefik_certificate_exporter/app.py:126-134`; claim in `docs/operational.md` ("### Shutdown")
**Problem:** `event_handler.cancel()` is called only inside `except KeyboardInterrupt`. No `signal.signal(SIGTERM, ...)` handler is installed anywhere in the package (verified by grep over `app.py` and the s6 service scripts). `docker stop`, `kubectl delete`, and systemd all send SIGTERM, whose default disposition terminates the interpreter without raising `KeyboardInterrupt` — so in the shipped deployment the new cancel path, the shutdown flag, the bounded 5s drain wait, and the INFO/WARNING shutdown lines never execute. The runbook added in this sprint nonetheless states "`Ctrl-C`/SIGTERM stops the watcher and cancels any armed-but-not-yet-fired debounce timer". BL-E010-002's shutdown half is closed only for an interactive terminal.
**Remedy:** Install a SIGTERM (and SIGINT) handler in `main()` that raises `KeyboardInterrupt` or sets a stop event the watch loop polls, then let the existing handler run; add a test that sends SIGTERM to a subprocess and asserts the cancellation line. Until that exists, correct the runbook to say SIGTERM is *not* handled.

### AD-02 — `cancel()` TOCTOU: a drain that has just started is reported as "cancelled" and skips the bounded wait *(adversarial, High)*
**Location:** `src/traefik_certificate_exporter/libs/certificate_exporter.py:577-620` (state read) vs `:624-640` (`doTheWork` sets `draining` only after it is scheduled onto the timer thread)
**Problem:** `armed = timer is not None and self.isWaiting and not draining` is evaluated under the lock, but the timer thread sets `self.draining = True` *after* the timer has already fired and the target has begun running. In the window between "timer fires" and "`doTheWork` acquires the lock", `cancel()` reads `draining == False`, takes the `armed` branch, calls `timer.cancel()` — a documented no-op after firing — and logs *"Shutdown requested; cancelled the pending export drain"*, then returns without joining. The drain is in fact running: it proceeds concurrently with `observer.join()` and process exit, is abandoned as a daemon thread with no 5s grace and no WARNING, and the operator's log says the opposite of what happened. The same window re-opens on every `__rearm()`. The class comment claims the three states are read in one critical section; they are not, because one of them is published late.
**Remedy:** Make the timer target publish its own state before any work: wrap `doTheWork` in a thin target that takes the lock and sets `draining = True` as its first statement (or have `cancel()` treat `timer.finished.is_set()` with `isWaiting` still true as "ambiguous → join rather than claim cancelled"). Use `Timer.cancel()`'s observable effect, not an independently-derived boolean, to decide which message to emit. Add a test that fires the timer and calls `cancel()` from the main thread without synchronisation, asserting the message is never "cancelled" when the drain ran.

### AD-03 — Private keys and `.pfx` bundles are deliberately chmod'ed from 0600 to 0644 *(adversarial, Medium)*
**Location:** `src/traefik_certificate_exporter/libs/certificate_exporter.py:75, 106`; asserted by `tests/libs/test_certificate_exporter.py::test_an_atomic_write_matches_what_open_w_would_have_produced`
**Problem:** `tempfile.NamedTemporaryFile` creates at 0600 — the correct mode for `privkey.pem`, `*.key`, and a `.pfx` that is unencrypted whenever `pkcs12passphrase` is unset (the documented default). The helper then explicitly widens it to `0o666 & ~umask` (0644 under the default umask) for *every* artifact, and a test locks that parity in. In the shipped container profile `/certs` is a bind mount shared with other services and often other UIDs, so the sprint had the private key at the right mode and gave it away on purpose. Parity with the old `Path.open("w")` behaviour is a compatibility argument, not a security one, and ADR-0023's own security bullet asks the question in both directions.
**Remedy:** Split the default: key-bearing artifacts (`*.key`, `privkey.pem`, `*.pfx`) default to 0600, chain/cert artifacts keep the umask default; preserve an existing file's mode as today so an operator's own choice still wins. Note the change in the runbook, since a consumer running as a different UID will need a `chmod`/`chown` once.

### AD-04 — The rename is not durable: the file is fsynced, the directory is not *(adversarial, Medium)*
**Location:** `src/traefik_certificate_exporter/libs/certificate_exporter.py:88-107`
**Problem:** `os.fsync(handle.fileno())` makes the *data* durable, and `os.replace` makes the swap atomic with respect to other processes — but the directory entry created by the rename is not fsynced. After a host power loss or a hard VM reset, ext4/XFS can present the directory in its pre-rename state while the temp file is gone, i.e. the certificate silently reverts to the previous version (or vanishes, if there was none). ADR-0023's stated guarantee is "either the old complete file or the new complete file", which survives this case, but the "Open questions" section explicitly flags overlay/bind-mount behaviour as unconfirmed and this is the missing half of the standard pattern.
**Remedy:** After `os.replace`, open the parent directory with `os.open(directory, os.O_DIRECTORY)` and `os.fsync` it (guarded for platforms that reject it), or state in ADR-0023 that crash-consistency stops at process death and host power loss is out of scope.

### AD-05 — Replacing the inode destroys a symlinked output path *(adversarial, Medium)*
**Location:** `src/traefik_certificate_exporter/libs/certificate_exporter.py:71-75, 107`
**Problem:** `target.stat()` follows symlinks, so mode/uid/gid are read from the *link target*, while `os.replace(tmpPath, target)` replaces the *link itself* with a regular file. A deployment that symlinks `/certs/fullchain.pem` into a service's own directory (a common pattern, and the reason `Path.open("w")` wrote *through* the link before) silently stops updating that service at the first renewal after this release, and the mode copied onto the new file came from a file that is no longer involved. The same read-through-follow/write-through-replace mismatch is the classic symlink TOCTOU shape if `outputpath` is ever group-writable.
**Remedy:** Use `os.lstat` for the metadata probe; if the target is a symlink, either resolve it and replace the resolved path (preserving the operator's intent) or log a WARNING once per path explaining that the link is being replaced. Document the behaviour change in the runbook either way.

### AD-06 — Orphaned temp files accumulate in `outputpath`, carrying key material *(adversarial, Medium)*
**Location:** `src/traefik_certificate_exporter/libs/certificate_exporter.py:78-116`
**Problem:** The `except BaseException: os.unlink(...)` cleanup covers exceptions, which is exactly the case the new tests assert. It cannot cover SIGKILL, a container OOM kill, or the `docker stop` SIGKILL that follows the grace period — precisely the scenarios the atomic-write work exists for. Each such kill leaves `.<name>.<random>.tmp` in the certificate directory containing a full private key (at 0644 after line 106, see AD-03), and nothing ever removes it. Over a year of renewals in a crash-looping container that is an unbounded pile of key copies in a bind mount shared with other services.
**Remedy:** Sweep `directory.glob(f".{target.name}.*.tmp")` older than, say, one hour at the start of each export pass (log at DEBUG), or clean the whole output directory's stale temp files once per pass. Add a test that plants a stale temp file and asserts it is gone after a pass.

### AD-07 — `_default_file_mode()` mutates the process-wide umask lazily, after threads and subprocesses exist *(adversarial, Medium)*
**Location:** `src/traefik_certificate_exporter/libs/certificate_exporter.py:34-54`
**Problem:** The probe does `os.umask(0o022)` then restores it. The lock serialises *this* function against itself, but umask is per-process state shared with everything else: the log file created by `RollingFileHanderEx` rotation on another thread, a concurrent drain thread writing a different domain's files, and — worst — a post-export hook `subprocess.run` that forks inside the window and inherits 0o022 instead of the operator's umask. Because the probe is lazy, it fires during the first export, i.e. after the watcher threads and the hook machinery are live, rather than at import when the process is still single-threaded.
**Remedy:** Perform the probe at module import (before any thread is started) and keep the cache, or avoid the umask dance entirely by creating a throwaway file with `tempfile` in the target directory and reading back `0o666 & ~(0o666 & ~os.stat(...).st_mode)` — simplest is to compute it once at import and document that a runtime umask change is not picked up.

### AD-08 — The untracked-file gate fails on any scratch file, including this sprint's own closure artifacts *(adversarial, Medium)*
**Location:** `tests/ci/test_gates.py::test_no_file_escapes_every_gate_by_never_having_been_added`
**Problem:** The guard fails on *every* non-ignored untracked path, with `_bmad-output/` deliberately in scope. In practice a developer mid-task always has untracked files — a review report, a profiling dump, a scratch script — so the gate fires on the common case rather than the defect, and the only way to get a green run is `git add` on whatever it names. That is an incentive to stage files nobody intended to commit (the scratch script holding a real token, the `.env` a developer created to reproduce an issue), which is the opposite of the safety the surrounding gates provide. A check that cries wolf on every run is a check developers learn to bypass with `--no-verify`, taking the secret scanner with it.
**Remedy:** Scope the failure to paths a file-scoped hook would actually have read (the extensions in the hooks' `files:` patterns) and/or honour an explicit `.gitignore`-style allowlist for working scratch; emit the rest as a warning. Keep the hard failure for new `src/`, `tests/`, `.github/` files, which is where all three recurrences happened.

### AD-09 — The vendored-integrity gates hash ~4,700 files on every commit and hard-code a count in prose *(adversarial, Medium)*
**Location:** `.pre-commit-config.yaml:38-50` (`always_run: true`, `entry: poetry run pytest -q tests/ci`); `tests/ci/test_gates.py` vendored-integrity section
**Problem:** Two of the new tests SHA-256 every file under `.agents/` and `.claude/` on every single commit, and a third asserts that three specific integers appear in CODEOWNERS prose. A routine upgrade of the vendored payload therefore fails three tests at once and requires a human to recompute and hand-edit numbers in a comment before any commit can land — the exact ritual global rule 3 says will not hold. `_vendored_trees()` additionally parses the `exclude:` regex with `re.fullmatch(r"\^\((?P<alternatives>.+)\)/")` and `.replace("\\", "")`, so a legitimate edit to that pattern (adding a third tree, or any character class) turns an integrity gate into an `assert alternation` failure with no diagnostic about what actually changed.
**Remedy:** Mark these two as a slow/`pre-push` stage or cache digests keyed by `git ls-files -s` output; generate the CODEOWNERS caveat (or make the assertion range-based/`>=`-shaped rather than exact-string) so a payload upgrade is a one-command regeneration; replace the regex-reverse-engineering with an explicit tuple of tree names validated *against* the exclude pattern.

### AD-10 — Strict CLI parsing is an undocumented breaking change for existing deployments *(adversarial, Medium)*
**Location:** `src/traefik_certificate_exporter/libs/cli_args.py:156-167`, `src/traefik_certificate_exporter/app.py:53-54`
**Problem:** Any invocation carrying an argument this version does not know now exits 2 instead of ignoring it. The shipped s6 service only passes `-c /config/config.yaml`, so the image is safe — but a `docker-compose` `command:` override, a Kubernetes `args:` list, or a wrapper script written against an older/newer flag spelling now crash-loops under s6's restart policy with the usage text as its only output, and the process dies before `setup_logging()` so nothing reaches the log file. Neither `README.md` nor `docs/operational.md` mentions the change; the new user-facing docs in this sprint are entirely about correlation IDs.
**Remedy:** Add a line to the README CLI section and to the runbook's troubleshooting area ("exit code 2 at start-up means an unrecognised flag — check your `command:` override"), and call it out in the release notes/CHANGELOG for this version.

### AD-11 — `logging.yaml` now hard-requires a `correlation_id` attribute supplied only by a global factory *(adversarial, Low)*
**Location:** `src/traefik_certificate_exporter/logging.yaml:7-34`, `src/traefik_certificate_exporter/libs/logging_utils.py:61-91, 222`
**Problem:** Every formatter string now references `%(correlation_id)s`. The attribute exists only because `install_correlation_id_record_factory()` ran at import of `logging_utils`. The runbook documents `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CFGFILE`, so an operator is invited to copy this YAML into their own config — and any process that loads it without importing this module (an embedding host, a sidecar that reuses the file, a reload after another library calls `logging.setLogRecordFactory`) raises a `ValueError` on *every* record, in the library's error path. The defence the docstring describes ("a missing correlation id must never break the pass") depends on an import side effect holding globally.
**Remedy:** Pass `defaults={"correlation_id": CORRELATION_ID_UNSET}` to the formatters (supported by `logging.Formatter` since 3.10, which is this project's floor) so the config is self-sufficient, and keep the record factory as the mechanism that fills in the real value.

### AD-12 — Record-factory installation is idempotent only against itself at the outermost layer *(adversarial, Low)*
**Location:** `src/traefik_certificate_exporter/libs/logging_utils.py:84-90`
**Problem:** `install_...` returns early only if the *current* factory is a `_CorrelationIdRecordFactory`. If any other library (coloredlogs plugins, an APM agent, pytest plugins) wraps the factory after ours, the next `setup_logging()` call wraps again — and `setup_logging()` is callable more than once. Each layer adds a `hasattr` check and a frame to every log record in the process; nothing ever unwinds them.
**Remedy:** Walk the `inner` chain when checking (`while hasattr(current, "inner")`), or record installation in a module-level `_installed` flag.

### AD-13 — `doTheWork(correlationId=None, *args, **kwargs)` will silently adopt any positional argument as the correlation id *(adversarial, Low)*
**Location:** `src/traefik_certificate_exporter/libs/certificate_exporter.py:624-636`
**Problem:** The signature was changed from `(*args, **kwargs)` to a leading positional parameter. Any existing or future call that passes a watchdog event positionally — the shape the old `*args` tolerance existed for — now binds that object as the correlation id, and `set_correlation_id` accepts it unvalidated. Its `repr` (which contains `src_path`) is then interpolated into the `correlation_id` field of every log line and exported into the post-export hook's environment, which is the one field the sprint documents as "carries nothing derived from a domain, path, or secret".
**Remedy:** Make it keyword-only (`def doTheWork(self, *args, correlationId: str | None = None, **kwargs)`) and have `set_correlation_id` coerce non-`str` input to `CORRELATION_ID_UNSET` rather than trusting the caller.

### AD-14 — Watch events are now logged while holding the handler lock *(adversarial, Low)*
**Location:** `src/traefik_certificate_exporter/libs/certificate_exporter.py:540-558, 560-566`
**Problem:** The `"Certificates changed found in file"` line moved from *before* `with self.lock:` to *inside* it, so every event dispatched by watchdog now serialises behind a log emit — which, with the rotating file handler, can mean a `RotatingFileHandler` rollover (rename + reopen) under the lock. A drain finishing at the same moment blocks on `self.lock` for the duration of a rollover, and watchdog's dispatcher thread blocks behind it, where a long enough stall drops inotify events from the kernel queue.
**Remedy:** Capture the id under the lock and emit the log line after releasing it; the ordering guarantee the move was made for (the line carries the window's id) is preserved by passing the captured value.

### AD-15 — The post-export hook's environment now carries the correlation id to every descendant *(adversarial, Low)*
**Location:** `src/traefik_certificate_exporter/libs/post_export.py:64`
**Problem:** `TRAEFIK_CERTIFICATE_EXPORTER_CORRELATION_ID` is injected into the hook's `env` and is therefore inherited by everything the hook spawns, including anything it pipes to a third party. A UUID4 is not sensitive, so this is low impact — but the value may be the literal `"-"` when the hook runs outside a pass, and the README documents it as "the export pass's correlation id" without saying so. A hook that keys a datastore on it will group every unattributed run under one `-` bucket.
**Remedy:** State the `-` sentinel in the README bullet (the runbook already does), or omit the variable entirely when `get_correlation_id() == CORRELATION_ID_UNSET` so a hook can distinguish "no id" from "id is a dash".

### AD-16 — The inode swap preserves mode/uid/gid but silently drops ACLs, xattrs, and SELinux labels *(adversarial, Low)*
**Location:** `src/traefik_certificate_exporter/libs/certificate_exporter.py:94-106`
**Problem:** The code goes to real trouble to restore ownership and mode because the container profile depends on them — but a POSIX ACL (`setfacl -m u:traefik:r`), a security xattr, or an SELinux file context applied by an operator to `/certs/privkey.pem` is attached to the old inode and is gone after the first renewal. On an SELinux-enforcing host the new file inherits the directory's default type, which may not be the type the consuming service is allowed to read. This is the same class of failure the ownership comment describes, one layer down, and it is not mentioned in ADR-0023/0024 or the runbook.
**Remedy:** Either copy them (`shutil.copystat` plus an explicit ACL copy where available), or state the limitation in the runbook's new write-safety paragraph so an operator relying on ACLs knows to move the hardening to the directory rather than the file.

---

**Findings:** 23 total — 7 `clean-release`, 16 `adversarial`.

Critical: 0, High: 2, Medium: 8, Low: 13
