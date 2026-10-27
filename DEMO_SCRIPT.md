# Wind Forecast Analytics: demo plan and speaking script

**Target runtime:** 9 minutes 30 seconds total. Keep each part under five minutes.
**Recording:** One unlisted YouTube video; recording and upload are still to be completed.

## Part 1 — Customer-facing overview (0:00–4:30)

| Time | Screen | Speaking script |
|---|---|---|
| 0:00–0:35 | Dashboard title and January 2026 label | “This dashboard examines historical UK wind generation forecasts in the context of a day-ahead purchasing decision. It is an analysis tool, not a live trading system. The question is: what forecast was available at a chosen decision time, and what wind generation was later reported?” |
| 0:35–1:20 | Decision date and cutoff controls | “I can select a decision date from January 1 through January 31, 2026, and a local UK-time cutoff. The default is 23:00 Europe/London, but it is a configurable analysis assumption—not a verified market deadline. The delivery shown is the following UK calendar day; selecting January 31 therefore examines February 1 delivery.” |
| 1:20–2:10 | Data coverage and source labels | “The application requests Elexon FUELHH wind outturn and WINDFOR forecast versions. Coverage reports how many delivery hours have forecast and actual observations. Missing intervals remain missing rather than being filled with zero. Publication timestamps show when selected forecast versions were issued.” |
| 2:10–3:20 | Chart and interval table | “The actual series is displayed separately. The table shows the timestamp-matched values and selected publication times, but timestamp matching alone does not establish that the measures are comparable. Elexon describes its wind forecast product as hourly and in megawatts, but the reviewed WINDFOR stream definition does not specify whether each value is an hourly average or another hourly statistic.” |
| 3:20–4:10 | Accuracy metric cards and limitation note | “For that reason, the dashboard intentionally withholds MAE, RMSE, bias, WAPE, and a combined forecast-versus-actual chart. The formulas exist and are tested, but publishing values before confirming the forecast interval basis and population compatibility could imply unsupported accuracy.” |
| 4:10–4:30 | Cutoff note and coverage | “The result is a transparent review of forecast vintages and data coverage, with its assumptions visible. It does not claim a market cutoff or validated forecast accuracy.” |

## Part 2 — Technical walkthrough (4:30–9:30)

| Time | Screen | Speaking script |
|---|---|---|
| 4:30–5:00 | Repository tree | “The frontend is a React application built with Vite. The Python backend is FastAPI. The UI calls the `/api/comparison` endpoint for aligned records and coverage, and only requests `/api/metrics` if the backend says metrics are valid.” |
| 5:00–5:55 | `backend/app/services/elexon_client.py` | “The Elexon client requests FUELHH for one settlement date with `fuelType=WIND`. WINDFOR is queried with bounded publication-time parameters; requests have a timeout, HTTP and JSON errors are surfaced, and successful responses use a short process-local cache. There is no API key in the application configuration.” |
| 5:55–6:55 | `backend/app/services/analytics_service.py` | “The service converts the configured Europe/London cutoff to UTC and selects the latest forecast publication no later than that instant for each expected delivery hour. The delivery date is the next UK calendar date, including the January 31 to February 1 boundary. FUELHH half-hour average-MW records are averaged only when both half-hours are present. This aggregation is documented as provisional rather than asserted to match WINDFOR semantics.” |
| 6:55–7:35 | `backend/app/api/routes.py`, schemas, and UI safety state | “Schemas make missing values explicit. Duplicate conflicts, malformed upstream records, network timeouts, and upstream HTTP errors do not become zero-valued success responses. Metrics remain gated because the public evidence reviewed does not resolve the hourly measurement basis or the exact population match.” |
| 7:35–8:25 | Backend test command and test output | “The backend tests use synthetic, clearly identified fixtures and mocked HTTP responses. They cover the API, cutoff selection, duplicates, missing intervals, metric formulas, and every January decision date, including the month boundary. These tests validate our application logic, not the completeness of every live upstream response.” |
| 8:25–9:00 | Docker Compose file/terminal | “Docker Compose runs the API and Nginx-served frontend on loopback-only host ports, waits for backend health, and proxies browser API requests through the frontend container. The frontend build and container configuration can be checked locally without deploying a paid service.” |
| 9:00–9:30 | README limitations and deployment section | “Vercel frontend and Render backend deployment instructions are prepared, but no production URL is claimed until it is deployed and verified. The remaining data question is a written Elexon confirmation of WINDFOR timestamp/interval meaning and population compatibility. Until then, the honest result is coverage and forecast history—not an accuracy score.” |

## Suggested recording sequence

1. Start on the dashboard at desktop width and show the selected date and cutoff.
2. Change the date once, then demonstrate January 31 and its February 1 delivery boundary.
3. Scroll through coverage, publication timestamps, actual-only chart, interval table, and withheld metrics.
4. Switch to the source files and test output for the technical section.
5. Show the Docker Compose health/proxy configuration and finish on README limitations/deployment status.

## Before recording and uploading

- [ ] Run the documented tests/build and use only their actual observed results in narration.
- [ ] Use a reachable local dataset/API for the dashboard; if live Elexon is unavailable, state that clearly and do not present fixtures as live data.
- [ ] Confirm the displayed date, delivery date, cutoff timezone, and API responses.
- [ ] Keep customer and technical sections at or below five minutes each; total video at or below ten minutes.
- [ ] Do not show credentials, private account information, or unpublished secrets.
- [ ] Upload as **Unlisted**, then open the video link in a fresh/incognito browser session and confirm playback.
- [ ] Add the verified video URL to the submission form only after that check.
