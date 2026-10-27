from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from app.services.analytics_service import (
    ActualRecord,
    AnalyticsService,
    DataValidationError,
    ForecastRecord,
    _delivery_hours,
    aggregate_actuals_hourly,
    calculate_metrics,
    parse_actuals,
    parse_forecasts,
)
from app.services.elexon_client import ElexonApiError, ElexonClient

client = TestClient(app)
LONDON = ZoneInfo("Europe/London")
UTC = timezone.utc


def actual_payload(delivery: date, half_hours: int = 48) -> list[dict]:
    """Deterministic synthetic records for tests; not downloaded Elexon observations."""
    start = datetime.combine(delivery, time.min, tzinfo=UTC)
    return [
        {
            "dataset": "FUELHH",
            "publishTime": (start + timedelta(minutes=30 * (index + 1))).isoformat(),
            "startTime": (start + timedelta(minutes=30 * index)).isoformat(),
            "settlementDate": delivery.isoformat(),
            "settlementPeriod": index + 1,
            "fuelType": "WIND",
            "generation": 100 + index,
        }
        for index in range(half_hours)
    ]


def forecast_payload(
    delivery: date,
    publication: datetime,
    generation: float = 120,
) -> list[dict]:
    """Deterministic synthetic hourly forecast records for tests."""
    start = datetime.combine(delivery, time.min, tzinfo=UTC)
    return [
        {
            "dataset": "WINDFOR",
            "publishTime": publication.isoformat(),
            "startTime": (start + timedelta(hours=hour)).isoformat(),
            "generation": generation + hour,
        }
        for hour in range(24)
    ]


class FakeElexonClient:
    def __init__(self, actuals: list[dict], forecasts: list[dict]) -> None:
        self.actuals = actuals
        self.forecasts = forecasts
        self.actual_date: date | None = None
        self.forecast_range: tuple[datetime, datetime] | None = None

    def get_actuals(self, delivery_date: date) -> list[dict]:
        self.actual_date = delivery_date
        return self.actuals

    def get_forecasts(self, publish_from: datetime, publish_to: datetime) -> list[dict]:
        self.forecast_range = (publish_from, publish_to)
        return self.forecasts


def test_health_returns_success() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "wind-forecast-analytics-api",
    }


def test_local_frontend_origin_is_allowed_by_cors() -> None:
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_actual_response_parsing_filters_wind_and_collapses_exact_duplicates() -> None:
    wind = actual_payload(date(2026, 1, 2), half_hours=1)[0]
    non_wind = {**wind, "fuelType": "CCGT", "generation": 900}

    records, duplicates, filtered = parse_actuals([wind, wind, non_wind])

    assert len(records) == 1
    assert records[0].generation_mw == 100
    assert duplicates == 1
    assert filtered == 1


def test_conflicting_actual_duplicates_are_not_silently_discarded() -> None:
    wind = actual_payload(date(2026, 1, 2), half_hours=1)[0]
    conflict = {**wind, "generation": 101}

    with pytest.raises(DataValidationError, match="Conflicting FUELHH"):
        parse_actuals([wind, conflict])


def test_actual_records_with_settlement_date_outside_query_are_rejected() -> None:
    actual = actual_payload(date(2026, 1, 2), half_hours=1)[0]
    actual["settlementDate"] = "2026-01-03"
    upstream = FakeElexonClient([actual], [])

    with pytest.raises(DataValidationError, match="outside the requested delivery date"):
        AnalyticsService(upstream).analyze(date(2026, 1, 1), time(23, 0))


def test_forecast_response_parsing_and_exact_duplicate_policy() -> None:
    publish = datetime(2026, 1, 1, 22, 30, tzinfo=UTC)
    record = forecast_payload(date(2026, 1, 2), publish)[0]

    forecasts, duplicates = parse_forecasts([record, record])

    assert len(forecasts) == 1
    assert forecasts[0].publish_time == publish
    assert forecasts[0].generation == 120
    assert duplicates == 1


def test_forecast_parser_rejects_naive_timestamp() -> None:
    record = {
        "dataset": "WINDFOR",
        "publishTime": "2026-01-01T22:30:00",
        "startTime": "2026-01-02T00:00:00Z",
        "generation": 10,
    }

    with pytest.raises(DataValidationError, match="must include a timezone"):
        parse_forecasts([record])


