import os
from importlib import metadata

import click

from . import __version__
from .generator import generate_app, CONFIG_ENV_VAR
from .config import ConfigError, get_config, set_default_config

PUBLISHED_FILES = ("main.py", "Dockerfile", "requirements.txt")

DOCKERFILE = '''FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
'''

MAIN_TEMPLATE = '''from autocrud.generator import generate_app
from autocrud.config import get_config

app = generate_app(get_config({config_path!r}))
'''


def _load_config(path):
    """Loads and validates the config, turning errors into friendly CLI messages."""
    try:
        return get_config(path)
    except ConfigError as e:
        raise click.ClickException(str(e))


def _build_app(config_data):
    try:
        return generate_app(config_data)
    except ConfigError as e:
        raise click.ClickException(str(e))


def _installed_version():
    try:
        return metadata.version("autocrud")
    except metadata.PackageNotFoundError:
        return __version__


@click.group()
def cli():
    """Automatic REST APIs from database models and functions."""
    pass

@cli.command()
def init():
    """Creates a commented autocrud.yml config file with a random API key."""
    if os.path.exists("autocrud.yml"):
        click.confirm("autocrud.yml already exists. Overwrite?", abort=True)

    set_default_config("autocrud.yml")
    click.echo("✅ Created autocrud.yml with a random API key.")
    click.echo("Edit models_module and expose.models, then run: autocrud serve")

@cli.command()
@click.option("--config", default="autocrud.yml", help="Path to the config file.")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind.")
@click.option("--port", default=8000, show_default=True, type=int, help="Port to bind.")
@click.option("--reload", is_flag=True, help="Restart the server when code changes.")
def serve(config, host, port, reload):
    """Builds the API from the config and runs it with uvicorn."""
    # Build once up front so config and model errors are reported here,
    # not as a traceback from inside the server.
    app = _build_app(_load_config(config))

    import uvicorn

    click.echo(f"🚀 Serving API docs at http://{host}:{port}/docs")
    if reload:
        os.environ[CONFIG_ENV_VAR] = os.path.abspath(config)
        uvicorn.run(
            "autocrud.generator:create_app_from_env",
            factory=True, host=host, port=port, reload=True,
        )
    else:
        uvicorn.run(app, host=host, port=port)

@cli.command()
@click.option("--config", default="autocrud.yml", help="Path to the config file.")
@click.option("--force", is_flag=True, help="Overwrite existing files without asking.")
def publish(config, force):
    """Scaffolds a deployable FastAPI app with main.py, Dockerfile and requirements.txt."""
    _load_config(config)

    existing = [name for name in PUBLISHED_FILES if os.path.exists(name)]
    if existing and not force:
        if not click.confirm(
            f"{', '.join(existing)} already exist(s). Overwrite?", default=False
        ):
            raise click.ClickException(
                f"Refusing to overwrite {', '.join(existing)}. "
                "Pass --force to overwrite them."
            )

    with open("main.py", "w") as f:
        f.write(MAIN_TEMPLATE.format(config_path=config))

    with open("Dockerfile", "w") as f:
        f.write(DOCKERFILE)

    with open("requirements.txt", "w") as f:
        f.write(f"autocrud=={_installed_version()}\n")

    click.echo("✅ Successfully published the application.")
    click.echo("You can now build and run your app with Docker.")

if __name__ == '__main__':
    cli()
