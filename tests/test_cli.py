import os

import uvicorn
from click.testing import CliRunner

from autocrud.cli import cli
from autocrud.config import get_config

VALID_CONFIG = """\
database: sqlite:///dev.db
models_module: examples.demo_app.models
expose:
  models:
    User: [list, get]
security:
  api_key: secret
"""

# Test that init writes a valid, commented config with a random API key
def test_init_writes_random_key_and_template():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0, result.output

        with open("autocrud.yml") as f:
            text = f.read()
        assert text.startswith("#")
        assert "models_module" in text
        assert "test-secret" not in text

        config = get_config("autocrud.yml")
        assert len(config["security"]["api_key"]) >= 40
        assert config["expose"]["models"] == {}

        os.remove("autocrud.yml")
        runner.invoke(cli, ["init"])
        assert get_config("autocrud.yml")["security"]["api_key"] != config["security"]["api_key"]

# Test that an unknown operation is reported as a friendly error, not a traceback
def test_serve_reports_unknown_operation():
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open("autocrud.yml", "w") as f:
            f.write(VALID_CONFIG.replace("[list, get]", "[list, frobnicate]"))
        result = runner.invoke(cli, ["serve"])
        assert result.exit_code == 1
        assert "unknown operation 'frobnicate'" in result.output
        assert "Traceback" not in result.output

def test_serve_reports_missing_key():
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open("autocrud.yml", "w") as f:
            f.write("database: sqlite:///dev.db\nexpose: {}\n")
        result = runner.invoke(cli, ["serve"])
        assert result.exit_code == 1
        assert "missing required key 'security'" in result.output

def test_serve_reports_missing_models_module():
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open("autocrud.yml", "w") as f:
            f.write(VALID_CONFIG.replace("models_module: examples.demo_app.models\n", ""))
        result = runner.invoke(cli, ["serve"])
        assert result.exit_code == 1
        assert "missing required key 'models_module'" in result.output

def test_serve_reports_missing_file():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["serve", "--config", "nope.yml"])
        assert result.exit_code == 1
        assert "Config file not found at: nope.yml" in result.output

def test_serve_reports_bad_yaml():
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open("autocrud.yml", "w") as f:
            f.write("database: [unclosed\n")
        result = runner.invoke(cli, ["serve"])
        assert result.exit_code == 1
        assert "Could not parse autocrud.yml as YAML" in result.output

def test_serve_reports_unknown_model():
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open("autocrud.yml", "w") as f:
            f.write(VALID_CONFIG.replace("User:", "Ghost:"))
        result = runner.invoke(cli, ["serve"])
        assert result.exit_code == 1
        assert "Unknown model(s) in expose.models: Ghost" in result.output

# Test that serve builds the app and hands it to uvicorn with the given options
def test_serve_runs_uvicorn(monkeypatch):
    calls = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open("autocrud.yml", "w") as f:
            f.write(VALID_CONFIG)
        result = runner.invoke(cli, ["serve", "--port", "9000"])
        assert result.exit_code == 0, result.output
        assert "http://127.0.0.1:9000/docs" in result.output
        app, kwargs = calls[0]
        assert "/users" in [route.path for route in app.routes]
        assert kwargs == {"host": "127.0.0.1", "port": 9000}

# Test that publish will not clobber existing files unless forced
def test_publish_refuses_to_overwrite_without_force():
    runner = CliRunner()
    with runner.isolated_filesystem():
        runner.invoke(cli, ["init"])
        with open("main.py", "w") as f:
            f.write("original\n")

        result = runner.invoke(cli, ["publish"], input="n\n")
        assert result.exit_code == 1
        assert "Refusing to overwrite main.py" in result.output
        assert not os.path.exists("Dockerfile")
        with open("main.py") as f:
            assert f.read() == "original\n"

        result = runner.invoke(cli, ["publish", "--force"])
        assert result.exit_code == 0, result.output
        with open("main.py") as f:
            assert "get_config('autocrud.yml')" in f.read()

def test_publish_writes_scaffold_using_config_path():
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.mkdir("conf")
        with open("conf/api.yml", "w") as f:
            f.write(VALID_CONFIG)
        result = runner.invoke(cli, ["publish", "--config", "conf/api.yml"])
        assert result.exit_code == 0, result.output
        with open("main.py") as f:
            assert "get_config('conf/api.yml')" in f.read()
        with open("Dockerfile") as f:
            assert f.read().startswith("FROM python:3.12-slim")
        with open("requirements.txt") as f:
            assert f.read().startswith("autocrud==")
