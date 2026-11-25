from __future__ import annotations

import pandas as pd

RATE_MIN = 1e-6
RATE_MAX = 1_000_000.0


def validate_rates(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """
    Validate a freshly-fetched rates DataFrame.

    Checks:
    - rate is not null
    - rate > 0
    - rate is within plausible bounds (RATE_MIN, RATE_MAX)

    Returns (clean_df, issues) where issues is a list of warning strings
    and clean_df has invalid rows removed.
    """
    issues: list[str] = []
    mask_keep = pd.Series(True, index=df.index)

    null_mask = df["rate"].isna()
    if null_mask.any():
        for pair in df.loc[null_mask, "pair"].tolist():
            issues.append(f"{pair}: rate is null — row dropped")
        mask_keep &= ~null_mask

    nonpos_mask = df["rate"] <= 0
    if nonpos_mask.any():
        for _, row in df.loc[nonpos_mask].iterrows():
            issues.append(f"{row['pair']}: rate <= 0 ({row['rate']}) — row dropped")
        mask_keep &= ~nonpos_mask

    implausible_mask = (df["rate"] < RATE_MIN) | (df["rate"] > RATE_MAX)
    if implausible_mask.any():
        for _, row in df.loc[implausible_mask].iterrows():
            issues.append(f"{row['pair']}: rate {row['rate']} out of plausible range — row dropped")
        mask_keep &= ~implausible_mask

    return df[mask_keep].reset_index(drop=True), issues