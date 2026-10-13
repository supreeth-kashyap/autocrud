import secrets

import yaml

OPERATIONS = ("list", "get", "create", "update", "delete")

DEFAULT_CONFIG_TEMPLATE = """\
# autocrud configuration. Edit this file, then run: autocrud serve

# SQLAlchemy database URL.
database: sqlite:///dev.db

# Python module that defines your SQLAlchemy models, importable from the
# directory you run autocrud in (e.g. "models" for ./models.py, or "myapp.models").
models_module: models

expose:
  # Model class name -> operations to enable ({operations}).
  # Nothing is exposed until you list it here, for example:
  #   models:
  #     User: [list, get]
  models: {{}}
  # Plain functions to expose as GET endpoints.
  functions: []

security:
  # Clients must send this in the X-API-Key header. Keep it secret.
  api_key: "{api_key}"

rate_limit:
  requests_per_minute: 100
"""


class ConfigError(ValueError):
    """Raised when the config file is missing, unparsable or invalid."""


def get_config(path="autocrud.yml", validate=True):
    """Reads, parses and (by default) validates the YAML config file."""
    try:
        with open(path, 'r') as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise ConfigError(
            f"Config file not found at: {path}. Run 'autocrud init' to create one."
        )
    except yaml.YAMLError as e:
        raise ConfigError(f"Could not parse {path} as YAML: {e}")
    if validate:
        validate_config(data, path)
    return data


def validate_config(data, path="autocrud.yml"):
    """Checks required keys, operation names and value types; raises ConfigError."""
    def fail(message):
        raise ConfigError(f"Invalid config in {path}: {message}")

    if not isinstance(data, dict):
        fail("expected a mapping of settings at the top level.")

    for key in ("database", "expose", "security"):
        if key not in data:
            fail(f"missing required key '{key}'.")

    if not isinstance(data["database"], str) or not data["database"]:
        fail("'database' must be a non-empty database URL string.")

    if "models_module" in data and not isinstance(data["models_module"], str):
        fail("'models_module' must be a module name string.")

    expose = data["expose"]
    if not isinstance(expose, dict):
        fail("'expose' must be a mapping with 'models' and/or 'functions'.")
    models = expose.get("models") or {}
    if not isinstance(models, dict):
        fail("'expose.models' must map model names to lists of operations.")
    for name, ops in models.items():
        if not isinstance(ops, list):
            fail(f"operations for model '{name}' must be a list, e.g. [list, get].")
        for op in ops:
            if op not in OPERATIONS:
                fail(
                    f"unknown operation '{op}' for model '{name}'; "
                    f"expected one of: {', '.join(OPERATIONS)}."
                )
    functions = expose.get("functions") or []
    if not isinstance(functions, list) or not all(isinstance(f, str) for f in functions):
        fail("'expose.functions' must be a list of function names.")

    security = data["security"]
    if not isinstance(security, dict):
        fail("'security' must be a mapping with an 'api_key'.")
    api_key = security.get("api_key")
    if not isinstance(api_key, str) or not api_key:
        fail("'security.api_key' must be a non-empty string.")

    rate_limit = data.get("rate_limit")
    if rate_limit is not None:
        if not isinstance(rate_limit, dict):
            fail("'rate_limit' must be a mapping.")
        rpm = rate_limit.get("requests_per_minute")
        if rpm is not None and (isinstance(rpm, bool) or not isinstance(rpm, int) or rpm <= 0):
            fail("'rate_limit.requests_per_minute' must be a positive integer.")

    return data


def set_default_config(path="autocrud.yml"):
    """Creates a commented default config file with a freshly generated API key."""
    content = DEFAULT_CONFIG_TEMPLATE.format(
        operations=", ".join(OPERATIONS),
        api_key=secrets.token_urlsafe(32),
    )
    with open(path, 'w') as f:
        f.write(content)
