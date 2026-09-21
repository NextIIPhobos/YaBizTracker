from __future__ import annotations


def visible_range(visible_rows: list[int], anchor_row: int, target_row: int) -> list[int]:
    """Return the inclusive Shift-selection range in visual order.

    Hidden rows are intentionally absent from ``visible_rows``. If the anchor
    is no longer visible after filtering, the target becomes the new anchor.
    """
    if not visible_rows or target_row not in visible_rows:
        return []
    if anchor_row not in visible_rows:
        anchor_row = target_row
    left = visible_rows.index(anchor_row)
    right = visible_rows.index(target_row)
    lo, hi = sorted((left, right))
    return visible_rows[lo : hi + 1]
