set shell := ["bash", "-euo", "pipefail", "-c"]

# The first run also installs [tool.poetry.requires-plugins] (poetry-dynamic-versioning)
# into the project-local .poetry/ plugin environment, which needs network access.
# Needs a vX.Y.Z tag reachable from HEAD (strict versioning, AD-7); in a shallow or
# tagless clone run `git fetch --tags --unshallow` first.
# Install the Poetry-managed project and development environment.
install:
    poetry install

# Run exactly the gates CI runs (AD-3): every pre-commit hook, then the test suite.
check:
    poetry run pre-commit run --all-files
    poetry run pytest

# Clean dist/, then build the wheel and sdist; the version comes from git tags (AD-7).
build:
    rm -rf dist
    poetry build

# Build and load the runtime image locally from the exact wheel `build` produced (AD-17).
image: build
    #!/usr/bin/env bash
    set -euo pipefail
    shopt -s nullglob
    wheels=(dist/*.whl)
    if (( ${#wheels[@]} != 1 )); then
        echo >&2 "image: dist/ must contain exactly one wheel, found ${#wheels[@]}"
        exit 1
    fi
    wheel="${wheels[0]}"
    # The wheel's own PEP 440 Version; never recomputed here (AD-7).
    version="$(poetry run python -c 'import email.parser, sys, zipfile; z = zipfile.ZipFile(sys.argv[1]); name = next(n for n in z.namelist() if n.endswith(".dist-info/METADATA")); print(email.parser.Parser().parsestr(z.read(name).decode())["Version"])' "$wheel")"
    docker build \
        -f docker/Dockerfile \
        --target runtime \
        --load \
        --build-arg POETRY_VERSION=2.4.2 \
        --build-arg WHEEL_PATH="$wheel" \
        --build-arg WHEEL_SHA256="$(sha256sum "$wheel" | cut -d' ' -f1)" \
        --build-arg VERSION="$version" \
        --build-arg REVISION="$(git rev-parse HEAD)" \
        -t traefik-certificate-exporter:local \
        .

# No secrets or variables are passed, so every publishing destination stays disabled.
# The exit status is act's own. Run `just act dev.yaml` from main (or pass an event file
# with `ref: refs/heads/main`) so the run matches dev.yaml's branch filter.
# Run a workflow locally under act with its own trigger event (AD-16).
act workflow="ci.yaml":
    act --detect-event -W .github/workflows/{{ workflow }} --artifact-server-path "$(mktemp -d)"

# Creates no commit and pushes no branch.
# Cut a release: push one annotated tag vX.Y.Z on the default branch's HEAD (AD-15).
release bump:
    #!/usr/bin/env bash
    set -euo pipefail
    bump="{{ bump }}"
    case "$bump" in
        major|minor|patch) ;;
        *) echo >&2 "release: bump must be major, minor or patch, got '$bump'"; exit 1 ;;
    esac
    dirty="$(git status --porcelain)"
    if [ -n "$dirty" ]; then
        echo >&2 "release: working tree is not clean:"; echo >&2 "$dirty"; exit 1
    fi
    default="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD || true)"
    default="${default#origin/}"
    default="${default:-main}"
    branch="$(git rev-parse --abbrev-ref HEAD)"
    if [ "$branch" != "$default" ]; then
        echo >&2 "release: current branch is '$branch', must be the default branch '$default'"; exit 1
    fi
    git fetch --tags --force origin
    head_sha="$(git rev-parse HEAD)"
    origin_sha="$(git rev-parse "origin/$default")"
    if [ "$head_sha" != "$origin_sha" ]; then
        echo >&2 "release: HEAD $head_sha does not equal origin/$default $origin_sha"; exit 1
    fi
    "{{ just_executable() }}" --justfile "{{ justfile() }}" check
    dirty="$(git status --porcelain)"
    if [ -n "$dirty" ]; then
        echo >&2 "release: 'just check' modified the working tree:"; echo >&2 "$dirty"; exit 1
    fi
    # awk reads all input and always exits 0, so pipefail cannot abort on SIGPIPE or no match.
    base="$(git tag --merged HEAD --sort=-v:refname | awk '/^v[0-9]+\.[0-9]+\.[0-9]+$/ && !f {print; f=1}')"
    if [ -z "$base" ]; then
        echo >&2 "release: no tag matching ^v[0-9]+\.[0-9]+\.[0-9]+\$ is reachable from HEAD"; exit 1
    fi
    # A commit is released once: a re-run on an already-tagged HEAD refuses rather than
    # stacking a second version on the same commit.
    if [ "$(git rev-parse "$base^{commit}")" = "$head_sha" ]; then
        echo >&2 "release: HEAD $head_sha is already released as $base"; exit 1
    fi
    next="$(poetry run pysemver bump "$bump" "${base#v}")"
    tag="v$next"
    echo "release: base tag      $base"
    echo "release: bump          $bump"
    echo "release: new tag       $tag"
    echo "release: HEAD          $head_sha"
    echo "release: origin/$default $origin_sha"
    if git rev-parse --quiet --verify "refs/tags/$tag" >/dev/null; then
        echo >&2 "release: tag $tag already exists locally"; exit 1
    fi
    remote_tag="$(git ls-remote --tags origin "refs/tags/$tag")"
    if [ -n "$remote_tag" ]; then
        echo >&2 "release: tag $tag already exists on origin: $remote_tag"; exit 1
    fi
    git tag -a "$tag" -m "$tag"
    if ! git push origin "refs/tags/$tag"; then
        echo >&2 "release: push failed; local tag $tag was created."
        echo >&2 "  retry:   git push origin refs/tags/$tag"
        echo >&2 "  abandon: git tag -d $tag"
        exit 1
    fi
    echo "release: pushed refs/tags/$tag"
