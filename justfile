set shell := ["bash", "-euo", "pipefail", "-c"]

# The default branch, derived once for `act` and `release`: origin/HEAD with `origin/`
# stripped, else `main`. Evaluated at load time by every recipe, so it never fails.
default_branch := `b="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"; b="${b#origin/}"; echo "${b:-main}"`

# The first run also installs [tool.poetry.requires-plugins] (poetry-dynamic-versioning)
# into the project-local .poetry/ plugin environment, which needs network access.
# Needs a vX.Y.Z tag reachable from HEAD (strict versioning, AD-7); in a shallow or
# tagless clone run `git fetch --tags --unshallow` first.
# `sync --all-groups` makes the venv exactly poetry.lock, optional groups included, so the
# pip-audit hook audits every lock group without naming one (ADR-0042).
# Install the Poetry-managed project and development environment.
install:
    poetry sync --all-groups

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

# No secrets or variables are passed, so every publishing destination stays disabled, and
# act's ambient secret sources are neutralised (AD-9, AD-16, ADR-0052): HOME and
# XDG_CONFIG_HOME are fresh temporary directories, so ~/.actrc, act's XDG actrc and
# ~/.docker/config.json are not read (image pulls are anonymous); --secret-file and
# --var-file are /dev/null, so ./.secrets and ./.vars are not read; `-s GITHUB_TOKEN=` is
# an explicitly empty token, so act does not fall back to `gh auth token` (gh reads the
# system keyring, which a fresh HOME does not hide); and a ./.actrc in the working
# directory, which act would read, makes the recipe refuse with exit 1.
# Not neutralised: a ./.env file still sets container environment variables (never
# `secrets.*` or `vars.*`), and a raw `act` run outside this recipe is not covered: even
# with no `-s`, act fills GITHUB_TOKEN from `gh auth token`, and release.yaml's forge
# release falls back to that token (ADR-0052).
# The platform mapping is passed here, so -P preferences in an actrc are ignored.
# The exit status is act's own. Run `just act dev.yaml` from main (or pass an event file
# with `ref: refs/heads/main`) so the run matches dev.yaml's branch filter.
# --defaultbranch sets github.event.repository.default_branch, which release.yaml's
# ancestry check reads (act would otherwise say `master`); that check also needs an
# `origin` remote tracking the default branch, or it fails closed (ADR-0038).
# Run a workflow locally under act with its own trigger event (AD-16).
act workflow="ci.yaml":
    if [ -e .actrc ] || [ -L .actrc ]; then echo >&2 "act: refusing to run with ./.actrc present (it can pass secrets); remove it"; exit 1; fi
    h="$(mktemp -d)" && x="$(mktemp -d)" && a="$(mktemp -d)" && HOME="$h" XDG_CONFIG_HOME="$x" act --detect-event -W .github/workflows/{{ workflow }} --defaultbranch {{ quote(default_branch) }} --artifact-server-path "$a" -P ubuntu-latest=ghcr.io/catthehacker/ubuntu:act-latest --secret-file /dev/null --var-file /dev/null -s GITHUB_TOKEN=

# Infisical project `home-lab-discovery`, which holds the publish tokens.
infisical_project := "45365f20-36e8-4d4d-87f3-1554c5ae0615"
infisical_env := "prod"

# Same isolation as `act`, but each named destination gets its token from Infisical, read
# into this recipe's environment one secret at a time (never argv, never a file) and passed
# with `-s NAME`. Destinations: pypi (PYPI_TOKEN), testpypi (PYPI_TEST_TOKEN), gitea
# (GITEA_TOKEN), dockerhub (DOCKERHUB_TOKEN). PyPI and TestPyPI are enabled by their token
# alone, so a destination that is not named gets no token. The PUBLISH_* variables come from
# `vars`, an act var file (NAME=value lines), e.g. PUBLISH_GITEA_USERNAME, _REGISTRY, _IMAGE,
# _PYPI_URL, PUBLISH_DOCKERHUB_USERNAME, _IMAGE. GITHUB_TOKEN stays empty, so GHCR and the
# forge release stay disabled under act (ADR-0052).
# Run a workflow under act and publish to the named destinations, e.g.
# `just act-publish dev.yaml ~/act/publish.vars testpypi,gitea`.
act-publish workflow vars destinations:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -e .actrc ] || [ -L .actrc ]; then echo >&2 "act-publish: refusing to run with ./.actrc present (it can pass secrets); remove it"; exit 1; fi
    vars={{ quote(vars) }}
    if [ ! -f "$vars" ]; then echo >&2 "act-publish: var file '$vars' not found"; exit 1; fi
    secret_args=()
    IFS=',' read -ra dests <<< {{ quote(destinations) }}
    for d in "${dests[@]}"; do
        case "$d" in
            pypi) from=PYPI_TOKEN; to=PUBLISH_PYPI_TOKEN ;;
            testpypi) from=PYPI_TEST_TOKEN; to=PUBLISH_TESTPYPI_TOKEN ;;
            gitea) from=GITEA_TOKEN; to=PUBLISH_GITEA_TOKEN ;;
            dockerhub) from=DOCKERHUB_TOKEN; to=PUBLISH_DOCKERHUB_TOKEN ;;
            *) echo >&2 "act-publish: unknown destination '$d' (pypi, testpypi, gitea, dockerhub)"; exit 1 ;;
        esac
        value="$(infisical secrets get "$from" --projectId {{ quote(infisical_project) }} --env {{ quote(infisical_env) }} --plain --silent)"
        if [ -z "$value" ]; then echo >&2 "act-publish: Infisical secret $from is empty or missing"; exit 1; fi
        export "$to=$value"
        secret_args+=(-s "$to")
        echo "act-publish: $d enabled ($from -> $to)"
    done
    unset value GITHUB_TOKEN GH_TOKEN
    h="$(mktemp -d)"; x="$(mktemp -d)"; a="$(mktemp -d)"
    HOME="$h" XDG_CONFIG_HOME="$x" act --detect-event -W .github/workflows/{{ workflow }} --defaultbranch {{ quote(default_branch) }} --artifact-server-path "$a" -P ubuntu-latest=ghcr.io/catthehacker/ubuntu:act-latest --secret-file /dev/null --var-file "$vars" -s GITHUB_TOKEN= "${secret_args[@]}"

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
    default={{ quote(default_branch) }}
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
