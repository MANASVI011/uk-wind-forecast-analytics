from datetime import date, time

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    AnalysisMetadata,
    ComparisonResponse,
    ErrorResponse,
    ForecastPoint,
    ForecastResponse,
    HealthResponse,
    MetricsResponse,
)
from app.services.analytics_service import (
    COMPATIBILITY_LIMITATION,
    FORECAST_LOOKBACK,
    FORECAST_UNIT_CONFIRMED,
    INTERVAL_ALIGNMENT_CONFIRMED,
    Analysis,
    AnalyticsService,
    DataValidationError,
)
from app.services.elexon_client import ElexonApiError

router = APIRouter(prefix="/api")
analytics_service = AnalyticsService()
CUTOFF_ASSUMPTION = (
    "23:00 Europe/London default is provisional and is not a verified market deadline."
)
HOURLY_AGGREGATION = (
    "The two FUELHH half-hour average-MW values are averaged, not summed, to "
    "produce a provisional hourly average-MW series. WINDFOR's hourly averaging "
    "semantics remain undocumented, so this series is not yet treated as a "
    "verified like-for-like comparison."
)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="wind-forecast-analytics-api")


def _get_analysis(decision_date: date, cutoff_time: time):
    try:
        return analytics_service.analyze(decision_date, cutoff_time)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ElexonApiError as error:
        raise HTTPException(
            status_code=502,
            detail=ErrorResponse(
                status="upstream_error",
                dataset=error.dataset,
                message=str(error),
            ).model_dump(),
        ) from error
    except DataValidationError as error:
        raise HTTPException(
            status_code=502,
            detail=ErrorResponse(
                status="invalid_upstream_data",
                dataset="FUELHH or WINDFOR",
                message=str(error),
            ).model_dump(),
        ) from error


def _metadata(analysis: Analysis) -> dict:
    expected = analysis.expected_intervals
    forecast_count = len(analysis.forecast)
    actual_count = len(analysis.actual)
    return AnalysisMetadata(
        decision_date=analysis.decision_date,
        delivery_date=analysis.delivery_date,
        cutoff_at=analysis.cutoff_at,
        cutoff_assumption=CUTOFF_ASSUMPTION,
        expected_hourly_intervals=expected,
        forecast_publications_considered=analysis.publication_count,
        forecast_publication_lookback_hours=int(FORECAST_LOOKBACK.total_seconds() / 3600),
        forecast_records_retrieved=analysis.forecast_records_retrieved,
        actual_wind_records_retrieved=analysis.actual_wind_records_retrieved,
        actual_non_wind_records_filtered=analysis.actual_non_wind_records_filtered,
        forecast_duplicates_removed=analysis.forecast_duplicates_removed,
        actual_duplicates_removed=analysis.actual_duplicates_removed,
        missing_forecast_intervals=analysis.missing_forecast_hours,
        missing_actual_intervals=analysis.missing_actual_hours,
        forecast_coverage=forecast_count / expected if expected else 0,
        actual_coverage=actual_count / expected if expected else 0,
        aligned_observation_count=analysis.aligned_count,
        alignment_verified=INTERVAL_ALIGNMENT_CONFIRMED,
        forecast_unit_verified=FORECAST_UNIT_CONFIRMED,
        limitation=COMPATIBILITY_LIMITATION,
    ).model_dump()


@router.get("/forecast", response_model=ForecastResponse)
def forecast(
    decision_date: date = Query(..., description="Purchasing decision date in January 2026"),
    cutoff_time: time = Query(
        default=time(23, 0),
        description="Latest eligible publication time in Europe/London; provisional default 23:00",
    ),
) -> ForecastResponse:
    analysis = _get_analysis(decision_date, cutoff_time)
    metadata = _metadata(analysis)
    return ForecastResponse(
        **metadata,
        forecasts=[
            ForecastPoint(
                delivery_start=record.start_time,
                published_at=record.publish_time,
                generation=record.generation,
            )
            for record in analysis.forecast
        ],
    )


@router.get("/comparison", response_model=ComparisonResponse)
def comparison(
    decision_date: date = Query(..., description="Purchasing decision date in January 2026"),
    cutoff_time: time = Query(
        default=time(23, 0),
        description="Latest eligible publication time in Europe/London; provisional default 23:00",
    ),
) -> ComparisonResponse:
    analysis = _get_analysis(decision_date, cutoff_time)
    metadata = _metadata(analysis)
    return ComparisonResponse(
        **metadata,
        comparison=analysis.comparison,
        actual_half_hour_records=analysis.actual_half_hours,
        expected_actual_half_hour_records=analysis.expected_actual_half_hours,
        hourly_actual_aggregation=HOURLY_AGGREGATION,
        metrics_available=(
            FORECAST_UNIT_CONFIRMED
            and INTERVAL_ALIGNMENT_CONFIRMED
            and analysis.metrics.observation_count > 0
        ),
    )


@router.get("/metrics", response_model=MetricsResponse)
def metrics(
    decision_date: date = Query(..., description="Purchasing decision date in January 2026"),
    cutoff_time: time = Query(
        default=time(23, 0),
        description="Latest eligible publication time in Europe/London; provisional default 23:00",
    ),
) -> MetricsResponse:
    analysis = _get_analysis(decision_date, cutoff_time)
    eligible = (
        FORECAST_UNIT_CONFIRMED
        and INTERVAL_ALIGNMENT_CONFIRMED
        and analysis.metrics.observation_count > 0
    )
    metadata = _metadata(analysis)
    return MetricsResponse(
        **metadata,
        mae_mw=analysis.metrics.mae if eligible else None,
        rmse_mw=analysis.metrics.rmse if eligible else None,
        mean_bias_mw=analysis.metrics.bias if eligible else None,
        wape_percent=analysis.metrics.wape if eligible else None,
        observation_count=analysis.metrics.observation_count,
        metrics_available=eligible,
    )
