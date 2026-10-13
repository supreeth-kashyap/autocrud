import asyncio
import json

import pytest
from sqlalchemy import create_engine

from autocrud.config import ConfigError, get_config
from autocrud.generator import generate_app
from examples.demo_app.models import Base

API_KEY = "test-secret"

def call(app, method, path, body=None, query=""):
    """Sends one request straight to the ASGI app; returns (status, parsed JSON or None)."""
    payload = json.dumps(body).encode() if body is not None else b""
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
        "root_path": "", "query_string": query.encode(),
        "headers": [(b"x-api-key", API_KEY.encode()), (b"content-type", b"application/json")],
        "client": ("testclient", 50000), "server": ("testserver", 80),
    }
    incoming = [{"type": "http.request", "body": payload, "more_body": False}]
    sent = []

    async def receive():
        return incoming.pop(0) if incoming else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    data = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return status, (json.loads(data) if data else None)

def routes(app, prefix):
    return {
        (method, route.path)
        for route in app.routes if route.path.startswith(prefix)
        for method in route.methods
    }

@pytest.fixture
def config(tmp_path):
    database = f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(database)
    Base.metadata.create_all(engine)
    engine.dispose()
    return {
        "database": database,
        "models_module": "examples.demo_app.models",
        "expose": {"models": {
            "User": ["list", "get", "create", "update", "delete"],
            "Order": ["list"],
        }},
        "security": {"api_key": API_KEY},
    }

# Test to ensure the YAML configuration is loaded correctly
def test_config_loading():
    config = get_config('examples/autocrud.yml')
    assert config['database'] == 'sqlite:///dev.db'
    assert config['models_module'] == 'examples.demo_app.models'
    assert 'User' in config['expose']['models']

# Test that the example config produces exactly its configured routes
def test_app_generation():
    app = generate_app(get_config('examples/autocrud.yml'))
    assert routes(app, "/users") == {
        ("GET", "/users"), ("GET", "/users/{pk}"), ("POST", "/users"),
    }
    assert routes(app, "/orders") == {("GET", "/orders"), ("GET", "/orders/{pk}")}
    assert ("GET", "/functions/get_active_users") in routes(app, "/functions")

def test_unknown_model_lists_mapped_classes(config):
    config["expose"]["models"] = {"Ghost": ["list"]}
    with pytest.raises(ConfigError) as e:
        generate_app(config)
    assert "Unknown model(s) in expose.models: Ghost" in str(e.value)
    assert "Mapped classes available in module 'examples.demo_app.models': Order, User" in str(e.value)

# Test that an operation not in the config has no route
def test_unconfigured_operations_are_absent(config):
    app = generate_app(config)
    assert routes(app, "/orders") == {("GET", "/orders")}
    assert call(app, "GET", "/orders/1")[0] == 404
    assert call(app, "POST", "/orders", {"amount": 3})[0] == 405

# Test that /docs gets typed request and response schemas
def test_openapi_schemas_are_typed(config):
    schemas = generate_app(config).openapi()["components"]["schemas"]
    create = schemas["UserCreate"]
    assert "id" not in create["properties"]
    assert set(create["required"]) == {"name", "email"}
    assert create["properties"]["name"]["type"] == "string"
    assert "required" not in schemas["UserUpdate"]
    assert schemas["UserRead"]["properties"]["id"]["type"] == "integer"

def test_create_and_get(config):
    app = generate_app(config)
    status, user = call(app, "POST", "/users", {"name": "Ada", "email": "ada@example.com"})
    assert status == 201
    assert user == {"id": 1, "name": "Ada", "email": "ada@example.com"}
    assert call(app, "GET", "/users/1") == (200, user)

def test_create_rejects_missing_required_field(config):
    app = generate_app(config)
    assert call(app, "POST", "/users", {"name": "Ada"})[0] == 422
    assert call(app, "GET", "/users")[1] == []

def test_get_missing_row_returns_404(config):
    status, body = call(generate_app(config), "GET", "/users/42")
    assert status == 404
    assert body == {"detail": "User 42 not found."}

def test_update(config):
    app = generate_app(config)
    call(app, "POST", "/users", {"name": "Ada", "email": "ada@example.com"})
    status, user = call(app, "PATCH", "/users/1", {"name": "Ada L."})
    assert status == 200
    assert user == {"id": 1, "name": "Ada L.", "email": "ada@example.com"}
    assert call(app, "GET", "/users/1")[1]["name"] == "Ada L."
    assert call(app, "PATCH", "/users/1", {"name": None})[0] == 422
    assert call(app, "PATCH", "/users/42", {"name": "x"})[0] == 404

def test_delete(config):
    app = generate_app(config)
    call(app, "POST", "/users", {"name": "Ada", "email": "ada@example.com"})
    assert call(app, "DELETE", "/users/1") == (204, None)
    assert call(app, "GET", "/users/1")[0] == 404
    assert call(app, "DELETE", "/users/1")[0] == 404

def test_list_limit_and_offset(config):
    app = generate_app(config)
    for i in range(5):
        call(app, "POST", "/users", {"name": f"u{i}", "email": f"u{i}@example.com"})
    assert [u["id"] for u in call(app, "GET", "/users")[1]] == [1, 2, 3, 4, 5]
    assert [u["id"] for u in call(app, "GET", "/users", query="limit=2&offset=1")[1]] == [2, 3]
    assert call(app, "GET", "/users", query="offset=5")[1] == []
    assert call(app, "GET", "/users", query="limit=1001")[0] == 422
    assert call(app, "GET", "/users", query="limit=0")[0] == 422
