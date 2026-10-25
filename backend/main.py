
"""UK Wind Forecast Portal API.

Sources:
- Elexon BMRS FUELHH: actual generation, fuelType=WIND
- Elexon BMRS WINDFOR: wind generation forecasts

Delivery period: January 2026.
Decision rule: latest forecast published by 09:00 UK time on D-1.
The 09:00 cutoff is an assumption and should be confirmed against the brief.
"""

import datetime as dt
import time
from functools import lru_cache
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query

BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1/datasets"
MARKET_TZ = ZoneInfo("Europe/London")

DELIVERY_START = pd.Timestamp("2026-01-01", tz=MARKET_TZ)
DELIVERY_END = pd.Timestamp("2026-02-01", tz=MARKET_TZ)

CUTOFF_HOUR = 9
CUTOFF_MINUTE = 0
EXPECTED_INTERVALS_PER_DAY = 48

app = FastAPI(
    title="UK Wind Forecast Portal",
    description=(
        "Historical UK wind forecast selection and accuracy analysis "
        "for January 2026."
    ),
    version="1.1.0",
)


# ---------------------------------------------------------
# API REQUESTS
# ---------------------------------------------------------

def fetch_stream(dataset: str, params: dict) -> list[dict]:
    """Request Elexon records, with limited retries."""
    url = f"{BASE_URL}/{dataset}/stream"
    last_error = None

    for attempt in range(3):
        try:
            with httpx.Client(
                timeout=httpx.Timeout(90.0, connect=15.0),
                follow_redirects=True,
            ) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()

            if isinstance(payload, list):
                return payload

            if isinstance(payload, dict):
                for key in ("data", "results", "result"):
                    if isinstance(payload.get(key), list):
                        return payload[key]

            raise ValueError(
                f"Unexpected {dataset} response format: "
                f"{type(payload).__name__}"
            )

        except (httpx.HTTPError, ValueError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(
        f"Elexon {dataset} request failed after 3 attempts: {last_error}"
    )


def normalize_datetime(series: pd.Series) -> pd.Series:
    """Convert timestamp values to UTC."""
    return pd.to_datetime(series, errors="coerce", utc=True)


def normalize_generation(frame: pd.DataFrame) -> pd.DataFrame:
    """Validate timestamps and numeric generation values."""
    if frame.empty or "startTime" not in frame.columns:
        return pd.DataFrame(columns=["startTime", "generation"])

    result = frame.copy()
    result["startTime"] = normalize_datetime(result["startTime"])

    if "generation" not in result.columns:
        result["generation"] = np.nan

    result["generation"] = pd.to_numeric(
        result["generation"], errors="coerce"
    )

    result = result.dropna(subset=["startTime", "generation"])
    result = result[np.isfinite(result["generation"])]

    return result


def january_delivery_rows(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep records whose delivery timestamp falls in January UK time."""
    if frame.empty:
        return frame.copy()

    local = frame["startTime"].dt.tz_convert(MARKET_TZ)

    return frame.loc[
        (local >= DELIVERY_START) & (local < DELIVERY_END)
    ].copy()


# ---------------------------------------------------------
# ACTUAL WIND GENERATION
# ---------------------------------------------------------

@lru_cache(maxsize=1)
def load_actuals() -> pd.DataFrame:
    """Load FUELHH actual generation for wind during January 2026."""
    records = fetch_stream(
        "FUELHH",
        {
            "settlementDateFrom": "2026-01-01",
            "settlementDateTo": "2026-01-31",
            "fuelType": "WIND",
        },
    )

    actuals = normalize_generation(pd.DataFrame(records))

    if actuals.empty:
        return pd.DataFrame(columns=["startTime", "actual"])

    actuals = january_delivery_rows(actuals)

    # Do not convert half-hourly timestamps into hourly timestamps.
    # Keep the original timestamp and remove only exact duplicates.
    actuals = (
        actuals.sort_values("startTime")
        .drop_duplicates(subset=["startTime"], keep="last")
        .rename(columns={"generation": "actual"})
    )

    return actuals[["startTime", "actual"]].reset_index(drop=True)


# ---------------------------------------------------------
# FORECASTS
# ---------------------------------------------------------

@lru_cache(maxsize=1)
def load_forecasts() -> pd.DataFrame:
    """Load forecast publications and select the latest eligible forecast."""
    chunks = []

    # Include publications before January because 1 January's D-1
    # decision cutoff occurs in December 2025.
    current = dt.datetime(
        2025, 12, 29, tzinfo=dt.timezone.utc
    )
    end = dt.datetime(
        2026, 2, 1, tzinfo=dt.timezone.utc
    )

    while current < end:
        chunk_end = min(
            current + dt.timedelta(days=3),
            end,
        )

        records = fetch_stream(
            "WINDFOR",
            {
                "publishDateTimeFrom": current.strftime(
                    "%Y-%m-%dT%H:%MZ"
                ),
                "publishDateTimeTo": chunk_end.strftime(
                    "%Y-%m-%dT%H:%MZ"
                ),
            },
        )

        if records:
            chunks.append(pd.DataFrame(records))

        current = chunk_end

    if not chunks:
        return pd.DataFrame(
            columns=["startTime", "publishTime", "forecast"]
        )

    forecasts = pd.concat(chunks, ignore_index=True)

    required = {"startTime", "publishTime", "generation"}
    missing = required - set(forecasts.columns)

    if missing:
        raise RuntimeError(
            "WINDFOR is missing required fields: "
            + ", ".join(sorted(missing))
        )

    forecasts["startTime"] = normalize_datetime(
        forecasts["startTime"]
    )
    forecasts["publishTime"] = normalize_datetime(
        forecasts["publishTime"]
    )
    forecasts["generation"] = pd.to_numeric(
        forecasts["generation"], errors="coerce"
    )

    forecasts = forecasts.dropna(
        subset=["startTime", "publishTime", "generation"]
    )
    forecasts = forecasts[
        np.isfinite(forecasts["generation"])
    ].copy()

    # Remove exact duplicate observations caused by overlapping requests.
    forecasts = forecasts.drop_duplicates(
        subset=["startTime", "publishTime", "generation"]
    )

    forecasts = january_delivery_rows(forecasts)

    if forecasts.empty:
        return pd.DataFrame(
            columns=["startTime", "publishTime", "forecast"]
        )

    # Derive the cutoff independently for each delivery date.
    local_delivery = forecasts["startTime"].dt.tz_convert(MARKET_TZ)
    delivery_days = local_delivery.dt.date

    cutoffs = []
    for delivery_day in delivery_days:
        cutoff_local = (
            pd.Timestamp(delivery_day, tz=MARKET_TZ)
            - pd.Timedelta(days=1)
            + pd.Timedelta(
                hours=CUTOFF_HOUR,
                minutes=CUTOFF_MINUTE,
            )
        )
        cutoffs.append(cutoff_local.tz_convert("UTC"))

    forecasts["cutoffTime"] = cutoffs

    # Do not use a forecast published after the decision cutoff.
    eligible = forecasts.loc[
        forecasts["publishTime"] <= forecasts["cutoffTime"]
    ].copy()

    if eligible.empty:
        return pd.DataFrame(
            columns=["startTime", "publishTime", "forecast"]
        )

    # For every target timestamp, select the latest eligible publication.
    eligible = eligible.sort_values(
        ["startTime", "publishTime"]
    )

    selected = eligible.drop_duplicates(
        subset=["startTime"],
        keep="last",
    )

    selected = selected.rename(
        columns={"generation": "forecast"}
    )

    return selected[
        ["startTime", "publishTime", "forecast"]
    ].reset_index(drop=True)


# ---------------------------------------------------------
# JOIN AND METRICS
# ---------------------------------------------------------

@lru_cache(maxsize=1)
def load_data() -> pd.DataFrame:
    """Join selected forecasts to actuals on exact delivery timestamps."""
    actuals = load_actuals()
    forecasts = load_forecasts()

    if forecasts.empty:
        raise RuntimeError(
            "No eligible January 2026 WINDFOR forecasts were returned."
        )

    # Keep only timestamps for which a forecast was selected.
    # Missing actuals remain NaN and are excluded from accuracy metrics.
    data = forecasts.merge(
        actuals,
        on="startTime",
        how="left",
        validate="one_to_one",
    )

    data = data.sort_values("startTime").reset_index(drop=True)
    data["error"] = data["forecast"] - data["actual"]

    data["horizon_h"] = (
        data["startTime"] - data["publishTime"]
    ).dt.total_seconds() / 3600

    return data


def get_data() -> pd.DataFrame:
    try:
        return load_data()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Unable to load forecast data from Elexon. "
                "Check the backend logs and retry."
            ),
        ) from exc


def calculate_metrics(frame: pd.DataFrame) -> dict:
    """Calculate metrics from matched forecasts and actuals only."""
    empty_result = {
        "n": 0,
        "mae": None,
        "rmse": None,
        "bias": None,
        "mape_pct": None,
        "p90_overforecast": None,
        "p90_underforecast": None,
    }

    if frame.empty:
        return empty_result

    valid = frame.dropna(
        subset=["forecast", "actual"]
    ).copy()

    if valid.empty:
        return empty_result

    error = valid["forecast"] - valid["actual"]
    abs_error = error.abs()

    nonzero_actuals = valid["actual"].abs() > 0

    if nonzero_actuals.any():
        mape = (
            abs_error[nonzero_actuals]
            / valid.loc[nonzero_actuals, "actual"].abs()
        ).mean() * 100
        mape_value = float(mape)
    else:
        mape_value = None

    over_errors = error[error > 0]
    under_errors = -error[error < 0]

    return {
        "n": int(len(valid)),
        "mae": float(abs_error.mean()),
        "rmse": float(np.sqrt((error ** 2).mean())),
        "bias": float(error.mean()),
        "mape_pct": mape_value,
        "p90_overforecast": (
            float(over_errors.quantile(0.90))
            if not over_errors.empty
            else 0.0
        ),
        "p90_underforecast": (
            float(under_errors.quantile(0.90))
            if not under_errors.empty
            else 0.0
        ),
    }


# ---------------------------------------------------------
# HEALTH AND CONFIGURATION
# ---------------------------------------------------------

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "wind-forecast-portal",
    }


@app.get("/api/status")
def status():
    return {
        "delivery_period": "2026-01",
        "timezone": "Europe/London",
        "cutoff": (
            f"D-1 {CUTOFF_HOUR:02d}:{CUTOFF_MINUTE:02d} "
            "Europe/London"
        ),
        "cutoff_is_assumption": True,
        "data_source": "Elexon BMRS FUELHH and WINDFOR",
        "expected_intervals_per_full_day": EXPECTED_INTERVALS_PER_DAY,
    }


# ---------------------------------------------------------
# DATA COVERAGE DIAGNOSTIC
# ---------------------------------------------------------

@app.get("/api/debug/coverage")
def debug_coverage(
    date: str = Query("2026-01-12", description="Date YYYY-MM-DD")
):
    """Compare raw actual and selected forecast timestamp coverage."""
    try:
        requested_day = dt.date.fromisoformat(date)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid date. Use YYYY-MM-DD.",
        ) from exc

    if not dt.date(2026, 1, 1) <= requested_day <= dt.date(2026, 1, 31):
        raise HTTPException(
            status_code=400,
            detail="Date must be within January 2026.",
        )

    try:
        actuals = load_actuals()
        forecasts = load_forecasts()
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="Could not load source data from Elexon.",
        ) from exc

    def inspect(frame: pd.DataFrame, timestamp_col: str) -> dict:
        if frame.empty:
            return {
                "count": 0,
                "hour_start_count": 0,
                "half_hour_start_count": 0,
                "unique_timestamp_count": 0,
                "sample_times": [],
            }

        local = frame[timestamp_col].dt.tz_convert(MARKET_TZ)
        subset = frame.loc[local.dt.date == requested_day].copy()
        times = subset[timestamp_col].dt.tz_convert(MARKET_TZ)

        return {
            "count": int(len(subset)),
            "hour_start_count": int((times.dt.minute == 0).sum()),
            "half_hour_start_count": int((times.dt.minute == 30).sum()),
            "unique_timestamp_count": int(times.nunique()),
            "sample_times": [
                timestamp.isoformat()
                for timestamp in times.sort_values().head(12)
            ],
        }

    actual_report = inspect(actuals, "startTime")
    forecast_report = inspect(forecasts, "startTime")

    actual_times = set(
        actuals.loc[
            actuals["startTime"].dt.tz_convert(MARKET_TZ).dt.date
            == requested_day,
            "startTime",
        ]
    )
    forecast_times = set(
        forecasts.loc[
            forecasts["startTime"].dt.tz_convert(MARKET_TZ).dt.date
            == requested_day,
            "startTime",
        ]
    )

    return {
        "date": date,
        "timezone": "Europe/London",
        "expected_intervals_per_full_day": EXPECTED_INTERVALS_PER_DAY,
        "actuals": actual_report,
        "selected_forecasts": forecast_report,
        "matching_timestamps": len(actual_times & forecast_times),
        "actual_only_timestamps": len(actual_times - forecast_times),
        "forecast_only_timestamps": len(forecast_times - actual_times),
        "note": (
            "This endpoint reports the source records as returned. "
            "It does not create or interpolate missing intervals."
        ),
    }


# ---------------------------------------------------------
# DAILY VIEW
# ---------------------------------------------------------

@app.get("/api/day")
def day(
    date: str = Query(..., description="Delivery date YYYY-MM-DD")
):
    try:
        requested_day = dt.date.fromisoformat(date)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="Invalid date. Use YYYY-MM-DD.",
        ) from exc

    if not dt.date(2026, 1, 1) <= requested_day <= dt.date(2026, 1, 31):
        raise HTTPException(
            status_code=400,
            detail="Delivery date must be within January 2026.",
        )

    data = get_data()

    local_times = data["startTime"].dt.tz_convert(MARKET_TZ)
    selected = data.loc[
        local_times.dt.date == requested_day
    ].copy()

    if selected.empty:
        raise HTTPException(
            status_code=404,
            detail="No eligible forecast rows found for this date.",
        )

    cutoff_local = (
        pd.Timestamp(requested_day, tz=MARKET_TZ)
        - pd.Timedelta(days=1)
        + pd.Timedelta(
            hours=CUTOFF_HOUR,
            minutes=CUTOFF_MINUTE,
        )
    )

    metrics = calculate_metrics(selected)
    overall_metrics = calculate_metrics(data)

    actuals = load_actuals()
    local_actual_times = actuals["startTime"].dt.tz_convert(MARKET_TZ)
    actual_day = actuals.loc[
        local_actual_times.dt.date == requested_day
    ]

    rows = []
    for row in selected.itertuples():
        rows.append({
            "t": row.startTime.isoformat(),
            "forecast": float(row.forecast),
            "actual": (
                float(row.actual)
                if pd.notna(row.actual)
                else None
            ),
            "published": row.publishTime.isoformat(),
            "error": (
                float(row.error)
                if pd.notna(row.actual)
                else None
            ),
        })

    buffer = overall_metrics["p90_overforecast"]

    return {
        "date": date,
        "decision_cutoff": cutoff_local.isoformat(),
        "timezone": "Europe/London",
        "latest_publish": (
            selected["publishTime"].max().isoformat()
            if not selected.empty
            else None
        ),
        "coverage": {
            "actual_intervals": int(len(actual_day)),
            "selected_forecast_intervals": int(len(selected)),
            "matched_intervals": int(
                selected["actual"].notna().sum()
            ),
            "expected_intervals": EXPECTED_INTERVALS_PER_DAY,
        },
        "day_metrics": metrics,
        "suggested_buffer_mw": (
            max(0.0, buffer) if buffer is not None else None
        ),
        "rows": rows,
    }


# ---------------------------------------------------------
# MONTHLY ACCURACY
# ---------------------------------------------------------

@app.get("/api/accuracy")
def accuracy():
    data = get_data()
    valid = data.dropna(
        subset=["actual", "forecast"]
    ).copy()

    if valid.empty:
        raise HTTPException(
            status_code=404,
            detail="No matched forecast and actual records are available.",
        )

    valid["local_time"] = valid["startTime"].dt.tz_convert(MARKET_TZ)
    valid["day"] = valid["local_time"].dt.strftime("%Y-%m-%d")
    valid["hour"] = valid["local_time"].dt.hour

    daily = [
        {
            "day": str(day_key),
            **calculate_metrics(group),
        }
        for day_key, group in valid.groupby("day")
    ]

    hourly = [
        {
            "hour": int(hour),
            "mae": float(group["error"].abs().mean()),
            "bias": float(group["error"].mean()),
            "n": int(len(group)),
        }
        for hour, group in valid.groupby("hour")
    ]

    bins = [0, 18, 24, 30, 36, 48, 72, 96, 120]
    labels = [
        "0–18h",
        "18–24h",
        "24–30h",
        "30–36h",
        "36–48h",
        "48–72h",
        "72–96h",
        "96–120h",
    ]

    valid["horizon_band"] = pd.cut(
        valid["horizon_h"],
        bins=bins,
        labels=labels,
        include_lowest=True,
    )

    by_horizon = [
        {
            "horizon": str(band),
            "mae": float(group["error"].abs().mean()),
            "n": int(len(group)),
        }
        for band, group in valid.groupby(
            "horizon_band",
            observed=True,
        )
    ]

    return {
        "overall": calculate_metrics(valid),
        "daily": daily,
        "hourly": hourly,
        "by_horizon": by_horizon,
    }
