"""Pure composition of already-rendered notification email content.

The caller chooses the primary part and declares the order. Template Studio
only assembles content; it does not select templates, group events, decide who
may receive an email, or deliver it. Full rendered bodies are retained, so
greetings or sign-offs repeated by separate templates remain repeated until a
fragment-template contract exists.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RenderedEmailPart:
    """One already-rendered email part and its caller-owned identity/order."""

    part_id: str
    order: int
    subject: str | None
    body: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.part_id, str)
            or not self.part_id
            or self.part_id != self.part_id.strip()
        ):
            raise ValueError("part_id must be a nonblank, unpadded string")
        if (
            isinstance(self.order, bool)
            or not isinstance(self.order, int)
            or self.order < 0
        ):
            raise ValueError("order must be a nonnegative integer")
        if self.subject is not None and not isinstance(self.subject, str):
            raise ValueError("subject must be a string or None")
        if not isinstance(self.body, str) or not self.body.strip():
            raise ValueError("body must be a nonblank string")


@dataclass(frozen=True, slots=True)
class ComposedEmail:
    """Assembled content plus immutable, ordered source-content provenance."""

    primary_part_id: str
    subject: str
    body: str
    parts: tuple[RenderedEmailPart, ...]


def compose_email(
    parts: Sequence[RenderedEmailPart], *, primary_part_id: str
) -> ComposedEmail:
    """Join full rendered bodies in declared order with one blank line.

    The primary part supplies the subject unchanged. The function does not
    inspect, substitute, trim, or rewrite any rendered content.
    """
    if isinstance(parts, str | bytes) or not isinstance(parts, Sequence) or not parts:
        raise ValueError("parts must be a nonempty sequence")
    snapshot = tuple(parts)
    if not isinstance(primary_part_id, str) or not primary_part_id:
        raise ValueError("primary_part_id must identify one part")
    if any(not isinstance(part, RenderedEmailPart) for part in snapshot):
        raise ValueError("every part must be a RenderedEmailPart")

    by_id: dict[str, RenderedEmailPart] = {}
    orders: set[int] = set()
    for part in snapshot:
        if part.part_id in by_id:
            raise ValueError(f"duplicate part_id: {part.part_id}")
        if part.order in orders:
            raise ValueError(f"duplicate order: {part.order}")
        by_id[part.part_id] = part
        orders.add(part.order)

    primary = by_id.get(primary_part_id)
    if primary is None:
        raise ValueError("primary_part_id must identify one part")
    if primary.subject is None or not primary.subject.strip():
        raise ValueError("the primary part must have a nonblank subject")

    ordered = tuple(sorted(snapshot, key=lambda part: part.order))
    return ComposedEmail(
        primary_part_id=primary_part_id,
        subject=primary.subject,
        body="\n\n".join(part.body for part in ordered),
        parts=ordered,
    )


__all__ = ["ComposedEmail", "RenderedEmailPart", "compose_email"]
