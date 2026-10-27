import { useEffect, useMemo, useState } from "react";
import {
  getComparison,
  getHealth,
  getMetrics,
} from "./services/api.js";

const metricCards = [
  { label: "Mean absolute error", key: "mae_mw", unit: "MW", description: "Average absolute forecast error" },
  { label: "Root mean squared error", key: "rmse_mw", unit: "MW", description: "Penalises larger forecast misses" },
  { label: "Mean bias", key: "mean_bias_mw", unit: "MW", description: "Forecast minus actual generation" },
  { label: "Weighted absolute percentage error", key: "wape_percent", unit: "%", description: "Absolute error relative to actual output" },
];

function nextDate(dateString) {
  const date = new Date(`${dateString}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}

function formatDate(dateString) {
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${dateString}T00:00:00Z`));
}

function formatTimestamp(timestamp) {
  if (!timestamp) return "—";
  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/London",
    timeZoneName: "short",
  }).format(new Date(timestamp));
}

function formatMetric(value) {
  return value == null ? "—" : new Intl.NumberFormat("en-GB", {
    maximumFractionDigits: 1,
  }).format(value);
}

export default function App() {
  const [decisionDate, setDecisionDate] = useState("2026-01-01");
  const [cutoffTime, setCutoffTime] = useState("23:00");
  const [health, setHealth] = useState("checking");
  const [loading, setLoading] = useState(true);
  const [dataError, setDataError] = useState("");
  const [comparisonData, setComparisonData] = useState(null);
  const [metricsData, setMetricsData] = useState(null);

  const deliveryDate = useMemo(() => nextDate(decisionDate), [decisionDate]);

  useEffect(() => {
    let active = true;
    getHealth()
      .then(() => {
        if (active) setHealth("online");
      })
      .catch(() => {
        if (active) {
          setHealth("offline");
        }
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setDataError("");
    setComparisonData(null);
    setMetricsData(null);

    async function loadAnalysis() {
      try {
        const comparison = await getComparison(decisionDate, cutoffTime);
        if (!active) return;

        setComparisonData(comparison);
        if (comparison.metrics_available) {
          setMetricsData(await getMetrics(decisionDate, cutoffTime));
        }
      } catch (error) {
        if (active) setDataError(error.message);
      } finally {
        if (active) setLoading(false);
      }
    }

    loadAnalysis();

    return () => {
      active = false;
    };
  }, [decisionDate, cutoffTime]);

  const intervalRows = comparisonData?.comparison ?? [];
  const hasDeliveryRecords = intervalRows.some(
    (row) => row.forecast_generation != null || row.actual_generation_mw != null,
  );
  const lastSelectedPublication = intervalRows.reduce(
    (latest, row) => (
      row.forecast_published_at
        && (!latest || row.forecast_published_at > latest)
        ? row.forecast_published_at
        : latest
    ),
    null,
  );
  const actualValues = intervalRows
    .map((row) => row.actual_generation_mw)
    .filter((value) => value != null);
  const actualMin = actualValues.length ? Math.min(...actualValues) : 0;
  const actualMax = actualValues.length ? Math.max(...actualValues) : 1;
  const actualRange = actualMax - actualMin || 1;
  let actualPath = "";
  intervalRows.forEach((row, index) => {
    if (row.actual_generation_mw == null) return;
    const x = intervalRows.length > 1 ? 10 + (index / (intervalRows.length - 1)) * 880 : 450;
    const y = 170 - ((row.actual_generation_mw - actualMin) / actualRange) * 150;
    const hasPreviousValue = index > 0 && intervalRows[index - 1].actual_generation_mw != null;
    actualPath += `${actualPath ? " " : ""}${hasPreviousValue ? "L" : "M"} ${x} ${y}`;
  });

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="Wind Forecast Analytics home">
          <span className="brand-mark" aria-hidden="true">W</span>
          <span className="brand-copy">
            <strong>Northstar</strong>
            <small>ENERGY INTELLIGENCE</small>
          </span>
        </a>
        <div className="nav-label">WORKSPACE</div>
        <div className="nav-item nav-item-active">
          <span className="nav-icon" aria-hidden="true">▦</span>
          Forecast review
        </div>
        <div className="sidebar-bottom">
          <span className={`connection-dot connection-${health}`} />
          <span>
            API {health === "online" ? "connected" : health === "offline" ? "unavailable" : "connecting"}
          </span>
          <span className="api-version">v0.1</span>
        </div>
      </aside>

      <main className="main-content">
        <header className="topbar">
          <div className="breadcrumb">Analytics <span>/</span> Forecast review</div>
          <div className="historical-badge"><span /> HISTORICAL ANALYSIS</div>
        </header>

        <div className="page-content">
          <section className="page-heading">
            <div>
              <div className="eyebrow">UK POWER SYSTEM · WIND</div>
              <h1>Wind Forecast Analytics</h1>
              <p>Review the forecast available at decision time against delivered generation.</p>
            </div>
            <div className="period-tag"><span className="calendar-icon">▣</span> JANUARY 2026</div>
          </section>

          <section className="selection-panel" aria-label="Analysis selection">
            <div className="selection-field">
              <label htmlFor="decision-date">Decision date</label>
              <input
                id="decision-date"
                type="date"
                required
                min="2026-01-01"
                max="2026-01-31"
                value={decisionDate}
                onChange={(event) => setDecisionDate(event.target.value)}
              />
            </div>
            <div className="selection-divider" />
            <div className="selection-field">
              <label htmlFor="cutoff-time">Decision cutoff <span className="timezone-label">UK time</span></label>
              <input
                id="cutoff-time"
                type="time"
                required
                value={cutoffTime}
                onChange={(event) => setCutoffTime(event.target.value)}
              />
            </div>
            <div className="delivery-summary">
              <span className="delivery-label">DELIVERY DATE</span>
              <strong>{formatDate(deliveryDate)}</strong>
              <span className="assumption-note">Assumed next-day delivery</span>
            </div>
          </section>

          <div className="assumption-banner">
            <span className="info-icon">i</span>
            <span><strong>Cutoff assumption:</strong> {comparisonData?.cutoff_assumption ?? "23:00 Europe/London by default. This is configurable and is not a verified market deadline."}</span>
          </div>

          {dataError && (
            <div className="error-banner" role="alert">
              <strong>Historical data request failed</strong>
              <span>{dataError}</span>
            </div>
          )}

          <section className="section-heading">
            <div>
              <h2>Forecast performance</h2>
              <p>Selected forecast publication compared with national wind outturn.</p>
            </div>
            <span className="unit-chip">Actual &amp; forecast · MW <span className="unit-caveat">Interval basis unverified</span></span>
          </section>

          <section className="chart-panel" aria-label="Forecast and actual generation chart">
            <div className="panel-header">
              <div>
                <h3>Forecast vs actual</h3>
                <p>Delivery date: {formatDate(deliveryDate)}</p>
              </div>
              <div className="chart-legend">
                <span><i className="legend-actual" /> Actual average MW</span>
                <span><i className="legend-forecast" /> Forecast comparison withheld</span>
              </div>
            </div>
            <div className="chart-empty">
              <div className="chart-grid" aria-hidden="true">
                <span /><span /><span /><span />
                <div className="chart-axis-labels"><span>MW</span><span>Delivery intervals →</span></div>
              </div>
              {!loading && !dataError && actualValues.length > 0 ? (
                <>
                  <svg
                    className="actual-line-chart"
                    viewBox="0 0 900 180"
                    role="img"
                    aria-label="Hourly wind generation actuals in megawatts. Forecast comparison withheld because WINDFOR interval semantics are not verified."
                    preserveAspectRatio="none"
                  >
                    <path d={actualPath} className="actual-chart-path" />
                    {intervalRows.map((row, index) => {
                      if (row.actual_generation_mw == null) return null;
                      const x = intervalRows.length > 1 ? 10 + (index / (intervalRows.length - 1)) * 880 : 450;
                      const y = 170 - ((row.actual_generation_mw - actualMin) / actualRange) * 150;
                      return (
                        <circle key={row.delivery_start} cx={x} cy={y} r="2.5" className="actual-chart-point">
                          <title>{`${formatTimestamp(row.delivery_start)} · ${formatMetric(row.actual_generation_mw)} MW actual`}</title>
                        </circle>
                      );
                    })}
                  </svg>
                  <div className="chart-note">
                    <strong>Actual outturn only</strong>
                    <span>{comparisonData.limitation}</span>
                  </div>
                </>
              ) : (
              <div className="empty-message">
                <span className="empty-icon" aria-hidden="true">⌁</span>
                {loading ? (
                  <>
                    <strong>Checking data availability</strong>
                    <p>Retrieving historical FUELHH actuals and eligible WINDFOR publications.</p>
                  </>
                ) : dataError ? (
                  <>
                    <strong>Data unavailable</strong>
                    <p>Check the request details above, then retry when the Elexon API is available.</p>
                  </>
                ) : hasDeliveryRecords ? (
                  <>
                    <strong>Historical records retrieved · comparison withheld</strong>
                    <p>{comparisonData.limitation}</p>
                  </>
                ) : (
                  <>
                    <strong>No matching historical records</strong>
                    <p>The selected date returned no aligned forecast and actual observations. Missing values are not replaced with zero.</p>
                  </>
                )}
              </div>
              )}
            </div>
            <div className="chart-footer">
              <span>Latest selected publication <strong>{formatTimestamp(lastSelectedPublication)}</strong></span>
              <span>Timezone <strong>UTC timestamps · UK display</strong></span>
            </div>
            {!loading && !dataError && intervalRows.length > 0 && (
              <div className="records-table-wrap">
                <div className="records-table-heading">
                  <strong>Retrieved hourly intervals</strong>
                  <span>Elexon labels the forecast in MW; its hourly averaging basis is unverified, so no line-to-line chart or accuracy claim is shown.</span>
                </div>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Delivery start (UK)</th>
                        <th>Forecast (MW)</th>
                        <th>Forecast published</th>
                        <th>Actual hourly average (MW)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {intervalRows.map((row) => (
                        <tr key={row.delivery_start}>
                          <td>{formatTimestamp(row.delivery_start)}</td>
                          <td>{formatMetric(row.forecast_generation)}</td>
                          <td>{formatTimestamp(row.forecast_published_at)}</td>
                          <td>{formatMetric(row.actual_generation_mw)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </section>

          <section className="metrics-section">
            <div className="section-heading compact">
              <div>
                <h2>Accuracy metrics</h2>
                <p>Values are withheld until the WINDFOR hourly time basis is verified as compatible with hourly actual averages.</p>
              </div>
            </div>
            <div className="metric-grid">
              {metricCards.map((metric) => (
                <article className="metric-card" key={metric.key}>
                  <div className="metric-title">{metric.label}</div>
                  <div className="metric-value">{formatMetric(metricsData?.[metric.key])} <small>{metric.unit}</small></div>
                  <div className="metric-description">{metricsData?.metrics_available ? metric.description : "Unavailable · hourly interval basis unverified"}</div>
                </article>
              ))}
            </div>
          </section>

          <section className="coverage-panel">
            <div>
              <span className="coverage-title">DATA COVERAGE</span>
              <strong>{loading ? "Checking…" : dataError ? "Unavailable" : `${Math.round((comparisonData?.forecast_coverage ?? 0) * 100)}% forecast · ${Math.round((comparisonData?.actual_coverage ?? 0) * 100)}% actual`}</strong>
              <span>{comparisonData ? `${comparisonData.forecast_records_retrieved.toLocaleString("en-GB")} forecast records across ${comparisonData.forecast_publications_considered} publications · ${comparisonData.actual_wind_records_retrieved} WIND half-hours retrieved` : "Coverage will appear when the historical API request completes."}</span>
            </div>
            <div className="coverage-stat">
              <span>ALIGNED OBSERVATIONS</span>
              <strong>{comparisonData?.aligned_observation_count ?? "—"}</strong>
              <small>timestamp-aligned hourly pairs</small>
            </div>
            <div className="coverage-stat">
              <span>FORECAST SOURCE</span>
              <strong>WINDFOR</strong>
              <small>{comparisonData ? `${comparisonData.forecast_publication_lookback_hours}h publication lookback` : "historical vintages"}</small>
            </div>
          </section>

          <footer className="page-footer">
            <span>Wind Forecast Analytics <span className="footer-separator">·</span> Historical analysis only</span>
            <span>No live trading decisions are made by this application.</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
