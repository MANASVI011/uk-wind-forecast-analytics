from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"]
    service: str


class ErrorResponse(BaseModel):
    status: Literal["upstream_error", "invalid_upstream_data"]
    dataset: str
    message: str


class ForecastPoint(BaseModel):
    delivery_start: datetime
    published_at: datetime
    generation: float


class ComparisonPoint(BaseModel):
    delivery_start: datetime
    forecast_generation: float | None
    forecast_published_at: datetime | None
    actual_generation_mw: float | None


class AnalysisMetadata(BaseModel):
    decision_date: date
    delivery_date: date
    cutoff_at: datetime
    cutoff_timezone: Literal["Europe/London"] = "Europe/London"
    cutoff_assumption: str
    expected_hourly_intervals: int
    forecast_publications_considered: int
    forecast_publication_lookback_hours: int
    forecast_records_retrieved: int
    actual_wind_records_retrieved: int
    actual_non_wind_records_filtered: int
    forecast_duplicates_removed: int
    actual_duplicates_removed: int
    missing_forecast_intervals: list[datetime]
    missing_actual_intervals: list[datetime]
    forecast_coverage: float
    actual_coverage: float
    aligned_observation_count: int
    alignment_verified: bool = False
    forecast_unit_verified: bool = False
    limitation: str


class ForecastResponse(AnalysisMetadata):
    forecasts: list[ForecastPoint]


class ComparisonResponse(AnalysisMetadata):
    comparison: list[ComparisonPoint]
    actual_half_hour_records: int
    expected_actual_half_hour_records: int
    hourly_actual_aggregation: str
    metrics_available: bool = False


class MetricsResponse(AnalysisMetadata):
    mae_mw: float | None
    rmse_mw: float | None
    mean_bias_mw: float | None
    wape_percent: float | None
    observation_count: int
    metrics_available: bool
