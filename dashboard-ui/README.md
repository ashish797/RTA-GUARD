# RTA-GUARD Dashboard (Phase 8)

Production React dashboard for RTA-GUARD AI Agent Security.

## Tech Stack

- **React 18** + TypeScript
- **Vite 6** — fast builds, HMR
- **Tailwind CSS** — dark theme by default
- **Recharts** — charts and data visualization
- **React Router v6** — client-side routing
- **TanStack Query** — data fetching and caching
- **Lucide React** — icons

## Quick Start

```bash
# Install dependencies
npm install

# Development (with API proxy to localhost:8000)
npm run dev

# Production build
npm run build

# Preview production build
npm run preview
```

## Configuration

Environment variables (`.env` or `.env.local`):

```env
VITE_API_URL=http://localhost:8000    # Backend API URL (default: same origin)
VITE_WS_URL=ws://localhost:8000/ws    # WebSocket URL (default: ws://host:8000/ws)
```

## Pages (15)

| Route | Page | Description |
|-------|------|-------------|
| `/login` | Login | Auth + SSO login |
| `/` | Dashboard | Overview stats, charts, live feed |
| `/events` | Events | Filterable event table with details |
| `/sessions` | Sessions | Killed sessions, drill-down, reset |
| `/check` | Rules & Check | Interactive rule testing |
| `/conscience` | Conscience | Agent health, drift, anomaly |
| `/drift` | Drift Analysis | Component breakdown, drift recording |
| `/escalation` | Escalation | Policies, history, evaluation |
| `/tenants` | Tenants | Multi-tenant management |
| `/rbac` | RBAC | Role-based access control |
| `/webhooks` | Webhooks | Webhook CRUD and testing |
| `/brahmanda` | Brahmanda | Ground truth verification |
| `/reports` | Reports | Compliance report generation |
| `/sla` | SLA & Limits | SLA monitoring, rate limiting |
| `/settings` | Settings | Auth config, SSO providers |

## Features

- 🔴 **Real-time WebSocket** live event feed
- 🌙 **Dark theme** by default, light toggle
- 📱 **Responsive** — mobile sidebar collapse
- 🔐 **Auth-aware** — Bearer token + SSO support
- 📊 **Charts** — violation breakdown, drift gauges, trend lines
- 🔍 **Filter & search** — across all data tables
- ⚡ **Auto-refresh** — configurable polling intervals
