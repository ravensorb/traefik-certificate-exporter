# E015 execution notes — environment facts every story agent needs

Read this before running anything. These are verified behaviours of this workstation, the
repository and the production host as of 2026-10-12; they are not design decisions (those live
in the PRD, the two spines, the ADRs and `maintainer-decisions.md`). If something here turns
out wrong, record it in your story's notes file and keep going.

## Authorities

- Requirements: `_bmad-output/planning-artifacts/prds/prd-traefik-certificate-exporter-2026-08-30/prd.md`
- Product architecture: `_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md`
- CI/CD architecture: `_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md`
- Decisions: `docs/adr/` (0001–0048 at planning time)
- Verified library/platform facts for this epic: `_bmad-output/planning-artifacts/research/research-2026-10-12-release-0.3.1.md` (§1–§8, one per story); the 0.3.0 brief `research-2026-10-10-release-0.3.0.md` still holds for what it covers.
- Maintainer decision record (accepted 2026-10-12): `_bmad-output/implementation-artifacts/epic-015/maintainer-decisions.md` (MD-06 … MD-23 accepted; MD-01 … MD-05 withdrawn). The PRD and both spines (Target 0.3.1) already carry them; they are the baseline to validate against.

## Toolchain on this host (re-verified 2026-10-12)

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11.11 (pyenv) | project supports 3.10–3.14 |
| Poetry | 2.4.2 | see "Poetry plugin" below |
| uv | 0.11.6 | runs `_bmad/scripts/pm-status.py` only; the project is Poetry (ADR-0001) |
| act | 0.2.89 | see "act" below |
| Docker Engine | 29.9.0, API 1.56 | socket `/var/run/docker.sock`; integration tests can use it |
| docker buildx | v0.38.0 | `imagetools inspect/create` used by S02-002/-004 |
| just | 1.58.0 | recipes: install, check, build, image, act, release |
| infisical CLI | 0.43.140 | secrets for live-host access (below); never print values |
| git | full clone | `git rev-parse --is-shallow-repository` = `false` (S01-004's history derivation needs this) |

Installed library versions the stories rely on (from `poetry.lock` / `.venv`): cryptography 50.0.2, watchdog 6.0.0 (`InotifyObserver` on Linux), pre-commit 3.8.0.

## Poetry plugin (poetry-dynamic-versioning)

- The global Poetry's plugin resolution can fail because of an unrelated user-environment
  conflict (`docker-apps-cfgmgr` pins `ruamel.yaml ^0.18.14`). If `poetry install` fails while
  resolving plugins, run `uvx --from poetry==2.4.2 poetry install` once; after that the global
  `poetry` works.
- Strict versioning needs tags: any Poetry command other than `run`/`shell` fails when no
  `vX.Y.Z` tag is reachable. In throwaway clones use full history (`git clone` without `--depth`).

## Verification commands

- The gate: `just check` (all pre-commit hooks + pytest). It must pass at the end of every story.
- Targeted tests: `poetry run pytest -q <path>::<test>`; record the node ids you ran.
- Integration tests (real Docker / built image): marker `integration`, opt-in with
  `TCE_DOCKER_INTEGRATION=1`; image under test from `TCE_IMAGE`
  (default `traefik-certificate-exporter:local`, built by `just image`).
  Example: `just image && TCE_DOCKER_INTEGRATION=1 poetry run pytest -q -m integration -rs <file>`.
  A skipped integration test is not a pass (ADR-0041): run with `-rs` and record "none skipped".
- Pre-commit on specific files: `poetry run pre-commit run --files <files>`.

## act (local workflow runs)

- `~/.actrc` prompts for Infisical-backed secrets, and act 0.2.89 also reads `.secrets` and
  `.vars` from the working directory by default (research §7). Bypass all of them with a
  temporary HOME, run from a throwaway clone with no `.secrets`/`.vars`, and pass the runner
  image explicitly:
  `HOME=$(mktemp -d) act <event> -W .github/workflows/<file> -P ubuntu-latest=ghcr.io/catthehacker/ubuntu:act-latest --pull=false --defaultbranch main --artifact-server-path "$(mktemp -d)"`
- `just act` still reads `~/.actrc` until E015-S02-002 hardens it; prefer the explicit form for
  unattended runs.
- Run act in a **throwaway clone** under `/tmp` when the test needs tags, branches or commits;
  never create tags/branches in the real repository. A release-event payload must carry the
  default branch, or `validate-tag` refuses (correctly):
  `{"ref":"refs/tags/v9.9.9","repository":{"default_branch":"main"}}`.
- Artifact actions are pinned to upload v5.0.0 / download v6.0.0 because act 0.2.89 rejects
  newer ones; do not change them.
- `docker/build-push-action` steps set `DOCKER_BUILD_RECORD_UPLOAD: "false"` for the same reason.
- No secrets ⇒ every destination is skipped (silent when unconfigured); that is the expected
  no-secret result. **Never pass real publishing tokens to act** (MD-14): act runs are for
  dummy-secret and local-registry tests only.

## Network

- `pip-audit`, PyPI/OSV lookups and image pulls need network access. ghcr.io may rate-limit
  anonymous pulls (HTTP 429); retry, do not log in.
- Registry digest lookups: `docker buildx imagetools inspect --format '{{json .Manifest.Digest}}' <ref>`
  prints **no trailing newline**, and a failed lookup prints **nothing**. Piping several lookups
  into `sort -u`/`grep -c .` therefore collapses several digests into one line, and an empty
  line from a failed lookup is not counted, so the check cannot fail (E014-S02-007 row 15;
  validation V-01). Use the `dig`/`onedigest` functions of E015-S02-002/-004 (CI spine AD-12):
  one line per lookup, `MISSING <ref>` for a failed or empty lookup, and a pass only when the
  ref count equals the expected count, nothing is `MISSING` and one digest remains. Prove them
  once with a real and a nonexistent image before relying on them.

## Live host: rwusdckrls6 (production "docker 6")

Production there runs Traefik, `cert-distributor` and the exporter container
`traefik-certificate-exporter` (`ghcr.io/ravensorb/traefik-certificate-exporter:latest`, 0.2.0
at planning time, root, Watchtower active, env includes `TRAEFIK_RESOLVERID_INOUTPUTPATHNAME=1`,
output `/mnt/certificates`). Source: `epic-014/sprint-02/closure/live-host-test-rwusdckrls6-2026-10-12.md`.

### Rule: test containers never touch production

- Never write to, restart, stop, recreate or re-label the production `traefik`,
  `traefik-certificate-exporter` or `cert-distributor` containers, Traefik's ACME files, or
  `/mnt/certificates`. The only exception is E015-S02-004's production upgrade, and only as the
  maintainer-approved HITL step that story describes.
- Test containers are named `tce-test-031-*`, run with `--network none` (unless a test needs the
  Docker socket), `--restart no`, and the Watchtower opt-out label
  (`com.centurylinklabs.watchtower.enable=false`).
- Before any restart test, confirm that no running container carries the label
  `com.github.ravensorb.traefik-certificate-exporter.domain-restart`
  (`sudo docker ps --filter label=com.github.ravensorb.traefik-certificate-exporter.domain-restart -q | wc -l` → `0`;
  it was 0 of 103 on 2026-10-12). Restart tests use a throwaway `whoami` container labelled for
  one domain, never a production service.
- Input data is a `sudo cp -p` copy of the ACME stores into a scratch directory; the originals
  are only read.

### Access (method verified by the E014 live test, 2026-10-12)

- Account `svc.claude`. Kerberos/GSSAPI login is refused for this account: authenticate by
  password. The password is in Infisical (project `45365f20-36e8-4d4d-87f3-1554c5ae0615`, env
  `prod`) as `CLAUDE_AD_PASSWORD`, with the user name in `CLAUDE_AD_USER` (names verified
  2026-10-12; values never printed, logged or written to a file).
- Feed the password through `SSH_ASKPASS` and keep one ControlMaster connection open, so the
  password is used once per session:

  ```sh
  A=$(mktemp -d) && chmod 700 "$A"
  printf '#!/bin/sh\nprintf "%%s\\n" "$CLAUDE_AD_PASSWORD"\n' > "$A/askpass" && chmod 700 "$A/askpass"
  infisical run --projectId 45365f20-36e8-4d4d-87f3-1554c5ae0615 --env prod --silent -- \
    env SSH_ASKPASS="$A/askpass" SSH_ASKPASS_REQUIRE=force DISPLAY=none \
    ssh -fN -o ControlMaster=yes -o ControlPath="$A/cm" -o ControlPersist=30m \
        -o GSSAPIAuthentication=no -o PreferredAuthentications=password,keyboard-interactive \
        svc.claude@rwusdckrls6
  ssh -o ControlPath="$A/cm" svc.claude@rwusdckrls6 'sudo -n docker ps --format "{{.Names}}" | wc -l'
  ```

  The exact command line above is reconstructed from the recorded method, not copied from the
  E014 session; record the form that worked in your notes on first use.
- `sudo` is passwordless for Docker (`sudo -n` must succeed; if it prompts, stop and record).
- Close the session at the end: `ssh -o ControlPath="$A/cm" -O exit svc.claude@rwusdckrls6; rm -rf "$A"`,
  and destroy any local Kerberos ticket you obtained (`kdestroy`).

### Live-host test procedure (parallel test against production data)

Modelled on the E014 run (`live-host-test-rwusdckrls6-2026-10-12.md`). Needs maintainer approval
per run, recorded in the story's notes.

1. **Pre-checks:** production containers up; label pre-check above = 0; note the production
   image digest (`sudo docker inspect traefik-certificate-exporter --format '{{.Image}}'`).
2. **Scratch:** `S=/mnt/docker-appdata/network/traefik-v3/traefik/_certexport-test-031`;
   `sudo install -d -m 0700 $S/{data,certs,certs-b,hook}`; `sudo cp -p` `acme-http.json` and
   `acme-dns-cloudflare.json` (both `0600 root`) from the Traefik data directory into `$S/data`.
3. **Image:** the candidate under test (pull by digest; for pre-release tests, a locally built
   image transferred with `docker save | ssh … sudo docker load`). Record the digest.
4. **Runs** (each `tce-test-031-<case>`, `--network none`, `--restart no`, Watchtower opt-out,
   `-v $S/data:/data:ro -v $S/certs:/certs`), with production's environment copied from
   `sudo docker inspect traefik-certificate-exporter` (incl. `TRAEFIK_RESOLVERID_INOUTPUTPATHNAME=1`):
   run-once export; `cert.pem` SHA-256 fingerprints compared with `/mnt/certificates` (read
   only); second unchanged pass (no mtime changes; timing); passphrase case; watch mode with an
   in-place write **and** an atomic rename (`cp` to a temp name in `$S/data`, then `mv`) of a
   copied store; restart case with a throwaway labelled `whoami` and the socket.
5. **Record** in the story's notes: commands, exit codes, log excerpts (no secrets, no key
   material), timings (`time` per pass, certificate count), digests.