def test_response_parsers_reject_wrong_datasets_and_invalid_actual_schema() -> None:
    actual = actual_payload(date(2026, 1, 2), half_hours=1)[0]
    with pytest.raises(DataValidationError, match="unexpected dataset"):
        parse_actuals([{**actual, "dataset": "WINDFOR"}])
    with pytest.raises(DataValidationError, match="settlementPeriod"):
        parse_actuals([{key: value for key, value in actual.items() if key != "settlementPeriod"}])


def test_selects_latest_eligible_forecast_version_and_excludes_later_records() -> None:
    delivery = date(2026, 1, 2)
    old_publication = datetime(2026, 1, 1, 18, 30, tzinfo=UTC)
    selected_publication = datetime(2026, 1, 1, 22, 30, tzinfo=UTC)
    late_publication = datetime(2026, 1, 1, 23, 1, tzinfo=UTC)
    old = forecast_payload(delivery, old_publication, 90)
    selected = forecast_payload(delivery, selected_publication, 120)
    late = forecast_payload(delivery, late_publication, 150)
    service = AnalyticsService(
        FakeElexonClient(
            actual_payload(delivery),
            old + selected + late,
        )
    )

    analysis = service.analyze(date(2026, 1, 1), time(23, 0))

    assert len(analysis.forecast) == 24
    assert all(item.publish_time == selected_publication for item in analysis.forecast)
    assert analysis.forecast[0].generation == 120
    assert analysis.publication_count == 2


def test_forecast_selection_uses_europe_london_cutoff_as_utc() -> None:
    delivery = date(2026, 1, 2)
    publication = datetime(2026, 1, 1, 22, 30, tzinfo=UTC)
    upstream = FakeElexonClient(
        actual_payload(delivery),
        forecast_payload(delivery, publication),
    )

    analysis = AnalyticsService(upstream).analyze(date(2026, 1, 1), time(23, 0))

    assert analysis.cutoff_at == datetime(2026, 1, 1, 23, 0, tzinfo=UTC)
    assert upstream.forecast_range is not None
    assert upstream.forecast_range[1] == analysis.cutoff_at
    assert upstream.forecast_range[0] == analysis.cutoff_at - timedelta(hours=48)


@pytest.mark.parametrize("day", range(1, 32))
def test_every_january_decision_date_covers_its_next_day(day: int) -> None:
    decision_date = date(2026, 1, day)
    delivery_date = decision_date + timedelta(days=1)
    publication = datetime.combine(decision_date, time(22, 30), tzinfo=UTC)
    upstream = FakeElexonClient(
        actual_payload(delivery_date),
        forecast_payload(delivery_date, publication),
    )

    analysis = AnalyticsService(upstream).analyze(decision_date, time(23, 0))

    assert upstream.actual_date == delivery_date
    assert analysis.delivery_date == delivery_date
    assert analysis.cutoff_at == datetime.combine(decision_date, time(23, 0), tzinfo=UTC)
    assert len(analysis.forecast) == analysis.expected_intervals == 24
    assert len(analysis.actual) == 24
    assert analysis.missing_forecast_hours == []
    assert analysis.missing_actual_hours == []
    assert analysis.aligned_count == 24
    assert all(record.publish_time <= analysis.cutoff_at for record in analysis.forecast)
    assert [record.start_time for record in analysis.forecast] == _delivery_hours(delivery_date)
    assert analysis.actual_half_hours == analysis.expected_actual_half_hours == 48
    if day == 31:
        assert delivery_date == date(2026, 2, 1)


def test_actuals_are_averaged_hourly_only_when_both_half_hours_exist() -> None:
    hours = _delivery_hours(date(2026, 1, 2))
    records = [
        ActualRecord(hours[0], 100),
        ActualRecord(hours[0] + timedelta(minutes=30), 200),
        ActualRecord(hours[1], 300),
    ]

    hourly, missing, received = aggregate_actuals_hourly(
        records, date(2026, 1, 2), hours
    )

    assert hourly[hours[0]] == 150
    assert hours[1] not in hourly
    assert hours[1] in missing
    assert len(missing) == 23
    assert received == 3


def test_zero_generation_is_a_real_actual_value_not_a_missing_interval() -> None:
    hours = _delivery_hours(date(2026, 1, 2))
    records = [
        ActualRecord(hours[0], 0),
        ActualRecord(hours[0] + timedelta(minutes=30), 0),
    ]

    hourly, missing, _ = aggregate_actuals_hourly(records, date(2026, 1, 2), hours)

    assert hourly[hours[0]] == 0
    assert hours[0] not in missing


