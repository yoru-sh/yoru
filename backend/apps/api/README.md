# SaaS API

Production-ready FastAPI backend with authentication, subscriptions, notifications, and RBAC.

## Table of Contents

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Authentication](#authentication)
- [API Documentation](#api-documentation)
- [Endpoints Overview](#endpoints-overview)
- [Development Guide](#development-guide)
- [Testing](#testing)

## Quick Start

### 1. Setup Environment

```bash
# Copy environment variables
cp .env.example .env

# Edit .env with your Supabase credentials
# SUPABASE_URL=your_supabase_url
# SUPABASE_ANON_KEY=your_anon_key
```

### 2. Start the API

```bash
# Using Docker Compose (recommended)
docker-compose -f docker/compose/docker-compose.yml up api

# Or run locally
cd apps/api
uvicorn main:app --reload --port 8000
```

### 3. Access Documentation

- **Swagger UI**: http://localhost:8000/api/docs
- **ReDoc**: http://localhost:8000/api/redoc
- **OpenAPI Schema**: http://localhost:8000/api/openapi.json

## Architecture

```
apps/api/
├── main.py                 # FastAPI app entry point
└── api/
    ├── dependencies/       # FastAPI dependencies (auth, features)
    ├── exceptions/         # Custom exceptions
    ├── middleware/         # Request middlewares
    ├── models/            # Pydantic models
    ├── routers/           # API endpoints
    └── services/          # Business logic
```

### Key Design Principles

1. **Per-Request Service Instantiation**: Services are created per request with user tokens
2. **RLS Security**: Row Level Security policies in Supabase for data protection
3. **Correlation IDs**: Request tracing across all operations
4. **Structured Logging**: LoggingController with context for all operations

## Authentication

### JWT-Based Authentication

All protected endpoints require a Bearer token:

```bash
Authorization: Bearer <your_access_token>
```

### Getting a Token

**Sign Up:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "SecureP@ssw0rd",
    "first_name": "John",
    "last_name": "Doe"
  }'
```

**Sign In:**
```bash
curl -X POST http://localhost:8000/api/v1/auth/signin \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "SecureP@ssw0rd"
  }'
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600,
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "role": "user"
  }
}
```

### Refresh Token

```bash
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "YOUR_REFRESH_TOKEN"
  }'
```

## API Documentation

### Interactive Documentation

Visit **http://localhost:8000/api/docs** for:
- Interactive API explorer (Swagger UI)
- Try out endpoints directly from the browser
- View request/response schemas
- See example requests and responses

### ReDoc Alternative

Visit **http://localhost:8000/api/redoc** for:
- Clean, three-panel documentation
- Better for reading and sharing
- Mobile-friendly interface

## Endpoints Overview

### Authentication (`/api/v1/auth`)
- `POST /signup` - Register a new user
- `POST /signin` - Sign in with email/password
- `POST /signout` - Sign out current user
- `POST /refresh` - Refresh access token

### User Profile (`/api/v1/me`)
- `GET /me` - Get current user profile
- `PATCH /me` - Update profile
- `GET /me/subscription` - Get active subscription
- `GET /me/grants` - Get active grants
- `GET /me/notifications` - List notifications
- `PATCH /me/notifications/{id}/read` - Mark as read

### Plans (`/api/v1/plans`)
- `GET /plans` - List all active plans (public)
- `GET /plans/{id}` - Get plan details with features (public)

### Subscriptions (`/api/v1/subscriptions`)
- `POST /subscriptions` - Create subscription
- `POST /subscriptions/{id}/cancel` - Cancel subscription

### Notifications (`/api/v1/me/notifications`)
- `GET /me/notifications` - List user notifications (paginated)
- `GET /me/notifications/unread/count` - Get unread count
- `PATCH /me/notifications/{id}/read` - Mark as read
- `PATCH /me/notifications/read-all` - Mark all as read
- `DELETE /me/notifications/{id}` - Delete notification

### Admin Endpoints

**Requires `admin` role in user profile.**

- `POST /api/v1/admin/notifications/broadcast` - Broadcast notification
- `POST /api/v1/admin/plans` - Create plan
- `POST /api/v1/admin/features` - Create feature
- `POST /api/v1/admin/grants` - Create grant
- `GET /api/v1/admin/grants` - List all grants

## Development Guide

### Adding a New Router

1. Create router class in `api/routers/`:

```python
from fastapi import APIRouter, Depends
from apps.api.api.dependencies.auth import get_current_user_token

class MyRouter:
    def __init__(self):
        self.router = APIRouter(prefix="/my-endpoint", tags=["my-tag"])
        self._setup_routes()

    def initialize_services(self):
        pass

    def get_router(self) -> APIRouter:
        return self.router

    def _setup_routes(self):
        self.router.get("")(self.list_items)

    async def list_items(
        self,
        token: str = Depends(get_current_user_token),
        correlation_id: str = Depends(get_correlation_id),
    ):
        service = MyService(access_token=token)
        return await service.list_items(correlation_id)
