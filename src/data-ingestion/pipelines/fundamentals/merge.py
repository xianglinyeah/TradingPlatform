"""Shared helpers for fundamentals_full and fundamentals_incremental.

Extracted to avoid duplication between the two ingestion paths.
"""
from __future__ import annotations

from typing import List

from core.schema import FundTableSpec, TableKind


def merge_batches(target: List[dict], incoming: List[dict], spec: FundTableSpec) -> None:
    """Merge field values from `incoming` into `target` by row key.

    Used when a single API table requires multiple calls (field batches) —
    rows from later batches are merged into matching rows from earlier batches.
    """
    if not incoming:
        return

    by_key = {row_key(r, spec): r for r in target}
    for ir in incoming:
        k = row_key(ir, spec)
        tr = by_key.get(k)
        if tr is None:
            target.append(ir)
            by_key[k] = ir
        else:
            for f in spec.fields:
                if f in ir:
                    tr[f] = ir[f]


def row_key(r: dict, spec: FundTableSpec) -> tuple:
    """Compute the natural key for a fundamentals row.

    Quarterly tables: (symbol, rpt_date[, data_type])
    Daily tables:     (symbol, trade_date)
    """
    sym = r.get("symbol")
    if spec.kind == TableKind.Quarterly:
        rpt = r.get("rpt_date")
        if spec.returns_rpt_type:
            return (sym, rpt, r.get("data_type"))
        return (sym, rpt)
    return (sym, r.get("trade_date"))
