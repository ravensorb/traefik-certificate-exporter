#!/usr/bin/env bash

set -euo pipefail

# --------------------------------------------------------------------------------------
# Runs the governed verifier locally, in a DISPOSABLE CLONE -- never against this tree.
#
# On 2026-09-01 running act directly against the repository destroyed it, losing every
# unpublished commit. `~/.actrc` sets `--bind`, so act mounts the host directory as the
# container's /github/workspace instead of copying it; verify-build.yaml's first job runs
# `actions/checkout` with a `ref:`, which logged
#
#     Deleting the contents of '<repo>'
#     git init '<repo>'
#
# and only then failed to fetch the ref, because that commit existed only locally. The
# destructive half had already run against the real .git. Committing often was no
# protection: the commits lived inside the directory that was deleted.
#
# Cloning first makes that harmless. `--no-hardlinks` is load-bearing -- without it the
# clone's objects are hardlinked into this repository's object store, so a destructive
# checkout could still reach them.
#
# It also fixes a second defect the incident exposed: because checkout resolves the SHA
# from `origin`, this only ever verified what the remote already had. A local clone
# carries local commits, so the ref resolves without a push.
#
# Consequence: this verifies HEAD, not the dirty working tree -- which is what CI would
# verify anyway. The script warns when the two differ.
#
# No credentials are passed. verify-build.yaml is the secret-free verifier (ADR-0007);
# a local run that injected secrets would not be exercising the same contract.
# --------------------------------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [ -n "$(git status --porcelain)" ]; then
    echo "WARNING: uncommitted changes will NOT be verified -- this runs against HEAD." >&2
fi

WORKTREE="$(mktemp -d -t act-verify-XXXXXXXX)"
trap 'rm -rf "$WORKTREE"' EXIT
git clone --quiet --local --no-hardlinks "$REPO_ROOT" "$WORKTREE"

# Refuse to continue unless we are demonstrably elsewhere: a clone that resolved back to
# the real repository would reintroduce the failure this script exists to prevent.
CLONE_ROOT="$(cd "$WORKTREE" && git rev-parse --show-toplevel)"
if [ "$CLONE_ROOT" = "$REPO_ROOT" ]; then
    echo "refusing to run: the disposable clone resolved to the real repository" >&2
    exit 1
fi

cd "$CLONE_ROOT"

SOURCE_SHA="$(git rev-parse HEAD)"
PACKAGE_VERSION="$(poetry version --short)"

echo "--------------------------------------------------------------------------------------"
echo "Running the governed verifier locally, in a disposable clone"
echo "Clone:  $CLONE_ROOT"
echo "Source: $SOURCE_SHA"
echo "Package version: $PACKAGE_VERSION"
echo "--------------------------------------------------------------------------------------"

# -P ubuntu-24.04=... is required: act ships no default image mapping for that runner
# label (only older ubuntu-latest/-22.04/-20.04 are pre-mapped), so verify-build.yaml's
# `runs-on: ubuntu-24.04` jobs are silently skipped ("Skipping unsupported platform")
# without it.
act workflow_dispatch \
    -W .github/workflows/verify-build.yaml \
    --input channel=ci \
    --input package-version="$PACKAGE_VERSION" \
    --input source-sha="$SOURCE_SHA" \
    -P ubuntu-24.04=catthehacker/ubuntu:act-latest \
    | tee "$REPO_ROOT/act-build-traefik-certificate-exporter.log"
