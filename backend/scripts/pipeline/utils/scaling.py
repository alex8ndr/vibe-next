from __future__ import annotations

import polars as pl


def minmax_scale_polars(df: pl.LazyFrame, columns: list[str]) -> pl.LazyFrame:
    """Apply min-max scaling in pure Polars expressions."""
    scale_exprs = []
    for col in columns:
        scaled = (
            (pl.col(col) - pl.col(col).min()) /
            (pl.col(col).max() - pl.col(col).min())
        ).fill_nan(0.0).fill_null(0.0).alias(col)
        scale_exprs.append(scaled)

    return df.with_columns(scale_exprs)
