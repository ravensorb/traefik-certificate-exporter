# ADR-0002: linuxserver.io base image and PUID/PGID privilege model

- **Status:** Accepted (existing practice, recorded retroactively)
- **Date:** 2026-08-30
- **Deciders:** Maintainer (ravensorb)
- **Principle(s) in tension:** Docker overlay (non-root runtime, minimal/pinned base images), Core §7/§8

## Context

The Docker image is built `FROM ghcr.io/linuxserver/baseimage-alpine:3.19`, which brings
s6-overlay init and the linuxserver.io convention of running the main process as root at
container start but dropping to a configured `PUID`/`PGID` for file ownership and (depending
on the service script) process execution. Reviewed in isolation, "no explicit non-root
`USER`" looks like a Docker-overlay violation; in the linuxserver.io ecosystem it is the
documented, expected pattern.

## Options considered

| Option | Pros | Cons | Standards fit |
|--------|------|------|---------------|
| A. Keep linuxserver.io base + PUID/PGID (current) | Consistent with the rest of the ravensorb/linuxserver-style image fleet; users already expect `PUID`/`PGID` env vars; s6-overlay handles config bootstrapping | Root-owned entrypoint before privilege drop; base image tag (`3.19`) not pinned by digest | Partially satisfies Docker overlay once digest-pinned; the privilege-drop pattern is an accepted deviation from "non-root runtime user" taken literally |
| B. Minimal distroless/slim image with a hard-coded non-root `USER` | Smaller attack surface, no root at any point | Loses PUID/PGID volume-ownership convenience that this tool's users (mounting host paths for certs/data) rely on; inconsistent with sibling images | Best literal fit for Docker overlay, worst fit for actual deployment ergonomics |

## Decision

Keep the linuxserver.io base image and PUID/PGID model (Option A). The volume-ownership
ergonomics it provides are load-bearing for this tool's actual use case (bind-mounting host
directories for Traefik's ACME store and the certs output). Close the gap with the standard
by pinning the base image by digest (review finding #12) rather than by abandoning the
pattern.

## Consequences

- Positive: no disruption to existing deployments' volume permission expectations.
- Negative / trade-offs accepted: the entrypoint still starts as root before s6 drops
  privilege; mitigated by keeping the base image current and pinned.
- Follow-ups: pin `FROM ghcr.io/linuxserver/baseimage-alpine:3.19` by digest; re-pin on each
  intentional base image bump (tracked in PRD backlog item #12).
