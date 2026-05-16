import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.database import Base, engine


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create tables before each test, drop after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_root(client: AsyncClient):
    resp = await client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "UniCalendar API"


@pytest.mark.asyncio
async def test_register(client: AsyncClient):
    resp = await client.post("/api/auth/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "testpass123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "testuser"
    assert data["email"] == "test@example.com"


@pytest.mark.asyncio
async def test_register_duplicate(client: AsyncClient):
    await client.post("/api/auth/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "testpass123",
    })
    resp = await client.post("/api/auth/register", json={
        "username": "testuser",
        "email": "test@a.com",
        "password": "testpass123",
    })
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_login(client: AsyncClient):
    await client.post("/api/auth/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "testpass123",
    })
    resp = await client.post("/api/auth/login", json={
        "login": "testuser",
        "password": "testpass123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "Bearer"


@pytest.mark.asyncio
async def test_login_invalid(client: AsyncClient):
    resp = await client.post("/api/auth/login", json={
        "login": "nobody",
        "password": "wrongpassword",
    })
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_unauthenticated(client: AsyncClient):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_authenticated(client: AsyncClient):
    await client.post("/api/auth/register", json={
        "username": "testuser",
        "email": "test@example.com",
        "password": "testpass123",
    })
    login_resp = await client.post("/api/auth/login", json={
        "login": "testuser",
        "password": "testpass123",
    })
    token = login_resp.json()["access_token"]

    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["username"] == "testuser"


@pytest.mark.asyncio
async def test_create_event(client: AsyncClient):
    # Register + login
    await client.post("/api/auth/register", json={
        "username": "evtuser",
        "email": "evt@example.com",
        "password": "testpass123",
    })
    login_resp = await client.post("/api/auth/login", json={
        "login": "evtuser",
        "password": "testpass123",
    })
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create event
    resp = await client.post("/api/events/", json={
        "title": "Test Event",
        "start": "2026-05-20T09:00:00",
        "end": "2026-05-20T10:00:00",
        "description": "A test event",
        "importance": "high",
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["event"]["title"] == "Test Event"
    assert data["event"]["importance"] == "high"

    # List events
    resp = await client.get("/api/events/", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


@pytest.mark.asyncio
async def test_create_todo(client: AsyncClient):
    await client.post("/api/auth/register", json={
        "username": "todouser",
        "email": "todo@example.com",
        "password": "testpass123",
    })
    login_resp = await client.post("/api/auth/login", json={
        "login": "todouser",
        "password": "testpass123",
    })
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/api/todos/", json={
        "title": "Test Todo",
        "description": "Do the thing",
        "importance": "high",
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["todo"]["title"] == "Test Todo"


@pytest.mark.asyncio
async def test_create_reminder(client: AsyncClient):
    await client.post("/api/auth/register", json={
        "username": "remuser",
        "email": "rem@example.com",
        "password": "testpass123",
    })
    login_resp = await client.post("/api/auth/login", json={
        "login": "remuser",
        "password": "testpass123",
    })
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/api/reminders/", json={
        "title": "Test Reminder",
        "trigger_time": "2026-05-20T14:00:00",
        "priority": "high",
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["reminder"]["title"] == "Test Reminder"


@pytest.mark.asyncio
async def test_create_event_group(client: AsyncClient):
    await client.post("/api/auth/register", json={
        "username": "grpuser",
        "email": "grp@example.com",
        "password": "testpass123",
    })
    login_resp = await client.post("/api/auth/login", json={
        "login": "grpuser",
        "password": "testpass123",
    })
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/api/event-groups/", json={
        "name": "Work",
        "color": "#ff0000",
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["group"]["name"] == "Work"


@pytest.mark.asyncio
async def test_oauth_client_registration(client: AsyncClient):
    await client.post("/api/auth/register", json={
        "username": "oauthuser",
        "email": "oauth@example.com",
        "password": "testpass123",
    })
    login_resp = await client.post("/api/auth/login", json={
        "login": "oauthuser",
        "password": "testpass123",
    })
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/api/oauth/clients", json={
        "client_name": "My App",
        "redirect_uris": ["https://myapp.local/callback"],
        "grant_types": ["authorization_code", "refresh_token"],
        "default_scopes": ["read:events", "read:todos"],
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["client_name"] == "My App"
    assert "client_id" in data
    assert "client_secret" in data
    assert data["redirect_uris"] == ["https://myapp.local/callback"]

    # List clients
    resp = await client.get("/api/oauth/clients", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


@pytest.mark.asyncio
async def test_legacy_api_login(client: AsyncClient):
    """Test old-style DRF token login endpoint."""
    await client.post("/api/auth/register", json={
        "username": "legacyuser", "email": "legacy@example.com", "password": "testpass123",
    })

    # Old-style login (username + password)
    resp = await client.post("/api/v0/api/auth/login/", json={
        "username": "legacyuser", "password": "testpass123",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "token" in data
    assert data["username"] == "legacyuser"


@pytest.mark.asyncio
async def test_legacy_token_header_auth(client: AsyncClient):
    """Test that old 'Authorization: Token <jwt>' header works."""
    await client.post("/api/auth/register", json={
        "username": "tokenuser", "email": "token@example.com", "password": "testpass123",
    })
    login_resp = await client.post("/api/auth/login", json={
        "login": "tokenuser", "password": "testpass123",
    })
    token = login_resp.json()["access_token"]

    # Old-style Token header
    resp = await client.get("/api/auth/me", headers={"Authorization": f"Token {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "tokenuser"


@pytest.mark.asyncio
async def test_legacy_events_get(client: AsyncClient):
    """Test old-style GET /get_calendar/events/ path."""
    await client.post("/api/auth/register", json={
        "username": "legaevt", "email": "legaevt@example.com", "password": "testpass123",
    })
    login_resp = await client.post("/api/auth/login", json={
        "login": "legaevt", "password": "testpass123",
    })
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/api/v0/get_calendar/events/", headers=headers)
    assert resp.status_code == 200
    assert "events" in resp.json()


@pytest.mark.asyncio
async def test_legacy_reminders_create(client: AsyncClient):
    """Test old-style POST /api/reminders/create/ path."""
    await client.post("/api/auth/register", json={
        "username": "legarem", "email": "legarem@example.com", "password": "testpass123",
    })
    login_resp = await client.post("/api/auth/login", json={
        "login": "legarem", "password": "testpass123",
    })
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/api/v0/api/reminders/create/", json={
        "title": "Legacy Reminder",
        "trigger_time": "2026-06-01T10:00:00",
    }, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["reminder"]["title"] == "Legacy Reminder"


@pytest.mark.asyncio
async def test_legacy_todos_get(client: AsyncClient):
    """Test old-style GET /api/todos/ path."""
    await client.post("/api/auth/register", json={
        "username": "legatodo", "email": "legatodo@example.com", "password": "testpass123",
    })
    login_resp = await client.post("/api/auth/login", json={
        "login": "legatodo", "password": "testpass123",
    })
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/api/v0/api/todos/", headers=headers)
    assert resp.status_code == 200
    assert "todos" in resp.json()
