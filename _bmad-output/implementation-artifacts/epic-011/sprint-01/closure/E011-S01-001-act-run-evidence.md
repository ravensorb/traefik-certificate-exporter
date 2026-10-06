# BL-E007-002 evidence: local `docker/act-build.sh` run, 2026-10-06

The wrapper's own retention path, `tee "$REPO_ROOT/act-build-traefik-certificate-exporter.log"`,
writes to a path matched by `.gitignore`'s `**/*.log`, so the transcript cannot be committed where
the script leaves it. This file is that transcript, archived where it can be reviewed.

## What was run

| | |
|---|---|
| Command | `docker/act-build.sh` (never `act` against the working tree) |
| Date | 2026-10-06 |
| Source SHA | `2213e429ed3eb83733b89744db835f267124f9c4` |
| Package version | `0.2.0` |
| Disposable clone | `/tmp/act-verify-IwtvfDEd` (resolved elsewhere; the `CLONE_ROOT = REPO_ROOT` guard did not fire) |
| `act` | `/usr/local/bin/act` |
| Docker | Engine 29.8.2, daemon reachable, Buildx v0.37.1 |
| Outcome | **completed, failed** in the first job (`Source identity`) |

## Outcome: attempted, blocked by `actions/checkout` rejecting the clone's `origin`

This is a completed run, not an unattempted one, and it is a real result: `act` planned the
workflow, started the `ubuntu-24.04` runner container, resolved `actions/checkout@v7` from its
action cache and executed it. The failure is at the first step of the first job and is definitive.

`act` derives `GITHUB_REPOSITORY` from the checked-out repository's `origin` remote. In the
disposable clone that remote is a filesystem path (`git clone --local --no-hardlinks` points
`origin` at this repository's directory), so `github.repository` is a path and `actions/checkout`
rejects it before doing anything:

```
::error::Invalid repository '/home/.../traefik/traefik-certificate-exporter'. Expected format {owner}/{repo}.
```

That is structural, not transient, and it is the mirror image of the property the clone exists to
provide. The clone is what makes a local-only commit resolvable at all — `origin` must point at the
local path for the SHA to be fetchable — and it is exactly that `origin` shape `actions/checkout`
refuses. Rewriting the clone's `origin` to `https://github.com/ravensorb/traefik-certificate-exporter.git`
would satisfy the format check and then fail one step later for the original reason the clone was
introduced: `git branch -r --contains HEAD` is empty for this SHA, so GitHub cannot serve the ref.

Conclusion for BL-E007-002: the wrapper is **safe and now demonstrably executes**, and it is still
**unproven end to end**. The remaining blocker is named and reproducible rather than unknown.
Closing the rest of the gap means giving the Act run a ref source `actions/checkout` will accept —
a change to the wrapper's clone/mount strategy that is a redesign of `docker/act-build.sh`, which
this story's technical ACs explicitly exclude ("no required signature change", "do not rebuild it").

## Second, environment-only finding: value-less secrets in `~/.actrc`

The first invocation did not reach `act`'s planner at all:

```
level=error msg="failed to read input: inappropriate ioctl for device"
Provide value for 'PYPI_CUSTOM_USERNAME':
```

The operator's `~/.actrc` declares `-s PYPI_CUSTOM_USERNAME`, `-s PYPI_TOKEN` and others with no
`=value`, so `act` prompts for each; with no TTY the prompt fails. This is an out-of-repo developer
environment file, which this story's non-goals forbid changing. It was worked around for this run by
exporting placeholder values in the invoking environment only — no credential was introduced into
the local-run path, and nothing was written outside the repository. `verify-build.yaml` is the
secret-free verifier (ADR-0007) and consumes none of them.

## Transcript (`act-build-traefik-certificate-exporter.log`, verbatim)

```text
[Verify build/Source identity] ⭐ Run Set up job
[Verify build/Source identity] 🚀  Start image=catthehacker/ubuntu:act-latest
[Verify build/Source identity]   🐳  docker pull image=catthehacker/ubuntu:act-latest platform= username= forcePull=false
[Verify build/Source identity]   🐳  docker create image=catthehacker/ubuntu:act-latest platform= entrypoint=["tail" "-f" "/dev/null"] cmd=[] network="host"
[Verify build/Source identity]   🐳  docker run image=catthehacker/ubuntu:act-latest platform= entrypoint=["tail" "-f" "/dev/null"] cmd=[] network="host"
[Verify build/Source identity]   🐳  docker exec cmd=[node --no-warnings -e console.log(process.execPath)] user= workdir=
[Verify build/Source identity]   ✅  Success - Set up job
[Verify build/Source identity] GoGitActionCacheOfflineMode fetch content https://github.com/actions/checkout with ref v7 at ~/.cache/act/actions-checkout.git
[Verify build/Source identity] GoGitActionCache get content actions/checkout with sha 3d3c42e5aac5ba805825da76410c181273ba90b1 subpath 'action.yml'
[Verify build/Source identity] ⭐ Run Main Checkout exact source with full tag history
[Verify build/Source identity]   🐳  docker exec cmd=[/opt/acttoolcache/node/24.19.0/x64/bin/node /var/run/act/actions/actions-checkout@v7/dist/index.js] user= workdir=
[Verify build/Source identity]   ❗  ::error::Invalid repository '/home/.../traefik/traefik-certificate-exporter'. Expected format {owner}/{repo}.
[Verify build/Source identity]   ❌  Failure - Main Checkout exact source with full tag history [1.20058255s]
[Verify build/Source identity] exitcode '1': failure
[Verify build/Source identity] ⭐ Run Post Checkout exact source with full tag history
[Verify build/Source identity]   ✅  Success - Post Checkout exact source with full tag history [285.846717ms]
[Verify build/Source identity] ⭐ Run Complete job
[Verify build/Source identity] Cleaning up container for job Source identity
[Verify build/Source identity]   ✅  Success - Complete job
[Verify build/Source identity] 🏁  Job failed
Error: Job 'Source identity' failed
```
