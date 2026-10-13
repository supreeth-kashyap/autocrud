import asyncio
import json
import logging

import pytest
from sqlalchemy import create_engine

from autocrud.config import ConfigError, get_config, validate_config
from autocrud.generator import generate_app
from autocrud.security import API_KEY_ENV_VAR, SlidingWindowRateLimiter
from examples.demo_app.models import Base

API_KEY = "unit-test-key"

def request(app, method, path, body=None, query="", api_key=API_KEY, client="testclient"):
    """Sends one request straight to the ASGI app; returns (status, headers, parsed JSON or None).
    api_key=None sends no X-API-Key header."""
    payload = json.dumps(body).encode() if body is not None else b""
    headers = [(b"content-type", b"application/json")]
    if api_key is not None:
        headers.append((b"x-api-key", api_key.encode()))
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
        "root_path": "", "query_string": query.encode(), "headers": headers,
        "client": (client, 50000), "server": ("testserver", 80),
    }
    incoming = [{"type": "http.request", "body": payload, "more_body": False}]
    sent = []

    async def receive():
        return incoming.pop(0) if incoming else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    response_headers = {k.decode().lower(): v.decode() for k, v in start.get("headers", [])}
    data = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], response_headers, (json.loads(data) if data else None)

def call(app, method, path, body=None, query="", **kwargs):
    """Like request, without the headers: returns (status, parsed JSON or None)."""
    status, _, data = request(app, method, path, body, query, **kwargs)
    return status, data

def routes(app, prefix):
    return {
        (method, route.path)
        for route in app.routes if route.path.startswith(prefix)
        for method in route.methods
    }

@pytest.fixture(autouse=True)
def no_env_api_key(monkeypatch):
    """Keeps a key in the test runner's environment from overriding the config's."""
    monkeypatch.delenv(API_KEY_ENV_VAR, raising=False)

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
def test_app_generation(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, API_KEY)
    app = generate_app(get_config('examples/autocrud.yml'))
    assert routes(app, "/users") == {
        ("GET", "/users"), ("GET", "/users/{pk}"), ("POST", "/users"),
    }
    assert routes(app, "/orders") == {("GET", "/orders"), ("GET", "/orders/{pk}")}
    assert routes(app, "/functions") == {
        ("GET", "/functions/get_active_users"), ("GET", "/functions/greet"),
    }

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

# Test that only the configured key gets in
def test_requests_need_the_right_key(config):
    app = generate_app(config)
    assert call(app, "GET", "/users", api_key=None) == (401, {"detail": "Missing API Key"})
    assert call(app, "GET", "/users", api_key="wrong") == (401, {"detail": "Invalid API Key"})
    assert call(app, "GET", "/users") == (200, [])

def test_refuses_to_start_without_a_key(config):
    config["security"] = {}
    with pytest.raises(ConfigError) as e:
        generate_app(config)
    assert "No API key configured" in str(e.value)
    assert API_KEY_ENV_VAR in str(e.value)

def test_refuses_to_start_with_the_old_example_key(config, monkeypatch):
    config["security"]["api_key"] = "test-secret"
    with pytest.raises(ConfigError) as e:
        generate_app(config)
    assert "Refusing to start with the published example API key" in str(e.value)

    config["security"]["api_key"] = API_KEY
    monkeypatch.setenv(API_KEY_ENV_VAR, "test-secret")
    with pytest.raises(ConfigError):
        generate_app(config)

def test_env_var_overrides_config_key(config, monkeypatch):
    monkeypatch.setenv(API_KEY_ENV_VAR, "key-from-env")
    app = generate_app(config)
    assert call(app, "GET", "/users")[0] == 401
    assert call(app, "GET", "/users", api_key="key-from-env") == (200, [])

    config["security"] = {}
    assert call(generate_app(config), "GET", "/users", api_key="key-from-env")[0] == 200

# Test that expose.functions become authenticated GET endpoints with typed query params
def test_function_endpoint(config):
    config["expose"]["functions"] = ["greet"]
    app = generate_app(config)
    assert call(app, "GET", "/functions/greet", query="name=Ada&times=2") == (
        200, {"greeting": "Hello, Ada! Hello, Ada!"},
    )
    assert call(app, "GET", "/functions/greet", query="name=Ada") == (
        200, {"greeting": "Hello, Ada!"},
    )
    assert call(app, "GET", "/functions/greet", query="name=Ada&times=many")[0] == 422
    assert call(app, "GET", "/functions/greet")[0] == 422
    assert call(app, "GET", "/functions/greet", query="name=Ada", api_key=None)[0] == 401
    assert call(app, "GET", "/functions/greet", query="name=Ada", api_key="wrong")[0] == 401

    parameters = app.openapi()["paths"]["/functions/greet"]["get"]["parameters"]
    by_name = {p["name"]: p for p in parameters}
    assert by_name["name"]["in"] == "query" and by_name["name"]["required"] is True
    assert by_name["name"]["schema"]["type"] == "string"
    assert by_name["times"]["schema"]["type"] == "integer"
    assert by_name["times"]["required"] is False

