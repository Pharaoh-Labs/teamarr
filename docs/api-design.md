# Teamarr v2 - API Design

> REST API specification and design principles.

## Design Principles

1. **UI is just another consumer** - No special routes for UI, everything via API
2. **OpenAPI/Swagger first** - Auto-generate docs from code annotations
3. **Consistent naming** - RESTful resources, predictable patterns
4. **Proper status codes** - 200/201/204 for success, 4xx/5xx for errors
5. **JSON everywhere** - Request and response bodies are JSON

---

## Framework Choice

**FastAPI** - chosen for:
- Auto-generated OpenAPI docs at `/docs` (Swagger UI) and `/redoc`
- Pydantic models for request/response validation
- Type hints drive the schema
- Async-ready when needed

---

## URL Structure

```
/api/v1/{resource}
/api/v1/{resource}/{id}
/api/v1/{resource}/{id}/{sub-resource}
```

### Resource Naming

| Resource | Description |
|----------|-------------|
| `/teams` | Team configurations (user-created) |
| `/events` | Sports events |
| `/channels` | Managed EPG channels |
| `/templates` | EPG templates |
| `/epg` | EPG generation endpoints |
| `/providers` | Data provider status |

---

## Core Endpoints

### Teams

```
GET    /api/v1/teams              # List all teams
POST   /api/v1/teams              # Create team
GET    /api/v1/teams/{id}         # Get team
PUT    /api/v1/teams/{id}         # Update team
DELETE /api/v1/teams/{id}         # Delete team
GET    /api/v1/teams/{id}/schedule  # Get team's upcoming events
```

### Events

```
GET    /api/v1/events             # List events (with filters)
GET    /api/v1/events/{id}        # Get single event
```

Query params for list:
- `league` - Filter by league code
- `date` - Filter by date (YYYY-MM-DD)
- `team_id` - Filter by team

### Templates

```
GET    /api/v1/templates          # List all templates
POST   /api/v1/templates          # Create template
GET    /api/v1/templates/{id}     # Get template
PUT    /api/v1/templates/{id}     # Update template
DELETE /api/v1/templates/{id}     # Delete template
POST   /api/v1/templates/import   # Import templates (v1 migration)
GET    /api/v1/templates/export   # Export all templates
```

### EPG Generation

```
POST   /api/v1/epg/generate       # Trigger EPG generation
GET    /api/v1/epg/status         # Get generation status
GET    /api/v1/epg/xmltv          # Get XMLTV output
```

### Channels (Event-based EPG)

```
GET    /api/v1/channels           # List managed channels
POST   /api/v1/channels/reconcile # Reconcile channels with events
DELETE /api/v1/channels/{id}      # Delete channel
```

### System

```
GET    /api/v1/health             # Health check
GET    /api/v1/providers          # List providers and status
```

---

## Request/Response Models

### Standard Response Envelope

Success:
```json
{
  "data": { ... },
  "meta": {
    "total": 100,
    "page": 1,
    "per_page": 20
  }
}
```

Error:
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid team_id format",
    "details": {
      "field": "team_id",
      "value": "abc"
    }
  }
}
```

### Team Model

```python
class TeamCreate(BaseModel):
    team_name: str
    league: str
    provider_team_id: str
    template_id: int
    active: bool = True

class TeamResponse(BaseModel):
    id: int
    team_name: str
    league: str
    provider_team_id: str
    template_id: int
    active: bool
    created_at: datetime
    updated_at: datetime
```

### Event Model

```python
class EventResponse(BaseModel):
    id: str
    provider: str
    name: str
    short_name: str
    start_time: datetime
    home_team: TeamBrief
    away_team: TeamBrief
    status: EventStatus
    league: str
    venue: Optional[Venue]
    broadcasts: list[str]
```

---

## Status Codes

| Code | Usage |
|------|-------|
| 200 | Success (GET, PUT) |
| 201 | Created (POST) |
| 204 | No content (DELETE) |
| 400 | Bad request / validation error |
| 404 | Resource not found |
| 409 | Conflict (duplicate) |
| 500 | Internal server error |

---

## OpenAPI Integration

FastAPI auto-generates OpenAPI spec. Enhance with:

```python
from fastapi import FastAPI

app = FastAPI(
    title="Teamarr API",
    description="Sports EPG generation service",
    version="2.0.0",
    docs_url="/docs",      # Swagger UI
    redoc_url="/redoc",    # ReDoc
    openapi_url="/openapi.json"
)

@app.get(
    "/api/v1/teams",
    response_model=list[TeamResponse],
    summary="List all teams",
    tags=["Teams"]
)
async def list_teams():
    ...
```

---

## Authentication

For v2 initial release: **No authentication** (local network assumption).

Future: API key header for external access.

```
Authorization: Bearer <api_key>
```

---

## Pagination

List endpoints support:

```
GET /api/v1/teams?page=1&per_page=20
```

Response includes meta:
```json
{
  "data": [...],
  "meta": {
    "total": 150,
    "page": 1,
    "per_page": 20,
    "pages": 8
  }
}
```

---

## WebSocket (Future)

For live updates during EPG generation:

```
WS /api/v1/epg/ws
```

Messages:
```json
{"type": "progress", "percent": 45, "message": "Processing NFL..."}
{"type": "complete", "programmes": 1234}
{"type": "error", "message": "ESPN API unavailable"}
```

---

## Example: Full Team CRUD

```bash
# Create team
curl -X POST http://localhost:8000/api/v1/teams \
  -H "Content-Type: application/json" \
  -d '{"team_name": "Detroit Lions", "league": "nfl", "provider_team_id": "8", "template_id": 1}'

# Response: 201 Created
{
  "data": {
    "id": 1,
    "team_name": "Detroit Lions",
    "league": "nfl",
    "provider_team_id": "8",
    "template_id": 1,
    "active": true,
    "created_at": "2024-12-11T10:00:00Z",
    "updated_at": "2024-12-11T10:00:00Z"
  }
}

# Get team schedule
curl http://localhost:8000/api/v1/teams/1/schedule

# Response: 200 OK
{
  "data": [
    {
      "id": "401547679",
      "provider": "espn",
      "name": "Detroit Lions at Chicago Bears",
      "start_time": "2024-12-08T18:00:00Z",
      ...
    }
  ]
}
```
