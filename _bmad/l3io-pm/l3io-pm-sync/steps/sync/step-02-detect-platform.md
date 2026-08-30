# Sync Step 02: Detect Platform

Communicate all responses in `{communication_language}`.

Detect the external sync platform from the git remote and verify authentication. Bind
variables used by step-03 and step-04. This step runs for every mode — `setup` is not a
special case here, since detection and auth are cheap, stateless, and idempotent.

## 1. Detect platform from the git remote

```bash
python3 {skill-root}/scripts/detect-platform.py {project-root}
```

The script takes the project root as its only argument — no flags. It reads `origin` (then
`upstream`, then any remote) and prints a JSON object to stdout.

Parse the JSON and bind:
- `{sync_platform}` = `.platform` (`"github"` or `"unknown"`)
- `{platform_owner}` = `.owner` (github only)
- `{platform_repo}` = `.repo` (github only)
- `{remote_url}` = `.remote_url`

If `{sync_platform}` is `unknown`:
```
Could not detect a supported sync platform from the git remote ({remote_url}).
l3io-pm-sync currently supports GitHub only. Point a remote at a GitHub repo and re-run.
```
BLOCKED: platform detection failed.

## 2. Resolve auth method

`{github_auth_method}` comes from `customize.toml` (`mcp` or `gh-cli`) and is a preference,
not a guarantee — verify what is actually usable:

- If `{github_auth_method}` = `mcp` — check whether GitHub MCP tools are present in your
  current tool set (tool names beginning `mcp__github`). If they are, use them for every
  remote operation in step-03/step-04. If none are available, fall through to the `gh-cli`
  check below instead of blocking.
- `gh-cli` (or the MCP fallback above) — run:
  ```bash
  gh auth status
  ```
  A non-zero exit means the `gh` CLI is not authenticated.

If neither GitHub MCP tools nor `gh auth status` succeed:
```
No usable GitHub authentication found. Configure GitHub MCP, or run `gh auth login`, then retry.
```
BLOCKED: authentication unavailable.

Bind `{auth_method}` = whichever check actually succeeded (`mcp` or `gh-cli`) — this may
differ from `{github_auth_method}` if the preferred method fell back.

## 3. Locate sync-state.yaml

```bash
cat {project-root}/_bmad/sync-state.yaml 2>/dev/null || echo "(absent — created on first push)"
```

Bind `{sync_state_file}` = `{project-root}/_bmad/sync-state.yaml`. `sync-state.py` treats a
missing file as empty state everywhere it reads (`list` returns `[]`, `get` reports no
mapping) — an absent file is not an error at this step, in any mode. It is written into
existence the first time `upsert` runs (during `push`).

## 4. Output

```
Step 02 complete — platform: {sync_platform} ({platform_owner}/{platform_repo}), auth: {auth_method}, sync-state: {sync_state_file}
```
