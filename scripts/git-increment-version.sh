#!/bin/sh

echo >&2 "This unsafe release path is retired."
echo >&2 "Use 'just release-dry-run <major|minor|patch>' to inspect a release."
echo >&2 "Use 'just release <major|minor|patch>' or 'python scripts/release_version.py --resume-push' to publish."
exit 2
