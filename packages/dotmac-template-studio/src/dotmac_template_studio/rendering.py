"""Single-brace template substitution, independent of Template Studio wiring.

Importing this module does not assemble the module's routes, web surface,
database models, or feature flags. It is the renderer shared by the service
and callers that only need to substitute already-approved template text.
"""

from __future__ import annotations

import re

# Negative lookarounds leave {{double}} braces untouched. Save-time validation
# in the service rejects that syntax before a template can be published.
_PLACEHOLDER = re.compile(r"(?<!\{)\{\s*([a-z][a-z0-9_]*)\s*\}(?!\})")


class MissingTemplateValueError(ValueError):
    """Strict rendering found a placeholder with no supplied value."""


def render(body: str, values: dict[str, str], *, strict: bool = True) -> str:
    """Substitute `{name}` placeholders with `values` without evaluating text.

    Strict mode refuses a half-substituted result. Preview callers may pass
    ``strict=False`` to leave absent placeholders visible.
    """
    missing: list[str] = []

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in values:
            return values[name]
        missing.append(name)
        return match.group(0)

    rendered = _PLACEHOLDER.sub(_sub, body)
    if strict and missing:
        names = ", ".join(sorted(set(missing)))
        raise MissingTemplateValueError(
            f"missing value(s) for template variable(s): {names}"
        )
    return rendered


__all__ = ["MissingTemplateValueError", "render"]
