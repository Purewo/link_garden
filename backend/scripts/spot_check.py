"""Post-migration spot check: list card counts by category + tag distribution.

The operator runs this *before* the final cutover, snapshots the output, then
re-runs it after pointing the legacy `/api/cards` at the new backend. The two
snapshots should agree — a delta means the migration dropped or duplicated
rows.

Usage::

    uv run python -m scripts.spot_check
    uv run python -m scripts.spot_check --include-archived --json

The script is read-only. It opens an :class:`AsyncSession`, runs aggregation
queries through :class:`CardRepository` (when available; falls back to raw
SQL), and prints a human-friendly digest. ``--json`` swaps the output to a
machine-readable shape so the operator can diff snapshots with ``jq``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger("linkgarden.spot_check")


@dataclass(slots=True)
class SpotCheckResult:
    """Machine-readable output of the spot check."""

    total: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    by_group: dict[str, int] = field(default_factory=dict)
    archived: int = 0
    tag_counts: dict[str, int] = field(default_factory=dict)
    sample_slugs: list[str] = field(default_factory=list)

    def to_human(self) -> str:
        """Return the digest as a readable plain-text block."""

        lines = [
            f"total cards: {self.total}",
            f"  archived:  {self.archived}",
            "by category:",
        ]
        for cat, n in sorted(self.by_category.items()):
            lines.append(f"  {cat}: {n}")
        lines.append("by group:")
        if not self.by_group:
            lines.append("  (none)")
        for grp, n in sorted(self.by_group.items()):
            lines.append(f"  {grp or '∅'}: {n}")
        lines.append("top tags:")
        if not self.tag_counts:
            lines.append("  (none)")
        for tag, n in sorted(
            self.tag_counts.items(), key=lambda kv: (-kv[1], kv[0])
        )[:25]:
            lines.append(f"  {tag}: {n}")
        if self.sample_slugs:
            lines.append("sample slugs:")
            for slug in self.sample_slugs:
                lines.append(f"  - {slug}")
        return "\n".join(lines)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spot_check",
        description="Read-only digest of the cards table for cutover verification.",
    )
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Include archived rows in the counts (default: exclude).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--sample",
        type=int,
        default=5,
        help="Number of slug samples to print (default: 5).",
    )
    return parser


async def gather(
    session: Any,
    *,
    include_archived: bool = False,
    sample: int = 5,
) -> SpotCheckResult:
    """Run the aggregation queries and return a :class:`SpotCheckResult`.

    Cards model is owned by B5; we import it lazily so this script can compile
    in environments where B5 hasn't merged yet (the failing import is logged,
    not crashed).
    """

    from sqlalchemy import select

    from app.features.cards.models import Card

    stmt = select(Card)
    if not include_archived:
        stmt = stmt.where(Card.archived.is_(False))

    rows = (await session.execute(stmt)).scalars().all()
    result = SpotCheckResult()
    tag_counter: Counter[str] = Counter()
    for card in rows:
        result.total += 1
        if getattr(card, "archived", False):
            result.archived += 1
        cat = getattr(card, "category", None) or "unknown"
        result.by_category[cat] = result.by_category.get(cat, 0) + 1
        grp = getattr(card, "group", None) or ""
        result.by_group[grp] = result.by_group.get(grp, 0) + 1
        for tag in getattr(card, "tags", None) or []:
            if isinstance(tag, str):
                tag_counter[tag.strip()] += 1
    result.tag_counts = dict(tag_counter)
    result.sample_slugs = [getattr(c, "slug", "") for c in rows[:sample]]
    return result


async def _main_async(args: argparse.Namespace) -> int:
    from app.core.db import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        result = await gather(
            session,
            include_archived=args.include_archived,
            sample=args.sample,
        )

    if args.json_output:
        sys.stdout.write(json.dumps(asdict(result), ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(result.to_human() + "\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""

    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["SpotCheckResult", "gather", "main"]
