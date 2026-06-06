# agent/config/registry/

Machine-readable registry cataloguing every event, metric, and action exposed
by the Bumba bridge. Per Plan E Objective 5 and E-O6.

## Directory layout

```
agent/config/registry/
├── README.md           ← this file
├── _schema.py          ← Pydantic models (EventEntry, MetricEntry, ActionEntry)
├── events/             ← one YAML file per category group
│   ├── actionable-hitl.yaml    ← directive + surface lifecycle events
│   ├── agents.yaml             ← department lifecycle events
│   ├── deploy.yaml             ← deploy lifecycle events
│   ├── health-status.yaml      ← bridge health, failure, trust events
│   ├── hook-lifecycle.yaml     ← Claude Code CLI hook.* events (E2.3)
│   ├── jobs.yaml               ← job search pipeline events
│   ├── sample.yaml             ← loader test fixture (not a real entry)
│   └── work-progress.yaml      ← WorkOrder, pipeline, task events
├── metrics/
│   ├── agents.yaml             ← few-shot ingest counters
│   ├── health-status.yaml      ← core bridge counters
│   ├── sample.yaml             ← loader test fixture
│   ├── services.yaml           ← /healthz component metrics
│   └── work-progress.yaml      ← Z3 dispatcher/executor counters
└── actions/
    ├── actionable-hitl.yaml    ← escalation, HITL, directives, surfaces
    ├── agents.yaml             ← agent/session management, Z4 VAPI
    ├── cost-resources.yaml     ← cost, trust endpoints
    ├── health-status.yaml      ← healthz, heartbeat, metrics, traces
    ├── memory.yaml             ← knowledge store endpoints
    ├── sample.yaml             ← loader test fixture
    ├── services.yaml           ← Z4 observability (feature-flagged)
    └── work-progress.yaml      ← tasks, WorkOrder, webhooks
```

Files matching `sample*.yaml` are loader fixtures; they are exempted from the
E2.6 CI gate that enforces every new route/event/metric has a registry entry.

## E2.5 category distribution (populated by Sprint E2.5)

| Category | Events | Actions | Metrics | Total |
|---|---|---|---|---|
| Agents | 16 | 10 | 4 | 30 |
| Work & Progress | 15 | 11 | 3 | 29 |
| Actionable/HITL | 4 | 15 | 0 | 19 |
| Services | 0 | 14 | 13 | 27 |
| Health & Status | 11 | 6 | 3 | 20 |
| Jobs | 3 | 0 | 0 | 3 |
| Cost & Resources | 0 | 2 | 0 | 2 |
| Memory | 0 | 2 | 1 | 3 |
| **Total** | **49** | **60** | **24** | **133** |

Notes:
- `hook.*` events (13 entries) are pre-registered per E2.3 scope; `HooksTelemetrySubscriber` adds them to `EVENT_TYPES` when E2.3 lands.
- Z4 observability endpoints (14 entries in `actions/services.yaml`) are registered with `[feature_flag_required: z4_observability_tool_tracker_enabled]` in their description.
- Peer-coordination routes (`peer_api.py` 9 endpoints) are excluded — not currently wired into `BridgeApp` per `agent/CLAUDE.md`.

## Schema

All three entry types share five base fields from Plan E Obj 5:

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | str | yes | Human-readable label (1–120 chars) |
| `category` | Category | yes | One of the eight values below |
| `description` | str | no | Up to 400 chars |
| `source_module` | str | yes | Dotted module path, e.g. `bridge.cost_tracker` |
| `schema_ref` | str | no | JSONSchema $id, dataclass name, or inline description |

### EventEntry

Additional fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| `event_type` | str | yes | String published via `EventBus.publish(Event(event_type=...))` |
| `access_method` | enum | no | `push:event_bus` (default) or `ws:/ws/events` |

### MetricEntry

Additional fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| `metric_name` | str | yes | Key used in `GET /api/metrics/{name}` |
| `access_method` | enum | no | `pull:/api/metrics/{name}` (default) or `pull:/healthz` |

### ActionEntry

Additional fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| `method` | enum | yes | `GET`, `POST`, `PUT`, `DELETE`, or `WS` |
| `path` | str | yes | HTTP/WS path starting with `/`, e.g. `/api/cost` |
| `auth` | enum | no | `bearer` (default) or `none` |
| `access_method` | enum | no | `rest` (default) or `ws` |

## The eight categories

| Enum value | YAML string |
|---|---|
| `HEALTH_STATUS` | `Health & Status` |
| `WORK_PROGRESS` | `Work & Progress` |
| `ACTIONABLE_HITL` | `Actionable/HITL` |
| `COST_RESOURCES` | `Cost & Resources` |
| `MEMORY` | `Memory` |
| `AGENTS` | `Agents` |
| `SERVICES` | `Services` |
| `JOBS` | `Jobs` |

## YAML file format

Each YAML file in `events/`, `metrics/`, or `actions/` is a mapping of
entry-key → fields. One or many entries per file — use one file per logical
group (e.g. `cost.yaml` for all cost-related entries).

```yaml
# events/work-progress.yaml
workorder_created:
  kind: event
  name: WorkOrder Created
  category: "Work & Progress"
  description: Fires when a WorkOrder transitions from external spec to bridge-tracked state.
  source_module: bridge.work_order_store
  schema_ref: bridge.work_order.WorkOrder
  event_type: workorder.created
  access_method: push:event_bus
```

## Loader

`agent/bridge/registry_loader.py` — `RegistryLoader.load_all(root)` walks
the three subdirectories, validates each entry via Pydantic, and returns a
`RegistryIndex` dataclass. Validation failures are recorded in
`RegistryIndex.errors`; the loader never raises so boot is not blocked.

Called at `BridgeApp` startup; entry counts + error count are logged.

## Adding entries

1. Add a new YAML file (or append to an existing file) in the appropriate
   subdirectory.
2. Each top-level key is an entry. Key should be snake_case and unique within
   the subdirectory.
3. E2.6 CI gate will enforce that every new route/event/metric has an entry.
