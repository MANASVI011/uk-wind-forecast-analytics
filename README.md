# Wind Forecast Analytics

Historical analysis of UK wind generation forecasts for day-ahead purchasing decisions in January 2026. This is an analytics project, not a live electricity-trading system.

## Current status

The React/Vite dashboard calls the FastAPI backend. The backend retrieves historical actuals from FUELHH and publication-versioned wind forecasts from WINDFOR, validates payloads, selects eligible forecasts, aligns values by UTC hourly start, and reports coverage.

MAE, RMSE, mean bias, and WAPE formulas are implemented and unit tested. Their API values are deliberately `null` and marked unavailable: Elexon's Wind Generation product identifies forecast values in MW, but WINDFOR does not document whether each timestamped hourly value is an hourly average or another hourly measure. Actual hourly averages therefore cannot yet be confirmed as like-for-like. The dashboard displays the forecast in MW and clearly withholds the comparison and accuracy metrics.

## Architecture

- `frontend/`: React dashboard built with Vite.
- `backend/app/api/`: validated FastAPI routes and response models.
- `backend/app/services/elexon_client.py`: bounded HTTP requests, timeouts, response parsing, and a short in-memory response cache.
- `backend/app/services/analytics_service.py`: upstream validation, duplicate handling, UTC cutoff selection, half-hour-to-hour actual aggregation, interval alignment, and metric formulas.
- No database is required. The cache is process-local and expires after five minutes.

## Data sources and verified response details