6. **Cleanup** (always, also on failure): remove `tce-test-031-*` and the throwaway `whoami`,
   `sudo rm -rf $S` (it holds private-key copies), remove host temp logs, remove pulled test
   images, close the SSH control session, `kdestroy`. Confirm production `traefik`,
   `traefik-certificate-exporter`, `cert-distributor` are still up and unchanged (same image
   digest as in step 1).

## Repository rules for agents

- Do not commit, push, tag, or change forge settings; commits happen at sprint closure.
  Forge settings, tokens, tags and production changes are maintainer-only actions; a story lists
  them under "Maintainer-only forge actions".
- `uv.lock` is an untracked stray file; leave it alone.
- ADR numbers: reserve with
  `uv run -q _bmad/scripts/pm-status.py adr-reserve --state-root _bmad-output/implementation-artifacts/state --epic E015 --slug <slug> --count 1 --adr-dir docs/adr`;
  never pick one by listing the directory.
- E015 has no dedicated docs/spine story. Since the 2026-10-12 consolidation the PRD and both
  spines already state the 0.3.1 target. Each story checks the spine text against what it ships,
  records the check and any deviation (with exact replacement text) in its notes file
  (`<sprint>/closure/notes-<story>.md`, section `## Spine/ADR amendments`), applies only a
  deviation, and replaces "ADR to be written by E015-S0x-00y" with the number it reserves;
  spine Changelog lines are appended, never rewritten. A story that writes or amends an ADR
  updates its row in `docs/architecture.md` §6 in the same change.
