# Dashboard.Web

React + TypeScript + Vite front-end for `Dashboard.Service`. Provides four pages:

1. **Market** (`/market`) - K-line chart + fundamentals for the selected symbol.
2. **Backtest** (`/backtest`) - schema-driven parameter form + live status polling.
3. **History** (`/history`) - list of past runs, click-through to results.
4. **Compare** (`/compare`) - side-by-side PnL curves from multiple runs.

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │   React App (React Router)              │
                    │   - SymbolContext (top-bar selector)    │
                    │   - 4 route components (src/pages/*)    │
                    └────────────┬────────────────────────────┘
                                 │  React Query (src/api/client.ts)
                                 ▼
                    ┌─────────────────────────────────────────┐
                    │   Dashboard.Service  (FastAPI :8080)    │
                    └─────────────────────────────────────────┘
```

The front-end NEVER talks to ClickHouse, PostgreSQL, Kafka, or any service other than Dashboard.Service.

## Key UX patterns

- **Schema-driven param form**: `ParamForm` reads `params_schema` from `GET /api/strategies` and renders the right input per parameter type. Adding a new strategy class with a `PARAMS_SCHEMA` class attribute makes it appear here automatically.
- **Bloomberg-style symbol selector**: the top-bar search box drives a `SymbolContext` that persists across page navigation. Clicking a trade in the results page jumps to MarketView with the symbol pre-selected.
- **Polling**: backtest status polls every 2s via React Query's `refetchInterval`. Polling stops on terminal status (`completed`/`error`/`stopped`).

## Local development

```bash
cd react/dashboard-web
npm install
npm run dev   # serves on http://localhost:5173
```

The dev server proxies `/api` to `http://localhost:8080` (Dashboard.Service). Override with `VITE_DASHBOARD_API=http://host:port`.

## Production build

```bash
npm run build   # outputs to dist/
```

The Dockerfile serves `dist/` via nginx on port 80, with `/api/*` proxied to `dashboard-service:8080`.
