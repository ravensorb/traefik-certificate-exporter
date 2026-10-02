---
name: l3io-pm-execute
description: DEPRECATED forwarder for /l3io-execute — renamed in 3.1.3. Use /l3io-execute instead. This forwarder will be removed in 4.0.0.
---

# l3io-pm-execute (DEPRECATED — use /l3io-execute)

This skill was renamed to `/l3io-execute` in v3.1.3. This forwarder exists only so old
invocations continue to work; it will be **removed in v4.0.0**.

## On Activation

1. Print one line to stderr, verbatim:

   ```
   NOTICE: /l3io-pm-execute is deprecated (renamed to /l3io-execute in v3.1.3). This forwarder will be removed in v4.0.0.
   ```

2. Invoke `skill:l3io-execute` with the exact arguments the user gave to `/l3io-pm-execute`, and report
   its output unchanged. Add no summary of your own — the forwarded skill's output is the
   response.
