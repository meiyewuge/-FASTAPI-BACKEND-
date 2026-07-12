"""Dynamic Date Range Template — Phase2 V1.2."""
from __future__ import annotations
from datetime import date, timedelta
from typing import Optional

class DateRangeError(ValueError):
    """Invalid date range parameters."""
    pass

def compute_date_range(
    run_date: Optional[str | date] = None,
    lookback_days: int = 6,
) -> tuple[date, date]:
    if lookback_days < 0:
        raise DateRangeError(f"lookback_days must be >= 0, got {lookback_days}")
    if run_date is None:
        rd = date.today()
    elif isinstance(run_date, date):
        rd = run_date
    elif isinstance(run_date, str):
        try:
            rd = date.fromisoformat(run_date)
        except (ValueError, TypeError) as e:
            raise DateRangeError(f"Invalid run_date format: {run_date!r}. Expected YYYY-MM-DD.") from e
    else:
        raise DateRangeError(f"Invalid run_date type: {type(run_date).__name__}")
    end_date = rd
    start_date = rd - timedelta(days=lookback_days)
    return start_date, end_date

def format_date_range(start_date: date, end_date: date) -> str:
    return f"{start_date.isoformat()}~{end_date.isoformat()}"

def expand_query_template(
    template: str,
    run_date: Optional[str | date] = None,
    lookback_days: int = 6,
) -> str:
    start_date, end_date = compute_date_range(run_date, lookback_days)
    rd = end_date
    return template.replace("{run_date}", rd.isoformat()) \
                   .replace("{start_date}", start_date.isoformat()) \
                   .replace("{end_date}", end_date.isoformat()) \
                   .replace("{date_range}", format_date_range(start_date, end_date))