def test_hourly_matching_uses_the_same_utc_delivery_start() -> None:
    delivery = date(2026, 1, 2)
    publication = datetime(2026, 1, 1, 22, 30, tzinfo=UTC)
    upstream = FakeElexonClient(
        actual_payload(delivery),
        forecast_payload(delivery, publication),
    )

    analysis = AnalyticsService(upstream).analyze(date(2026, 1, 1), time(23, 0))

    assert len(analysis.comparison) == 24
    assert analysis.comparison[0]["delivery_start"] == datetime(
        2026, 1, 2, 0, 0, tzinfo=UTC
    )
    assert analysis.comparison[0]["actual_generation_mw"] == 100.5
    assert analysis.comparison[0]["forecast_generation"] == 120
    assert analysis.aligned_count == 24


def test_missing_forecast_and_actual_remain_null_and_reduce_coverage() -> None:
    delivery = date(2026, 1, 2)
    publication = datetime(2026, 1, 1, 22, 30, tzinfo=UTC)
    actuals = actual_payload(delivery, half_hours=47)
    forecasts = forecast_payload(delivery, publication)[:-1]
    analysis = AnalyticsService(
        FakeElexonClient(actuals, forecasts)
    ).analyze(date(2026, 1, 1), time(23, 0))

    assert analysis.comparison[0]["forecast_generation"] == 120
    assert analysis.comparison[-1]["forecast_generation"] is None
    assert analysis.comparison[-1]["actual_generation_mw"] is None
    assert len(analysis.missing_forecast_hours) == 1
    assert len(analysis.missing_actual_hours) == 1
    assert analysis.aligned_count == 23


def test_empty_upstream_responses_produce_zero_coverage_not_zero_values() -> None:
    analysis = AnalyticsService(FakeElexonClient([], [])).analyze(
        date(2026, 1, 1), time(23, 0)
    )

    assert analysis.forecast == []
    assert analysis.actual == {}
    assert analysis.aligned_count == 0
    assert len(analysis.missing_forecast_hours) == 24
    assert len(analysis.missing_actual_hours) == 24
    assert analysis.metrics.mae is None


def test_metrics_match_known_example_and_zero_actual_wape_is_null() -> None:
    result = calculate_metrics([1, 3], [2, 1])

    assert result.observation_count == 2
    assert result.mae == pytest.approx(1.5)
    assert result.rmse == pytest.approx((2.5) ** 0.5)
    assert result.bias == pytest.approx(0.5)
    assert result.wape == pytest.approx(100.0)

    zero_denominator = calculate_metrics([1, 2], [0, 0])
    assert zero_denominator.wape is None


def test_metrics_reject_unequal_or_non_finite_inputs() -> None:
    with pytest.raises(ValueError, match="equally sized"):
        calculate_metrics([1], [1, 2])
    with pytest.raises(ValueError, match="finite"):
        calculate_metrics([float("nan")], [0])


def test_january_31_decision_requests_february_1_actuals() -> None:
    upstream = FakeElexonClient([], [])
    analysis = AnalyticsService(upstream).analyze(date(2026, 1, 31), time(23, 0))

    assert upstream.actual_date == date(2026, 2, 1)
    assert analysis.delivery_date == date(2026, 2, 1)
    assert analysis.cutoff_at == datetime(2026, 1, 31, 23, 0, tzinfo=UTC)


def test_london_daylight_saving_delivery_day_has_23_utc_intervals() -> None:
    hours = _delivery_hours(date(2026, 3, 29))

    assert len(hours) == 23
    assert hours[0] == datetime(2026, 3, 29, 0, 0, tzinfo=UTC)


def test_january_request_date_validation() -> None:
    service = AnalyticsService(FakeElexonClient([], []))

    with pytest.raises(ValueError, match="January 2026"):
        service.analyze(date(2026, 2, 1), time(23, 0))
    with pytest.raises(ValueError, match="without an offset"):
        service.analyze(
            date(2026, 1, 1),
            time(23, 0, tzinfo=ZoneInfo("Europe/London")),
        )


