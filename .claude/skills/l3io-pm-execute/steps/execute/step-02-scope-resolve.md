# Step 02: Scope Resolution

Communicate all responses in `{communication_language}`.

Parse the invocation argument to determine execution scope. This step sets bind variables used
by all subsequent execute steps.

## 1. Parse scope argument

Inspect the text that follows `/l3io-pm-execute` (or the args block in context):

| Argument pattern | Scope | Bind variables |
|---|---|---|
| None (or `all`) | Full plan — all unstarted epics | `{exec_scope}=full`, `{scope_epic_keys}=all` |
| `E{nnn}` | Single epic | `{exec_scope}=epic`, `{scope_epic_keys}=[E{nnn}]` |
| `E{nnn}-S{nn}` | Single sprint | `{exec_scope}=sprint`, `{scope_epic_keys}=[E{nnn}]`, `{scope_sprint_key}=S{nn}` |

If the argument does not match any pattern, output:
```
Unrecognized scope argument. Usage:
  /l3io-pm-execute              — run all epics in plan phase order
  /l3io-pm-execute E001         — run a single epic
  /l3io-pm-execute E001-S02     — run a single sprint
```
BLOCKED: unrecognized scope argument.

## 2. State node existence check

For each key in `{scope_epic_keys}` (skip if `all`):

```bash
python3 {pm_status} verify --state-root {pm_state_root} --scope epic --epic {epic_key}
```

`verify --scope epic` resolves the key across `planned/`, `active/`, and `archived/` — no need
to probe each folder separately. Exit code `3` means the key was not found anywhere:
```
BLOCKED: {epic_key} not found under {pm_state_root} — check key and re-run.
```

## 3. Lock pre-check

For each scoped epic key:

```bash
python3 {pm_status} check-lock \
  --state-root {pm_state_root} \
  --epic {epic_key} \
  --session-id {session_id}
```

If exit code 5 (LOCKED by another session), display the lock details and:
```
BLOCKED: {epic_key} is owned by another session. Wait for TTL expiry or resolve manually.
```

## 4. Output

```
Step 02 complete — scope: {exec_scope}, epics: {scope_epic_keys}
```
