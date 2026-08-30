# Engineering Standards — Node.js Overlay

Loaded on top of `standards-core.md` when the project (or component under review) is Node.js.

## Runtime version — current, supported, pinned

**Rule.** Use the **latest active LTS** of Node.js (or newer current where a specific
capability is needed and justified per core §8). Do not run on EOL Node.

- **Design/decision** — Target the latest active LTS at project start; record the version.
  Pin it so every environment matches:
  - `engines.node` in `package.json` (enforced, e.g. via `engine-strict`).
  - `.nvmrc` / `.node-version` for local + CI parity.
  - CI matrix runs on the pinned LTS (and optionally the next LTS for forward-readiness).
- **Keep current** — schedule LTS upgrades before EOL; an EOL runtime is a BLOCKER.

## Packaging & dependencies

- One package manager per repo (npm / pnpm / yarn); **lockfile committed**; CI installs
  frozen (`npm ci` / `pnpm i --frozen-lockfile`). pnpm preferred for monorepos/footprint.
- Dependencies GA, maintained, license-checked (core §7/§8). Avoid trivial micro-deps.
- Prefer **ESM** and native language features over legacy shims where the runtime supports them.

## Quality toolchain (aligns with core)

- **Types** — TypeScript in `strict` mode; types are contracts (core §3). Types over JSDoc-only.
- **Lint/format** — ESLint + Prettier (or Biome as the single tool) in CI.
- **Test** — Vitest/Jest; keep pure logic separable from I/O (core §4).
- **Logging** — one structured logger (e.g. `pino`) emitting JSON with a propagated
  `trace_id`/`correlation_id` (core §9); no stray `console.log` in production paths.

## Review checklist (Node-specific)

- [ ] Runs on latest active LTS (not EOL); version pinned via `engines` + `.nvmrc`, CI matches.
- [ ] Lockfile committed; CI installs frozen.
- [ ] TypeScript strict; ESLint/Prettier (or Biome) clean.
- [ ] Structured logger with propagated correlation ID; no production `console.log`.
- [ ] Dependencies GA, maintained, license-checked.