```

2. Register in `main.py`:

```python
from apps.api.api.routers.my_router import MyRouter

my_router = MyRouter()
my_router.initialize_services()
app.include_router(my_router.get_router(), prefix="/api/v1")
```

### Adding a New Service

1. Create service in `api/services/`:

```python
from libs.supabase.supabase import SupabaseManager
from libs.log_manager.controller import LoggingController

class MyService:
    def __init__(
        self,
        access_token: str | None = None,
        supabase: SupabaseManager | None = None,
        logger: LoggingController | None = None,
    ):
        self.supabase = supabase or SupabaseManager(access_token=access_token)
        self.logger = logger or LoggingController(app_name="MyService")

    async def list_items(self, correlation_id: str):
        context = {
            "operation": "list_items",
            "component": "MyService",
            "correlation_id": correlation_id,
        }
        self.logger.log_info("Listing items", context)

        try:
            items = self.supabase.query_records(
                "my_table",
                correlation_id=correlation_id
            )
            return items
        except Exception as e:
            context["error"] = str(e)
            self.logger.log_error("Failed to list items", context)
            raise
```

### CRITICAL: Token Passing Rule

**Every service MUST receive the user's access token:**

```python
# ✅ CORRECT - Per-request instantiation with token
async def my_endpoint(
    token: str = Depends(get_current_user_token),
    correlation_id: str = Depends(get_correlation_id),
):
    service = MyService(access_token=token)
    return await service.do_something(correlation_id)

# ❌ WRONG - Singleton service without token
def initialize_services(self):
    self.service = MyService()  # NO! RLS policies won't work

async def my_endpoint(self):
    return await self.service.do_something()  # Won't have user context
```

**Why this matters:**
- Supabase uses Row Level Security (RLS) policies
- RLS policies check `auth.uid()` to filter data by user
- Without the user's token, queries use the anonymous key
- This can cause permission errors or data leaks

## Testing

### Manual Testing with Curl

```bash
# 1. Get a token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/signin \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"test123"}' \
  | jq -r '.access_token')

# 2. Test an authenticated endpoint
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/me

# 3. Test with query parameters
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/me/notifications?page=1&page_size=10"
```

### Using the Interactive Docs

1. Go to http://localhost:8000/api/docs
2. Click "Authorize" button (top right)
3. Enter: `Bearer YOUR_ACCESS_TOKEN`
4. Click "Authorize" then "Close"
5. Try out any endpoint with the "Try it out" button

### Running Tests

```bash
# Unit tests
pytest apps/api/tests/unit/

# Integration tests
pytest apps/api/tests/integration/

# With coverage
pytest --cov=apps/api apps/api/tests/
```

## Error Handling

### Standard Error Response

```json
{
  "detail": "Error message here",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Common HTTP Status Codes

- `200 OK` - Successful GET/PATCH
- `201 Created` - Successful POST
- `204 No Content` - Successful DELETE
- `400 Bad Request` - Validation error
- `401 Unauthorized` - Missing or invalid token
- `403 Forbidden` - Insufficient permissions
- `404 Not Found` - Resource not found
- `500 Internal Server Error` - Server error

## Environment Variables

```bash
# Required
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your_anon_key

# Optional
PORT=8000
ENVIRONMENT=development
LOG_LEVEL=INFO
REDIS_URL=redis://localhost:6379
```

## Deployment

### Docker Production Build

```bash
# Build
docker build -f docker/api/Dockerfile -t saas-api:latest .

# Run
docker run -p 8000:8000 \
  -e SUPABASE_URL=your_url \
  -e SUPABASE_ANON_KEY=your_key \
  saas-api:latest
```

### Health Check

```bash
curl http://localhost:8000/health
```

## Best Practices

### Security
- ✅ Always use `get_current_user_token` dependency
- ✅ Pass tokens to service constructors
- ✅ Validate input with Pydantic models
- ✅ Use RLS policies in Supabase
- ❌ Never expose sensitive data in logs
- ❌ Never commit `.env` files

### Performance
- ✅ Use async/await for I/O operations
- ✅ Add database indexes for common queries
- ✅ Use pagination for list endpoints
- ✅ Cache frequently accessed data
- ❌ Avoid N+1 queries

### Logging
- ✅ Include correlation_id in all logs
- ✅ Log errors with full context
- ✅ Use appropriate log levels
- ❌ Don't log sensitive data (passwords, tokens)

## Support

- **Documentation**: http://localhost:8000/api/docs
- **Issues**: Create an issue in the repository
- **Cursor Rules**: See `.cursor/rules/` for AI-assisted development rules

## License

MIT