def test_elexon_actual_request_uses_documented_fuel_and_settlement_filters() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    elexon = ElexonClient(transport=httpx.MockTransport(handler))
    try:
        elexon.get_actuals(date(2026, 2, 1))
    finally:
        elexon.close()

    request = requests[0]
    assert request.url.path == "/bmrs/api/v1/datasets/FUELHH/stream"
    assert request.url.params["settlementDateFrom"] == "2026-02-01"
    assert request.url.params["settlementDateTo"] == "2026-02-01"
    assert request.url.params["fuelType"] == "WIND"


def test_elexon_forecast_request_uses_bounded_publication_filters_only() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[])

    elexon = ElexonClient(transport=httpx.MockTransport(handler))
    start = datetime(2026, 1, 1, 23, 0, tzinfo=ZoneInfo("Europe/London"))
    end = datetime(2026, 1, 2, 23, 0, tzinfo=ZoneInfo("Europe/London"))
    try:
        elexon.get_forecasts(start, end)
    finally:
        elexon.close()

    request = requests[0]
    assert request.url.path == "/bmrs/api/v1/datasets/WINDFOR/stream"
    assert request.url.params["publishDateTimeFrom"] == "2026-01-01T23:00:00Z"
    assert request.url.params["publishDateTimeTo"] == "2026-01-02T23:00:00Z"
    assert "settlementDate" not in request.url.params


@pytest.mark.parametrize(
    ("response", "expected_message"),
    [
        (httpx.Response(503), "HTTP 503"),
        (httpx.Response(200, text="not-json"), "invalid JSON"),
        (httpx.Response(200, json={"error": "not an array"}), "JSON array"),
    ],
)
def test_elexon_errors_are_reported(response, expected_message: str) -> None:
    elexon = ElexonClient(
        transport=httpx.MockTransport(lambda request: response)
    )
    try:
        with pytest.raises(ElexonApiError, match=expected_message):
            elexon.get_actuals(date(2026, 1, 2))
    finally:
        elexon.close()


def test_elexon_timeout_is_reported() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("request timed out", request=request)

    elexon = ElexonClient(
        transport=httpx.MockTransport(timeout_handler)
    )
    try:
        with pytest.raises(ElexonApiError, match="timed out"):
            elexon.get_actuals(date(2026, 1, 2))
    finally:
        elexon.close()


def test_api_reports_mw_unit_but_withholds_metrics_for_interval_uncertainty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivery = date(2026, 1, 2)
    publication = datetime(2026, 1, 1, 22, 30, tzinfo=UTC)
    monkeypatch.setattr(
        routes,
        "analytics_service",
        AnalyticsService(
            FakeElexonClient(
                actual_payload(delivery),
                forecast_payload(delivery, publication),
            )
        ),
    )

    response = client.get(
        "/api/metrics",
        params={"decision_date": "2026-01-01", "cutoff_time": "23:00"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["delivery_date"] == "2026-01-02"
    assert body["aligned_observation_count"] == 24
    assert body["observation_count"] == 24
    assert body["forecast_unit_verified"] is True
    assert body["alignment_verified"] is False
    assert body["metrics_available"] is False
    assert body["mae_mw"] is None

    forecast_response = client.get(
        "/api/forecast",
        params={"decision_date": "2026-01-01", "cutoff_time": "23:00"},
    )
    comparison_response = client.get(
        "/api/comparison",
        params={"decision_date": "2026-01-01", "cutoff_time": "23:00"},
    )
    assert forecast_response.status_code == 200
    assert len(forecast_response.json()["forecasts"]) == 24
    assert comparison_response.status_code == 200
    assert len(comparison_response.json()["comparison"]) == 24


def test_api_validates_date_and_maps_upstream_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = client.get(
        "/api/forecast",
        params={"decision_date": "not-a-date"},
    )
    assert response.status_code == 422
    response = client.get(
        "/api/forecast",
        params={"decision_date": "2026-01-01", "cutoff_time": "25:00"},
    )
    assert response.status_code == 422

    class BrokenClient:
        def get_actuals(self, delivery_date: date) -> list[dict]:
            raise ElexonApiError("FUELHH", "Elexon FUELHH request timed out.")

    monkeypatch.setattr(
        routes,
        "analytics_service",
        AnalyticsService(BrokenClient()),  # type: ignore[arg-type]
    )
    response = client.get(
        "/api/forecast",
        params={"decision_date": "2026-01-01"},
    )
    assert response.status_code == 502
    assert response.json()["detail"]["status"] == "upstream_error"
