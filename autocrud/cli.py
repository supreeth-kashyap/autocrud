import click
import yaml
import os

from .generator import generate_app
from .config import get_config, set_default_config

@click.group()
def cli():
    """Automatic REST APIs from database models and functions."""
    pass

@cli.command()
def init():
    """Creates a default autocrud.yml config file."""
    if os.path.exists("autocrud.yml"):
        click.confirm("autocrud.yml already exists. Overwrite?", abort=True)
    
    set_default_config("autocrud.yml")
    click.echo("✅ Created autocrud.yml with default settings.")

@cli.command()
@click.option("--config", default="autocrud.yml", help="Path to the config file.")
def generate(config):
    """Scans models, generates APIs, and mounts Swagger UI."""
    config_data = get_config(config)
    
    # Placeholder for the actual app generation
    app = generate_app(config_data)
    
    click.echo("🚀 API generation complete.")
    click.echo("Run your app with: uvicorn main:app --reload")

@cli.command()
@click.option("--config", default="autocrud.yml", help="Path to the config file.")
def publish(config):
    """Scaffolds a deployable FastAPI app with Dockerfile and README."""
    
    # Create the main.py for the app
    with open("main.py", "w") as f:
        f.write('''
from fastapi import FastAPI
from autocrud.generator import generate_app
from autocrud.config import get_config

app = generate_app(get_config('autocrud.yml'))
''')

    # Create a Dockerfile
    with open("Dockerfile", "w") as f:
        f.write('''
FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
''')

    # Create a requirements.txt
    # In a real scenario, you'd parse pyproject.toml, but for now, this is fine
    with open("requirements.txt", "w") as f:
        f.write('''
fastapi
uvicorn
sqlalchemy
pydantic
pyyaml
autocrud
''')

    click.echo("✅ Successfully published the application.")
    click.echo("You can now build and run your app with Docker.")

if __name__ == '__main__':
    cli()
