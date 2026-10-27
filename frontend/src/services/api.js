const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message, status, code = "request_failed") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function request(path, params) {
  const query = params ? `?${new URLSearchParams(params)}` : "";
  let response;

  try {
    response = await fetch(`${API_BASE_URL}/api/${path}${query}`);
  } catch {
    throw new ApiError(
      "Could not reach the analytics API. Check that the backend is running.",
      0,
      "network_error",
    );
  }

  let body;
  try {
    body = await response.json();
  } catch {
    throw new ApiError(
      "The analytics API returned an unreadable response.",
      response.status,
      "invalid_response",
    );
  }

  if (!response.ok) {
    const detail = body.detail ?? body;
    const validationMessage = Array.isArray(detail)
      ? detail.map((issue) => {
        const field = Array.isArray(issue.loc) ? issue.loc.at(-1) : "request";
        return `${field}: ${issue.msg}`;
      }).join("; ")
      : null;
    throw new ApiError(
      detail.message ?? detail.msg ?? validationMessage ?? "The analytics API request failed.",
      response.status,
      detail.status ?? detail.code ?? (Array.isArray(detail) ? "validation_error" : "request_failed"),
    );
  }

  return body;
}

export function getHealth() {
  return request("health");
}

export function getForecast(decisionDate, cutoffTime) {
  return request("forecast", {
    decision_date: decisionDate,
    cutoff_time: cutoffTime,
  });
}

export function getComparison(decisionDate, cutoffTime) {
  return request("comparison", {
    decision_date: decisionDate,
    cutoff_time: cutoffTime,
  });
}

export function getMetrics(decisionDate, cutoffTime) {
  return request("metrics", {
    decision_date: decisionDate,
    cutoff_time: cutoffTime,
  });
}
