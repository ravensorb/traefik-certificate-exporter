import difflib
from collections.abc import Iterable


def nearest_name(candidate: str, options: Iterable[str]) -> str | None:
    """The closest of `options` to `candidate`, or None when nothing is close.

    The one place a "did you mean" suggestion is computed, so env-name and flag-name
    suggestions behave identically (E014-S01-009, E014-S01-008). A thin wrapper over the
    stdlib: `n=1, cutoff=0.6` are `difflib`'s own default cutoff and the single best match.
    """
    matches = difflib.get_close_matches(candidate, list(options), n=1, cutoff=0.6)
    return matches[0] if matches else None