- [FUELHH stream documentation](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream) — generation outturn by fuel type. The docs describe 30-minute average MW values and document `settlementDateFrom`, `settlementDateTo`, and `fuelType`. The backend requests a single delivery settlement date with `fuelType=WIND`; it independently validates/filter-checks WIND records.
- [WINDFOR stream documentation](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream) — generation forecast records. The docs document `publishDateTimeFrom` and `publishDateTimeTo`, and say an unfiltered request returns the latest forecast. The backend uses only bounded publication-time filters, never a settlement-date filter.
- [Elexon Wind Generation product](https://bmrs.elexon.co.uk/wind-generation) — describes NESO's **hourly** wind forecast horizon, says forecasts are for wind farms visible to ESO with operational metering, labels forecast values as a single **MW** figure across the available Power Park Modules, and says its graph compares forecasts with actual outturn derived from Generation by Fuel Type. Its product text says forecast evolution is available via APIs. This is authoritative evidence for the product's MW unit and broad generation scope, but it does not define the WINDFOR stream field's exact within-hour averaging/time convention.

Both streams return timezone-aware ISO timestamps in observed records (UTC `Z`). A verified WINDFOR sample is `{"dataset":"WINDFOR","publishTime":"2026-01-01T22:30:00Z","startTime":"2026-01-02T00:00:00Z","generation":18811}`. A query covering publication times on 1 January 2026 returned 584 rows across eight publication timestamps. The stream schema itself does not include a unit or explain whether `startTime` marks an hour-start average, a point estimate, or another hourly convention.

### What is verified, assumed, and unresolved

**Verified from Elexon documentation or observed API responses**

- FUELHH generation is reported as average MW for half-hour periods, and records are identified by `startTime`, settlement date/period, and fuel type.
- The Wind Generation product describes forecasts as hourly and labels its forecast values in MW. It says the forecast covers wind farms visible to ESO with operational metering and that its outturn comparison is derived from Generation by Fuel Type.
- WINDFOR responses contain `publishTime`, `startTime`, and a numeric `generation` value. The publication timestamp identifies the forecast issue time in observed records; the API documentation provides publication-time filters.
- A January 2026 live-data comparison of the 48-hour request window with a wider publication window returned identical selected versions for all 744 default-cutoff next-day delivery hours. This is evidence for this tested month and cutoff, not a general completeness guarantee.

**Application assumptions (not confirmed market or data definitions)**

- `startTime` is treated as the beginning of a UTC hourly delivery slot for matching and display. Elexon describes an hourly forecast, but the stream documentation does not explicitly define this field as an interval-start timestamp.
- Actuals are converted from two complete FUELHH half-hour average-MW values to an hourly average by taking their arithmetic mean. This does not sum MW into energy; it is a reasonable construction of an hourly average, but the missing WINDFOR interval statistic prevents confirmation that the values are comparable.
- **23:00 Europe/London is a provisional configurable decision cutoff only. It is not a verified day-ahead purchasing, market, or trading deadline.** The app excludes publications after the selected cutoff, but users must not interpret the default as a market rule.

**Unresolved; no compatibility claim is made**

- Does WINDFOR `startTime` denote the start of the hourly delivery interval, and does `generation` represent average MW across that full hour (rather than an instantaneous/representative value or another statistic)?
- Does the WINDFOR population of visible, operationally metered Power Park Modules exactly match the population included in FUELHH `fuelType=WIND`? Elexon documents a relationship between the product chart's forecast and Generation-by-Fuel-Type outturn, but the reviewed public material does not establish exact population, exclusions, or aggregation equivalence for these two API datasets.
- Does the 48-hour history remain complete for other cutoff times, periods, and API conditions? January default-cutoff testing passed, but the public documentation reviewed does not state a pagination or history-completeness guarantee.

The official BMRS/API portal links to [Contact Elexon](https://www.elexon.co.uk/contact/). Use that official contact route to request a written data-definition response (or referral to the responsible BMRS/Insights data owner) for the two compatibility questions above, and clarification of the 23:00 market cutoff if a market deadline is required. The contact page could not be independently read in this environment, so no dedicated mailbox or team name is asserted. No response or confirmation has been received.

## Selection and matching behavior

- The selected date is the purchasing decision date; delivery is the next Europe/London calendar day. A 31 January decision therefore requests 1 February actuals.
- The configurable default cutoff is 23:00 Europe/London. It is provisional and is not a verified market deadline. The backend converts it to UTC and never selects a forecast published after it.
- WINDFOR is requested over a bounded 48-hour lookback ending at the cutoff. The latest returned eligible publication is selected independently for each hourly delivery start. The response reports the lookback, publication count, retrieved rows, selected coverage, and missing intervals.
- The 48-hour window was checked against a wider historical response. For 1–31 January decision dates with the default 23:00 Europe/London cutoff, the wider query returned 24,528 rows across 336 publication times (73 rows per publication). The 48-hour request-range slice returned 18,688 rows across 256 publications (also 73 rows per publication). All 744 next-day hourly delivery starts had a forecast in both sets, and all 744 selected publication timestamps and values were identical between the 48-hour and wider-history selections. This is strong empirical evidence for this month and default cutoff, not a guarantee of upstream completeness, pagination behavior, other cutoff settings, or other periods.
- FUELHH actual half-hour average-MW records are grouped by UTC hour. The two half-hour values are averaged (not summed); an hour is produced only when both expected half-hour records are present. Missing intervals remain null.
- Forecast and actual values are joined on the same timezone-aware UTC hourly start. This is a timestamp-matching assumption, not confirmation of interval semantics. The Elexon product establishes MW units and describes hourly forecasts, but does not clarify whether a timestamped WINDFOR MW value is an hourly average. FUELHH's two half-hour average-MW values are averaged (not summed) to produce an hourly average MW. Until Elexon confirms the WINDFOR time basis and population compatibility, the join is not a validated like-for-like comparison, and API metrics remain null.
- Exact duplicate records are collapsed and counted. Conflicting values for the same actual start or forecast publication/start pair are treated as invalid upstream data and return HTTP 502; they are not silently discarded.

## Accuracy formulas

For matched forecast and actual pairs only, where error is forecast minus actual:

- **MAE** = mean of absolute errors.
- **RMSE** = square root of mean squared errors.
- **Mean bias** = mean error (forecast minus actual).
- **WAPE** = sum of absolute errors divided by sum of absolute actuals, multiplied by 100.

Metrics return null for empty data or a zero WAPE denominator. The formulas are available in the backend, but responses are withheld pending verification of the WINDFOR hourly time basis and its compatibility with hourly averaged FUELHH actuals.

## Local development

Prerequisites: Python 3.10+ and Node.js 20.19+ or 22.12+.

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --env-file .env
```

API: <http://localhost:8000>
Health check: <http://localhost:8000/api/health>
Interactive API docs: <http://localhost:8000/docs>

### Frontend

In another terminal:

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Dashboard: <http://localhost:5173>

Leave `VITE_API_BASE_URL` blank in local development to use the Vite `/api` proxy. When hosting the frontend separately, set it to the backend origin, for example `https://your-api.example.com`.

## Docker Compose

Docker Desktop (or Docker Engine with the Compose plugin) is required.

From the repository root, create a local Compose environment file and start both services:

```bash
cp .env.example .env
docker compose up --build
```

Open the dashboard at <http://localhost:8080>. The backend is also available at <http://localhost:8000>; its health endpoint is <http://localhost:8000/api/health> and its interactive docs are <http://localhost:8000/docs>. Both host ports are bound to loopback (`127.0.0.1`) and are not published on other network interfaces.

The production frontend container serves the built Vite files with Nginx and proxies `/api/` requests to `http://backend:8000` on the Compose network. This intentionally uses the Compose service DNS name, not `localhost` (which would refer to the frontend container itself). The browser calls the frontend's same-origin `/api` path, so no browser-side container hostname or build-time API URL is required. The backend health check gates frontend startup; both containers have health checks.

Useful commands:

```bash
# Start in the background
docker compose up --build -d

# Follow service logs
docker compose logs -f backend frontend

# Check service and health status
docker compose ps

# Rebuild after code or dependency changes
docker compose up --build -d

# Stop and remove the containers/network
docker compose down
```

Compose reads optional overrides from the root `.env` file. `.env.example` lists the supported local settings:

- `FRONTEND_PORT` — host port for the dashboard (default `8080`).
- `BACKEND_PORT` — host port for the API (default `8000`).
- `CORS_ORIGINS` — comma-separated browser origins for direct API access; defaults allow the Vite development server and Compose dashboard.

For example, set `FRONTEND_PORT=8081` if port 8080 is already occupied. Do not put credentials or secrets in this file. Per-service `.dockerignore` files exclude local environment files, caches, dependency folders, and build output from images; `.gitignore` excludes local `.env` files.

Troubleshooting:

- If Compose reports that it cannot connect to the Docker daemon, start Docker Desktop/Docker Engine and retry `docker compose up --build`.
- If a host port is occupied, change `FRONTEND_PORT` or `BACKEND_PORT` in `.env`, then recreate the services with `docker compose up --build -d`.
- If the frontend reports API errors, inspect `docker compose ps` and `docker compose logs backend frontend`. The frontend starts only after the backend health check passes; the proxy target must remain the Compose service name `backend:8000`.
- To force a clean image rebuild without reusing build cache, run `docker compose build --no-cache` followed by `docker compose up`.

## Public deployment preparation

The repository includes configuration for a static Vite frontend on Vercel and the existing Dockerized FastAPI backend on Render. This is deployment preparation only: no account was connected, no repository was published, and no service was provisioned or deployed.

### Platform and current cost considerations

Checked the platforms' official pricing and documentation on 27 October 2026:

- **Vercel Hobby:** $0/month for eligible personal, non-commercial use; Vercel's fair-use policy restricts Hobby to non-commercial personal use. If this hiring assignment/project is considered commercial under Vercel's definition, use Pro at **$20/month**, not Hobby. Usage or taxes may add cost.
- **Render backend:** the configured Starter web service is **$7/month** according to Render's current compute pricing (512 MB RAM, 0.5 CPU). Render Free is $0 but sleeps after 15 minutes without inbound traffic and Render says Free instances are not for production. The recommended always-on backend uses Starter. Usage beyond included limits and taxes may add cost.

Thus estimated baseline is **$7/month** with eligible Vercel Hobby, or **$27/month** with Vercel Pro, before taxes or any additional usage. Prices and plan terms can change; confirm current totals and Vercel Hobby eligibility in each provider's account before creating resources. The Render Blueprint declares a paid Starter service. Creating/deploying it requires a Render account and explicit approval for that recurring cost. Vercel deployment requires account credentials and repository access. Do not proceed without authorization.

### Configuration prepared

- Root [`render.yaml`](./render.yaml) describes a Frankfurt Render Docker web service, health-check path `/api/health`, a paid Starter plan, and a dashboard-supplied `CORS_ORIGINS` value. Automatic deploys are disabled until explicitly enabled in the Render dashboard.
- [`frontend/vercel.json`](./frontend/vercel.json) specifies Vite build settings. Import the `frontend/` directory as the Vercel project root.
- [`frontend/.env.example`](./frontend/.env.example) documents the build-time `VITE_API_BASE_URL`. In Vercel, set it to the backend's public origin, e.g. `https://<render-service>.onrender.com`, with no trailing slash. Vite embeds this value into the static build; changing the variable requires a new deployment.
- Set Render's `CORS_ORIGINS` to the exact Vercel production origin, e.g. `https://<project>.vercel.app` (comma-separated only if allowing additional known origins). Do not use `*`, include a path, or include a trailing slash. Preview deployments have different origins and are not allowed unless explicitly added. This variable is configuration, not a credential; never commit provider tokens or `.env` files.
- The backend binds to the platform-provided `PORT` (default `8000` locally) and its Docker health check targets that port. Render's platform health check also calls `/api/health`.
- Forecast validation and metric/chart safeguards are unchanged; metrics remain withheld until compatibility is confirmed.

### Deployment steps (perform only after repository and cost approval)

1. Review Vercel and Render pricing/terms and confirm whether Vercel Hobby is permitted for this project. Approve the Render Starter recurring charge (currently $7/month) and any applicable Vercel Pro charge (currently $20/month) before provisioning.
2. Publish the repository to the selected Git provider only after approving publication. Keep the repository name `uk-wind-forecast-analytics`; ensure `.env`, `.env.*` other than example files, `.vercel/`, and credentials remain excluded. Do not add provider tokens to repository files.
3. In Render, create a Blueprint from that repository and select the root `render.yaml`. Provide `CORS_ORIGINS` when prompted, using the final Vercel origin. Review the paid Starter plan in the final confirmation screen before creating the service. Record the generated backend URL.
4. In Vercel, import the same repository and set the project root/directory to `frontend`. Select Vite (or use the checked-in `vercel.json` settings), and configure:

   ```text
   VITE_API_BASE_URL=https://<render-service>.onrender.com
   ```

   Use the actual backend origin and do not enter a localhost URL. Trigger a deployment only after verifying the Vercel plan and account eligibility.
5. After Vercel assigns the production domain, add that exact origin to Render's `CORS_ORIGINS`, save the environment update, and manually deploy/restart the backend. Set `autoDeploy` on Render only if automatic deployments are desired and approved.
6. Verify `https://<render-service>.onrender.com/api/health` returns HTTP 200 and `{"status":"ok","service":"wind-forecast-analytics-api"}`. Open the Vercel site, check browser Network/Console for successful `/api/health` and analysis requests, and confirm no CORS errors. Test an analysis request while remembering that metrics are intentionally unavailable.
7. Record the verified frontend/backend URLs only after these checks. No public deployment URL is available yet.

If a deployment fails, inspect Render service events/logs and verify that the container listens on `PORT`, the Render health path is `/api/health`, `VITE_API_BASE_URL` was set before the Vercel build, and `CORS_ORIGINS` exactly matches the deployed site origin.

## API endpoints

The three analysis endpoints accept `decision_date=YYYY-MM-DD` and optional local `cutoff_time=HH:MM` (default `23:00`). Dates outside January 2026 are rejected.

- `GET /api/health` — confirms the API is running.
- `GET /api/forecast` — selected historical forecast values and publication timestamps.
- `GET /api/comparison` — forecast/actual timestamp-aligned hourly records, null gaps, and coverage.
- `GET /api/metrics` — metric values, observation count, and coverage. Metric values are currently null with `metrics_available=false` because the interval basis and population compatibility have not been verified.

Elexon timeouts, HTTP failures, malformed JSON, and invalid records are reported as explicit API errors; no success-shaped fallback data is returned.

## Tests and build

```bash
cd backend
pytest -q
```

```bash
cd frontend
npm run build
npm audit --audit-level=moderate
```

Tests use clearly identified deterministic synthetic fixtures, mock Elexon HTTP responses, and known expected metric examples. They do not present those fixtures as historical results.

## Known limitations

- The WINDFOR product's unit is identified as MW in Elexon's product documentation, but its stream schema does not define whether each hourly value represents an interval average or a point/other measure, nor whether the exact population matches FUELHH WIND. Keep forecast accuracy metrics and the combined forecast-versus-actual chart disabled pending confirmation from Elexon.
- The configurable 23:00 Europe/London cutoff is an application assumption, not a confirmed day-ahead market deadline.
- Forecast retrieval is limited to a 48-hour publication-time lookback. January 2026 default-cutoff selections matched a wider historical response, but Elexon does not specify pagination or an upstream history-completeness guarantee.
- Production deployment configuration is prepared but not applied. The repository has not been published, and no deployment has been created or verified.

## AI disclosure

AI assistance was used to investigate the Elexon API, implement the project scaffolding and data integration, and create tests and documentation. Live Elexon values were retrieved for manual verification; unit-test fixtures are synthetic and labelled as such.
