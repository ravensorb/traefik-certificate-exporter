---
name: l3io-pm-sync
description: DEPRECATED forwarder for /l3io-sync — renamed in 3.1.3. Use /l3io-sync instead. This forwarder will be removed in 4.0.0.
---

# l3io-pm-sync (DEPRECATED — use /l3io-sync)

This skill was renamed to `/l3io-sync` in v3.1.3. This forwarder exists only so old
invocations continue to work; it will be **removed in v4.0.0**.

## On Activation

1. Print one line to stderr, verbatim:

   ```
   NOTICE: /l3io-pm-sync is deprecated (renamed to /l3io-sync in v3.1.3). This forwarder will be removed in v4.0.0.
   ```

2. Invoke `skill:l3io-sync` with the exact arguments the user gave to `/l3io-pm-sync`, and report
   its output unchanged. Add no summary of your own — the forwarded skill's output is the
   response.
