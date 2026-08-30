# Engineering Standards — Docker Overlay (COMING NEXT — stub)

> **Status: placeholder.** This overlay is scaffolded but not yet authored. Until it is
> filled in, apply `standards-core.md` and treat the notes below as provisional guidance.

Planned rules (draft):

- Multi-stage builds; minimal, pinned base images (prefer slim/distroless; GA tags, core §8).
- Pin base images by digest for reproducibility/supply-chain (core §7).
- Non-root runtime user; least privilege; no secrets baked into layers or ENV.
- `.dockerignore` to keep context lean; deterministic, cached, ordered layers.
- Healthchecks; explicit, documented EXPOSE/labels; structured logs to stdout (core §9).
- Image scanning in CI; SBOM generation.

TODO: promote to full standard alongside PowerShell and shell overlays.
