from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite, sqrt
from threading import RLock
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.services.elexon_client import ElexonApiError, ElexonClient

UTC = timezone.utc
LONDON = ZoneInfo("Europe/London")
FORECAST_LOOKBACK = timedelta(hours=48)
FORECAST_UNIT_CONFIRMED = True
INTERVAL_ALIGNMENT_CONFIRMED = False
COMPATIBILITY_LIMITATION = (
    "Elexon's Wind Generation product labels its forecast in MW and describes "
    "an hourly forecast, but the WINDFOR stream does not define whether each "
    "timestamped MW value is an hourly average or another hourly measure. "
    "Actuals are averaged from two half-hour average-MW records; the time "
    "basis is not yet verified as like-for-like, so accuracy metrics remain "
    "withheld."
)


class DataValidationError(Exception):
    """Raised when an upstream payload cannot be safely interpreted."""


@dataclass(frozen=True)
class ActualRecord:
    start_time: datetime
    generation_mw: float
    settlement_date: date | None = None


@dataclass(frozen=True)
class ForecastRecord:
    publish_time: datetime
    start_time: datetime
    generation: float


@dataclass(frozen=True)
class MetricValues:
    mae: float | None
    rmse: float | None
    bias: float | None
    wape: float | None
    observation_count: int


@dataclass(frozen=True)
class Analysis:
    decision_date: date
    delivery_date: date
    cutoff_at: datetime
    expected_intervals: int
    forecast: list[ForecastRecord]
    actual: dict[datetime, float]
    comparison: list[dict[str, Any]]
    expected_actual_half_hours: int
    actual_half_hours: int
    missing_actual_hours: list[datetime]
    missing_forecast_hours: list[datetime]
    actual_duplicates_removed: int
    forecast_duplicates_removed: int
    actual_wind_records_retrieved: int
    forecast_records_retrieved: int
    actual_non_wind_records_filtered: int
    publication_count: int
    metrics: MetricValues

    @property
    def aligned_count(self) -> int:
        return sum(row["forecast_generation"] is not None and row["actual_generation_mw"] is not None for row in self.comparison)


