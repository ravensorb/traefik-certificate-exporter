# Engineering Standards — .NET / C# Overlay

Loaded on top of `standards-core.md` when the project (or component under review) is .NET/C#.

## Framework version — latest, supported

**Rule.** Target the **latest GA .NET release** (prefer the current **LTS** for
production services; STS is acceptable with a recorded upgrade plan). Do not target EOL
frameworks.

- **Design/decision** — Set `<TargetFramework>` to the current supported version; use the
  latest GA C# language version. Multi-target only when shipping a library that must support
  older consumers — record why.
- **Keep current** — upgrade before EOL; an EOL target framework is a BLOCKER for shipped code.

## Deployment — self-contained output

**Rule.** Applications compile to **self-contained** output — the runtime ships with the
app, no dependency on a framework install on the target host.

- **Design/decision** — Publish self-contained (`--self-contained true`) with an explicit
  RID (Runtime IDentifier) per target platform. Prefer, where it fits:
  - **Single-file** publish (`PublishSingleFile`) for simple distribution.
  - **Trimming** (`PublishTrimmed`) to cut size — validate no reflection/trimming breakage.
  - **AOT** (`PublishAot`) where startup/footprint matters and the app is AOT-compatible.
  - Record the chosen mode + RIDs in an ADR; note the size/compat trade-off.
- **Review** — Flag apps published framework-dependent when self-contained was required,
  missing RID targeting, or trimming/AOT enabled without validation. Libraries are exempt
  (they are consumed, not hosted) — this rule targets deployable apps.

## Quality toolchain (aligns with core)

- **Contracts/nullability** — `<Nullable>enable</Nullable>`, `<TreatWarningsAsErrors>` on;
  nullable reference types are contract enforcement (core §3).
- **Analyzers** — .NET analyzers + `.editorconfig` enforced in CI; `dotnet format` clean.
- **Test** — xUnit/NUnit; inject dependencies via DI (core §4).
- **Logging** — `ILogger<T>` with structured logging (message templates, not string concat)
  and a propagated correlation/trace ID (core §9); align with OpenTelemetry.

## Review checklist (.NET-specific)

- [ ] Targets a supported (non-EOL) .NET; current LTS for services.
- [ ] Deployable apps publish **self-contained** with explicit RID(s); mode recorded.
- [ ] Nullable enabled, warnings-as-errors, analyzers clean.
- [ ] `ILogger` structured logging with propagated correlation ID; no `Console.WriteLine` in prod.
- [ ] Dependencies (NuGet) GA, maintained, license-checked (core §7/§8).