- Shared files edited by parallel stories: `docs/upgrading.md` `## 0.3.0 → 0.3.1` (E015-S01-001
  owns the heading; S01-002 and S02-002 add `###` subsections) and
  `docs/ci/pipeline-walkthrough.md` (S02-001 first; then S02-002 and S02-003 in parallel, in
  different sections). Whichever story merges second rebases and keeps both edits.
- Each story's `## Verification` section is the definition of done: run every command listed,
  record the output (or its tail) in the notes file, and record every run with
  `pm-status add-test-run`.

## Evidence rules (carried from E014; retrospective actions A2, A3, A5)

- **Never record a command that cannot exit 0 on correct code, or that cannot fail on the
  defect.** "No output" greps are recorded as `! grep -q …`, never `grep -c` expecting `0`
  (`grep -c` exits 1 when it counts zero); counts as `test "$(grep -c …)" = N`. A row is one
  `&&` chain: no `;` between checks (only the last status is recorded); no `cmd | tee log`
  whose status is `tee`'s (use the story's `actrun`, which returns `PIPESTATUS[0]`, or redirect
  to a file); no `! (…) | tee` (it negates `tee`); listings go to a file before they are
  checked, so a failing `gh`/`curl`/`ssh` fails the row; with `set -o pipefail`, never pipe
  into `grep -q` or `head` (SIGPIPE turns a match into a failure); clean-up is its own row,
  never a trailing `rm -rf` that masks the result. Test each such wrapper once against a
  planted violation and say so in the notes.
- `pm-status add-test-run` has no expected-failure mode (`--expect-exit` does not exist in
  v3.4.4). Record fail-first runs and expected-failure probes in the notes only, or as the real
  outer exit of a capturing command line. **Never record a synthetic exit code under a command
  label.**
- Record every run, failures too; `tests_passing` derives from the last run of each distinct
  command.
- Before writing a guard, check CI spine AD-4 ("No custom policy code") for the allowed
  mechanism; a guard's scope is derived from the source of truth, and its test plants a
  violation that attacks the scope, not only the rule.
- A verification row that cannot run in this environment (forge, production) is marked as
  maintainer/HITL evidence in the story and recorded in the notes when it runs; it is never
  replaced by a weaker local proxy without saying so.
- Notes are written before review; run `ruff` before `just check`.

## Maintainer approvals recorded at planning (2026-10-12)

- BL-E014-106 scope (S01-002) as recorded in `state/events.jsonl` (2026-10-12 note): see
  `maintainer-decisions.md` header. Every other decision is MD-06 … MD-23 there, accepted 2026-10-12 (MD-01 … MD-05 withdrawn by the
  LSIO constraint).
