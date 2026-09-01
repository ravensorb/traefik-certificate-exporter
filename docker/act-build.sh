#!/usr/bin/env bash

set -euo pipefail

# --------------------------------------------------------------------------------------
# Runs act against a DISPOSABLE CLONE, never against this working tree.
#
# On 2026-09-01 running act directly against the repository destroyed it. The mechanism:
# `~/.actrc` sets `--bind`, so act mounts the host directory as the container's
# /github/workspace instead of copying it; a workflow's `actions/checkout` step then logged
#
#     Deleting the contents of '<repo>'
#     git init '<repo>'
#
# and only afterwards discovered it could not fetch the requested ref. The destructive half
# had already run, against the real .git -- taking every local commit with it, because
# commits live inside the directory that was deleted.
#
# Cloning first makes that harmless: act may do whatever it likes to the throwaway copy.
# `--no-hardlinks` is load-bearing -- without it the clone's objects are hardlinked back
# into this repository's object store, and a destructive checkout could still reach them.
#
# Consequence worth knowing: this verifies the last COMMIT, not your dirty working tree,
# because that is what a clone carries. That matches what CI would verify, and the script
# warns when the two differ.
# --------------------------------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if ! git diff --quiet HEAD 2>/dev/null || [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
    echo "WARNING: uncommitted changes will NOT be verified -- this runs against HEAD." >&2
    echo "         Commit them first if you want them covered." >&2
fi

WORKTREE="$(mktemp -d -t act-verify-XXXXXXXX)"
cleanup() { rm -rf "$WORKTREE"; }
trap cleanup EXIT

git clone --quiet --local --no-hardlinks "$REPO_ROOT" "$WORKTREE"

# Refuse to continue unless we are demonstrably somewhere else. A clone that silently
# resolved back to the real repository would reintroduce the exact failure above.
CLONE_ROOT="$(cd "$WORKTREE" && git rev-parse --show-toplevel)"
if [ "$CLONE_ROOT" = "$REPO_ROOT" ]; then
    echo "refusing to run: the disposable clone resolved to the real repository" >&2
    exit 1
fi

# Carry across the local-only inputs a clone cannot contain (gitignored by design).
for extra in .pipeline.env.traefik-certificate-exporter .pipeline.secrets.traefik-certificate-exporter; do
    [ -f "$REPO_ROOT/$extra" ] && cp "$REPO_ROOT/$extra" "$WORKTREE/$extra"
done

cd "$CLONE_ROOT"

EVENT_NAME=${1:-push}
GITHUB_TAG="$(git describe --tags --abbrev=0)"
SOURCE_SHA="$(git rev-parse HEAD)"

echo "--------------------------------------------------------------------------------------"
echo "Running workflows locally in a disposable clone"
echo "Clone:   $CLONE_ROOT"
echo "Source:  $SOURCE_SHA"
echo "Version: $GITHUB_TAG"
echo "Event:   $EVENT_NAME"
echo "--------------------------------------------------------------------------------------"

LOG="$REPO_ROOT/act-build-traefik-certificate-exporter.log"

# -P ubuntu-24.04=... is required: act ships no default image mapping for that runner label
# (only ubuntu-latest/-22.04/-20.04 are pre-mapped), so `runs-on: ubuntu-24.04` jobs are
# silently skipped ("Skipping unsupported platform") without it.
ACT_ARGS=(
    --env GITHUB_TAG="${GITHUB_TAG#v}"
    -P ubuntu-24.04=catthehacker/ubuntu:act-latest
    -a "${EVENT_NAME}"
)
[ -f "$CLONE_ROOT/.pipeline.env.traefik-certificate-exporter" ] && \
    ACT_ARGS+=(--env-file "$CLONE_ROOT/.pipeline.env.traefik-certificate-exporter")

act "${ACT_ARGS[@]}" | tee "$LOG"
