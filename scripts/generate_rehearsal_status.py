#!/usr/bin/env python3
"""Generate the Lane 3 status document. Never hand-maintain it.

The 2026-08-29 document opened with "14 of 16 items CLOSED" while its own table
recorded four `partial` and one `n/a`. Both halves were written by hand into one
file, so nothing could catch the contradiction.

Now the document is DERIVED. With a receipt it renders the receipt; without one
it renders the declared pre-execution baseline through the same item list and
the same tally. `--check` fails if the committed file has drifted, which is what
makes "generated" enforceable rather than aspirational.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

sys.path.insert(
    0,
    str(
        pathlib.Path(__file__).resolve().parents[1]
        / "packages"
        / "dotmac-deployment-foundation"
        / "src"
    ),
)

from dotmac_deployment_foundation.rehearsal import (
    REHEARSAL_RECEIPT_SCHEMA,
    RehearsalReceiptV1,
    RehearsalReceiptV2,
    RequirementStatus,
    render_pending_document,
    render_status_document,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = _ROOT / "docs/inventories/deployment-exposure-rehearsal-baseline.json"
OUTPUT = _ROOT / "docs/inventories/deployment-exposure-rehearsal-status.md"


def render(receipt_path: str | None) -> str:
    if receipt_path:
        payload = pathlib.Path(receipt_path).read_text(encoding="utf-8")
        # Each schema's own reader, chosen by the declared schema: a v1 document
        # renders as history, and neither reader interprets the other's fields.
        if json.loads(payload).get("schema") == REHEARSAL_RECEIPT_SCHEMA:
            return render_status_document(RehearsalReceiptV1.from_json(payload))
        return render_status_document(RehearsalReceiptV2.from_json(payload))
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    rows = {
        code: (RequirementStatus(row["status"]), row["detail"])
        for code, row in baseline["items"].items()
    }
    return render_pending_document(rows, reason=baseline["reason"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="generate_rehearsal_status.py")
    parser.add_argument(
        "--receipt", default="", help="a RehearsalReceipt.v2 (v1 renders as history)"
    )
    parser.add_argument(
        "--check", action="store_true", help="fail if the committed file drifted"
    )
    args = parser.parse_args(argv)

    document = render(args.receipt or None)
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != document:
            print(
                f"REFUSED: {OUTPUT} is stale. It is GENERATED — regenerate it "
                "with `python scripts/generate_rehearsal_status.py` rather than "
                "editing it, which is how its header came to contradict its own "
                "table.",
                file=sys.stderr,
            )
            return 1
        print(f"{OUTPUT} is current")
        return 0
    OUTPUT.write_text(document, encoding="utf-8")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