def test_unknown_function_is_a_config_error(config):
    config["expose"]["functions"] = ["nope"]
    with pytest.raises(ConfigError) as e:
        generate_app(config)
    assert "Unknown function(s) in expose.functions: nope" in str(e.value)

# Test that going over requests_per_minute returns 429 with Retry-After
def test_rate_limit_returns_429(config):
    config["rate_limit"] = {"requests_per_minute": 2}
    app = generate_app(config)
    assert call(app, "GET", "/users")[0] == 200
    assert call(app, "GET", "/users", api_key="wrong")[0] == 401
    status, headers, body = request(app, "GET", "/users")
    assert status == 429
    assert body == {"detail": "Rate limit exceeded."}
    assert 1 <= int(headers["retry-after"]) <= 60
    assert call(app, "GET", "/users", client="10.0.0.2")[0] == 200

def test_rate_limiter_window_slides():
    now = [1000.0]
    limiter = SlidingWindowRateLimiter(2, window=60, clock=lambda: now[0])
    assert limiter.hit("a") == 0
    now[0] += 30
    assert limiter.hit("a") == 0
    assert limiter.hit("a") == 30
    assert limiter.hit("b") == 0
    now[0] += 30
    assert limiter.hit("a") == 0
    assert limiter.hit("a") == 30

def test_no_rate_limit_when_unset(config):
    app = generate_app(config)
    for _ in range(5):
        assert call(app, "GET", "/users")[0] == 200

# Test that sensitive-looking column names are warned about unless excluded
def test_sensitive_columns_log_a_warning(config, caplog):
    with caplog.at_level(logging.WARNING, logger="autocrud.generator"):
        generate_app(config)
    warnings = [r.getMessage() for r in caplog.records if r.name == "autocrud.generator"]
    assert warnings == [
        "Model 'User' exposes column 'email', whose name looks sensitive. "
        "Add it to exclude_fields if clients should not see it."
    ]

def test_exclude_fields_removes_columns(config, caplog):
    call(generate_app(config), "POST", "/users", {"name": "Ada", "email": "ada@example.com"})
    config["expose"]["models"] = {
        "User": {"operations": ["list", "get", "update"], "exclude_fields": ["email"]},
    }
    with caplog.at_level(logging.WARNING, logger="autocrud.generator"):
        app = generate_app(config)
    assert "email" not in caplog.text

    schemas = app.openapi()["components"]["schemas"]
    assert set(schemas["UserRead"]["properties"]) == {"id", "name"}
    assert set(schemas["UserUpdate"]["properties"]) == {"name"}
    assert call(app, "GET", "/users/1") == (200, {"id": 1, "name": "Ada"})
    assert call(app, "GET", "/users") == (200, [{"id": 1, "name": "Ada"}])

def test_exclude_fields_rejects_unknown_or_required_columns(config):
    config["expose"]["models"] = {"User": {"operations": ["list"], "exclude_fields": ["pasword"]}}
    with pytest.raises(ConfigError) as e:
        generate_app(config)
    assert "Unknown field(s) in exclude_fields for model 'User': pasword" in str(e.value)

    config["expose"]["models"] = {"User": {"operations": ["create"], "exclude_fields": ["email"]}}
    with pytest.raises(ConfigError) as e:
        generate_app(config)
    assert "excludes required field(s) email" in str(e.value)

def test_validate_config_checks_model_options(config):
    config["expose"]["models"] = {"User": {"operations": ["list"], "exclude_fields": ["email"]}}
    assert validate_config(config) is config
    config["expose"]["models"] = {"User": {"operations": ["list"], "exclude_fields": "email"}}
    with pytest.raises(ConfigError) as e:
        validate_config(config)
    assert "'exclude_fields' for model 'User' must be a list" in str(e.value)
    config["expose"]["models"] = {"User": {"operations": ["list"], "hide": ["email"]}}
    with pytest.raises(ConfigError) as e:
        validate_config(config)
    assert "unknown option(s) hide for model 'User'" in str(e.value)
