set shell := ["bash", "-euo", "pipefail", "-c"]

# Install the Poetry-managed project and development environment.
install:
    poetry install

# Validate the lock file and run every configured pre-commit check.
# Non-mutating. Never rewrites the working tree -- `just check` is the release
# transaction's gate and it aborts if the tree moves. Use `just fix` to apply autofixes.
lint:
    poetry check --lock
    SKIP=ruff-check,ruff-format poetry run pre-commit run --all-files
    poetry run pre-commit run --hook-stage manual --all-files ruff-check-nofix
    poetry run pre-commit run --hook-stage manual --all-files ruff-format-check

# Apply the autofixes `just lint` only reports. Rewrites files.
fix:
    poetry run pre-commit run --all-files

# Run the project test suite.
test:
    poetry run pytest

# Run all local lint and test gates.
check: lint test

# Run the governed verifier locally through its direct Act entry point.
test-local:
    ./docker/act-build.sh

# Validate and report a semantic release without changing local or remote state.
release-dry-run bump:
    poetry run python scripts/release_version.py {{ bump }} --dry-run

# Prepare a release commit and annotated tag, then publish both atomically.
release bump:
    poetry run python scripts/release_version.py {{ bump }} --push

# Revalidate and atomically publish an existing local release commit and tag.
release-resume:
    poetry run python scripts/release_version.py --resume-push

# Build and validate exactly one wheel and one source distribution.
build: check
    poetry build --clean
    test "$(find dist -maxdepth 1 -type f -name '*.whl' | wc -l)" -eq 1
    test "$(find dist -maxdepth 1 -type f -name '*.tar.gz' | wc -l)" -eq 1
    poetry run twine check dist/*

# Build and locally load the native image from the exact local wheel.
image: build
    #!/usr/bin/env bash
    set -euo pipefail
    shopt -s nullglob
    wheels=(dist/*.whl)
    if (( ${#wheels[@]} != 1 )); then
        echo >&2 "wheel contract: dist must contain exactly one wheel"
        exit 1
    fi
    wheel="${wheels[0]}"
    WHEEL_PATH="$wheel" \
    WHEEL_SHA256="$(poetry run python -c 'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' "$wheel")" \
    VERSION="$(poetry run python -c 'import sys, zipfile; archive = zipfile.ZipFile(sys.argv[1]); metadata = archive.read(next(name for name in archive.namelist() if name.endswith(".dist-info/METADATA"))).decode(); print(next(line.removeprefix("Version: ") for line in metadata.splitlines() if line.startswith("Version: ")))' "$wheel")" \
    REVISION="$(git rev-parse HEAD)" \
        docker buildx bake image