def _required_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise DataValidationError(f"Upstream field {field!r} must be an ISO timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise DataValidationError(f"Upstream field {field!r} is not a valid ISO timestamp.") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DataValidationError(f"Upstream timestamp {field!r} must include a timezone.")
    return parsed.astimezone(UTC)


def _required_generation(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DataValidationError(f"Upstream field {field!r} must be numeric.")
    generation = float(value)
    if not isfinite(generation):
        raise DataValidationError(f"Upstream field {field!r} must be finite.")
    return generation


def _parse_rows(payload: Any, dataset: str) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise DataValidationError(f"{dataset} response must be a JSON array.")
    if any(not isinstance(row, dict) for row in payload):
        raise DataValidationError(f"{dataset} response contains a non-object record.")
    return payload


def parse_actuals(payload: Any) -> tuple[list[ActualRecord], int, int]:
    rows = _parse_rows(payload, "FUELHH")
    records: dict[datetime, ActualRecord] = {}
    duplicates_removed = 0
    filtered_non_wind = 0
    for row in rows:
        if row.get("dataset") != "FUELHH":
            raise DataValidationError("FUELHH response record has an unexpected dataset value.")
        if "fuelType" not in row:
            raise DataValidationError("FUELHH record is missing fuelType.")
        if "settlementDate" not in row or "settlementPeriod" not in row:
            raise DataValidationError(
                "FUELHH record is missing settlementDate or settlementPeriod."
            )
        if not isinstance(row["settlementDate"], str):
            raise DataValidationError("FUELHH settlementDate must be a yyyy-MM-dd string.")
        try:
            parsed_settlement_date = date.fromisoformat(row["settlementDate"])
        except ValueError as error:
            raise DataValidationError(
                "FUELHH settlementDate must be a yyyy-MM-dd string."
            ) from error
        if parsed_settlement_date.isoformat() != row["settlementDate"]:
            raise DataValidationError("FUELHH settlementDate must be a yyyy-MM-dd string.")
        if (
            isinstance(row["settlementPeriod"], bool)
            or not isinstance(row["settlementPeriod"], int)
            or row["settlementPeriod"] < 1
        ):
            raise DataValidationError("FUELHH settlementPeriod must be a positive integer.")
        fuel_type = row.get("fuelType")
        if fuel_type != "WIND":
            filtered_non_wind += 1
            continue
        if "startTime" not in row or "generation" not in row:
            raise DataValidationError("FUELHH WIND record is missing startTime or generation.")
        record = ActualRecord(
            start_time=_required_timestamp(row["startTime"], "startTime"),
            generation_mw=_required_generation(row["generation"], "generation"),
            settlement_date=parsed_settlement_date,
        )
        existing = records.get(record.start_time)
        if existing is not None:
            if existing != record:
                raise DataValidationError(
                    f"Conflicting FUELHH WIND records share startTime {record.start_time.isoformat()}."
                )
            duplicates_removed += 1
        else:
            records[record.start_time] = record
    return sorted(records.values(), key=lambda item: item.start_time), duplicates_removed, filtered_non_wind


def parse_forecasts(payload: Any) -> tuple[list[ForecastRecord], int]:
    rows = _parse_rows(payload, "WINDFOR")
    records: dict[tuple[datetime, datetime], ForecastRecord] = {}
    duplicates_removed = 0
    for row in rows:
        if row.get("dataset") != "WINDFOR":
            raise DataValidationError("WINDFOR response record has an unexpected dataset value.")
        if "publishTime" not in row or "startTime" not in row or "generation" not in row:
            raise DataValidationError(
                "WINDFOR record is missing publishTime, startTime, or generation."
            )
        record = ForecastRecord(
            publish_time=_required_timestamp(row["publishTime"], "publishTime"),
            start_time=_required_timestamp(row["startTime"], "startTime"),
            generation=_required_generation(row["generation"], "generation"),
        )
        key = (record.publish_time, record.start_time)
        existing = records.get(key)
        if existing is not None:
            if existing != record:
                raise DataValidationError(
                    "Conflicting WINDFOR records share publishTime and startTime."
                )
            duplicates_removed += 1
        else:
            records[key] = record
    return sorted(records.values(), key=lambda item: (item.publish_time, item.start_time)), duplicates_removed


def calculate_metrics(
    forecast_values: Iterable[float], actual_values: Iterable[float]
) -> MetricValues:
    forecasts = np.asarray(list(forecast_values), dtype=float)
    actuals = np.asarray(list(actual_values), dtype=float)
    if forecasts.ndim != 1 or actuals.ndim != 1 or forecasts.size != actuals.size:
        raise ValueError("Forecast and actual values must be equally sized one-dimensional sequences.")
    if not np.isfinite(forecasts).all() or not np.isfinite(actuals).all():
        raise ValueError("Metric inputs must contain only finite numbers.")
    count = int(forecasts.size)
    if not count:
        return MetricValues(None, None, None, None, 0)
    errors = forecasts - actuals
    denominator = float(np.abs(actuals).sum())
    wape = float(np.abs(errors).sum() / denominator * 100) if denominator else None
    return MetricValues(
        mae=float(np.abs(errors).mean()),
        rmse=float(sqrt(float(np.square(errors).mean()))),
        bias=float(errors.mean()),
        wape=wape,
        observation_count=count,
    )


def aggregate_actuals_hourly(
    records: list[ActualRecord],
    delivery_date: date,
    expected_hours: list[datetime],
) -> tuple[dict[datetime, float], list[datetime], int]:
    frame = pd.DataFrame(
        [
            {"start_time": record.start_time, "generation_mw": record.generation_mw}
            for record in records
        ],
        columns=["start_time", "generation_mw"],
    )
    if frame.empty:
        hourly: dict[datetime, float] = {}
        observed_count = 0
    else:
        frame["hour_start"] = pd.to_datetime(frame["start_time"], utc=True).dt.floor("h")
        grouped = frame.groupby("hour_start")["generation_mw"].agg(["mean", "count"])
        valid_actual_starts = {record.start_time for record in records}
        hourly = {}
        for expected_hour in expected_hours:
            second_half = expected_hour + timedelta(minutes=30)
            if expected_hour in valid_actual_starts and second_half in valid_actual_starts:
                aggregate = grouped.loc[pd.Timestamp(expected_hour)]
                if int(aggregate["count"]) == 2:
                    hourly[expected_hour] = float(aggregate["mean"])
        observed_count = len(records)
    missing = [hour for hour in expected_hours if hour not in hourly]
    return hourly, missing, observed_count


def _delivery_hours(delivery_date: date) -> list[datetime]:
    local_start = datetime.combine(delivery_date, time.min, tzinfo=LONDON)
    local_end = datetime.combine(delivery_date + timedelta(days=1), time.min, tzinfo=LONDON)
    start = local_start.astimezone(UTC)
    end = local_end.astimezone(UTC)
    hours: list[datetime] = []
    current = start
    while current < end:
        hours.append(current)
        current += timedelta(hours=1)
    return hours


class AnalyticsService:
    def __init__(self, client: ElexonClient | None = None) -> None:
        self.client = client or ElexonClient()
        self._cache: dict[tuple[date, time], tuple[datetime, Analysis]] = {}
        self._lock = RLock()

    def analyze(self, decision_date: date, cutoff_time: time) -> Analysis:
        if decision_date.year != 2026 or decision_date.month != 1:
            raise ValueError("decision_date must be within January 2026.")
        if cutoff_time.tzinfo is not None:
            raise ValueError("cutoff_time must be a local Europe/London clock time without an offset.")

        key = (decision_date, cutoff_time)
        now = datetime.now(UTC)
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > now:
                return cached[1]

        local_cutoff = datetime.combine(decision_date, cutoff_time, tzinfo=LONDON)
        cutoff_at = local_cutoff.astimezone(UTC)
        delivery_date = decision_date + timedelta(days=1)
        expected_hours = _delivery_hours(delivery_date)
        expected_first = expected_hours[0]
        expected_end = expected_hours[-1] + timedelta(hours=1)
        publication_from = cutoff_at - FORECAST_LOOKBACK

        actual_payload = self.client.get_actuals(delivery_date)
        forecast_payload = self.client.get_forecasts(publication_from, cutoff_at)
        actual_records, actual_duplicates, filtered_non_wind = parse_actuals(actual_payload)
        forecast_records, forecast_duplicates = parse_forecasts(forecast_payload)
        actual_wind_records_retrieved = len(actual_records) + actual_duplicates

        for record in actual_records:
            if (
                record.settlement_date != delivery_date
                or record.start_time.astimezone(LONDON).date() != delivery_date
            ):
                raise DataValidationError(
                    "FUELHH returned a WIND record outside the requested delivery date."
                )
        actual_hourly, missing_actual_hours, observed_half_hours = aggregate_actuals_hourly(
            actual_records, delivery_date, expected_hours
        )

        eligible_by_hour: dict[datetime, ForecastRecord] = {}
        publication_times: set[datetime] = set()
        for record in forecast_records:
            if publication_from <= record.publish_time <= cutoff_at:
                publication_times.add(record.publish_time)
            if (
                publication_from <= record.publish_time
                and record.publish_time <= cutoff_at
                and expected_first <= record.start_time < expected_end
                and record.start_time.minute == 0
                and record.start_time.second == 0
            ):
                current = eligible_by_hour.get(record.start_time)
                if current is None or record.publish_time > current.publish_time:
                    eligible_by_hour[record.start_time] = record

        selected_forecasts = [
            eligible_by_hour[hour] for hour in expected_hours if hour in eligible_by_hour
        ]
        missing_forecast_hours = [
            hour for hour in expected_hours if hour not in eligible_by_hour
        ]
        comparison = [
            {
                "delivery_start": hour,
                "forecast_generation": (
                    eligible_by_hour[hour].generation if hour in eligible_by_hour else None
                ),
                "forecast_published_at": (
                    eligible_by_hour[hour].publish_time if hour in eligible_by_hour else None
                ),
                "actual_generation_mw": actual_hourly.get(hour),
            }
            for hour in expected_hours
        ]
        paired_forecasts = [
            row["forecast_generation"]
            for row in comparison
            if row["forecast_generation"] is not None and row["actual_generation_mw"] is not None
        ]
        paired_actuals = [
            row["actual_generation_mw"]
            for row in comparison
            if row["forecast_generation"] is not None and row["actual_generation_mw"] is not None
        ]
        metrics = calculate_metrics(paired_forecasts, paired_actuals)
        result = Analysis(
            decision_date=decision_date,
            delivery_date=delivery_date,
            cutoff_at=cutoff_at,
            expected_intervals=len(expected_hours),
            forecast=selected_forecasts,
            actual=actual_hourly,
            comparison=comparison,
            expected_actual_half_hours=len(expected_hours) * 2,
            actual_half_hours=observed_half_hours,
            missing_actual_hours=missing_actual_hours,
            missing_forecast_hours=missing_forecast_hours,
            actual_duplicates_removed=actual_duplicates,
            forecast_duplicates_removed=forecast_duplicates,
            actual_wind_records_retrieved=actual_wind_records_retrieved,
            forecast_records_retrieved=len(forecast_records) + forecast_duplicates,
            actual_non_wind_records_filtered=filtered_non_wind,
            publication_count=len(publication_times),
            metrics=metrics,
        )
        with self._lock:
            self._cache[key] = (now + timedelta(minutes=5), result)
        return result

    def get_forecast(self, decision_date: date, cutoff_time: time) -> Analysis:
        return self.analyze(decision_date, cutoff_time)

    def get_comparison(self, decision_date: date, cutoff_time: time) -> Analysis:
        return self.analyze(decision_date, cutoff_time)

    def get_metrics(self, decision_date: date, cutoff_time: time) -> Analysis:
        return self.analyze(decision_date, cutoff_time)
