from __future__ import annotations

from datetime import date, datetime, timezone
from threading import RLock
from time import monotonic
from typing import Any

import httpx

API_BASE_URL = "https://data.elexon.co.uk/bmrs/api/v1/datasets/"


class ElexonApiError(Exception):
    def __init__(self, dataset: str, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.dataset = dataset
        self.status_code = status_code


class ElexonClient:
    def __init__(
        self,
        transport: httpx.BaseTransport | None = None,
        timeout: httpx.Timeout | None = None,
        cache_ttl_seconds: int = 300,
    ) -> None:
        self._http = httpx.Client(
            base_url=API_BASE_URL,
            timeout=timeout or httpx.Timeout(20.0, connect=5.0),
            transport=transport,
            headers={"Accept": "application/json"},
        )
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[tuple[str, tuple[tuple[str, str], ...]], tuple[float, Any]] = {}
        self._lock = RLock()

    def _get(self, dataset: str, params: dict[str, str]) -> Any:
        key = (dataset, tuple(sorted(params.items())))
        with self._lock:
            cached = self._cache.get(key)
            if cached and cached[0] > monotonic():
                return cached[1]
            try:
                response = self._http.get(f"{dataset}/stream", params=params)
                response.raise_for_status()
            except httpx.TimeoutException as error:
                raise ElexonApiError(dataset, f"Elexon {dataset} request timed out.") from error
            except httpx.HTTPStatusError as error:
                raise ElexonApiError(
                    dataset,
                    f"Elexon {dataset} returned HTTP {error.response.status_code}.",
                    error.response.status_code,
                ) from error
            except httpx.RequestError as error:
                raise ElexonApiError(dataset, f"Could not reach Elexon {dataset}.") from error
            try:
                payload = response.json()
            except ValueError as error:
                raise ElexonApiError(dataset, f"Elexon {dataset} returned invalid JSON.") from error
            if not isinstance(payload, list):
                raise ElexonApiError(dataset, f"Elexon {dataset} response must be a JSON array.")
            self._cache[key] = (monotonic() + self._cache_ttl_seconds, payload)
            return payload

    def get_actuals(self, delivery_date: date) -> list[dict[str, Any]]:
        return self._get(
            "FUELHH",
            {
                "settlementDateFrom": delivery_date.isoformat(),
                "settlementDateTo": delivery_date.isoformat(),
                "fuelType": "WIND",
            },
        )

    def get_forecasts(
        self, publish_from: datetime, publish_to: datetime
    ) -> list[dict[str, Any]]:
        if publish_from.tzinfo is None or publish_to.tzinfo is None:
            raise ValueError("WINDFOR publication bounds must be timezone-aware.")
        if publish_from > publish_to:
            raise ValueError("WINDFOR publication range start must not exceed its end.")
        return self._get(
            "WINDFOR",
            {
                "publishDateTimeFrom": publish_from.astimezone(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
                "publishDateTimeTo": publish_to.astimezone(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z"),
            },
        )

    def close(self) -> None:
        self._http.close()
