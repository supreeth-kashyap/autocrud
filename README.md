# AutoCRUD

AutoCRUD is a powerful Python library that automatically generates REST APIs from your existing database models and functions. You can instantly create a secure, production-ready API with just a few lines of configuration. It uses FastAPI, SQLAlchemy, and Pydantic to provide a modern, fast, and well-documented API.

## Installation

To get started, you can install `autocrud` using pip:

```bash
pip install autocrud
```

## Quickstart Guide

Follow these steps to get your API up and running in minutes.

### 1. Initialize Your Project

After installing the library, navigate to your project's root directory in your terminal and run the `init` command:

```bash
autocrud init
```

This command creates a `autocrud.yml` file in your directory. This file is where you will configure your API.

### 2. Configure Your API

Next, open the `autocrud.yml` file to specify which database models and functions you want to expose.

Here is an example configuration:

```yaml
database: sqlite:///dev.db
expose:
  models:
    User: [list, get, create]
    Order: [list, get]
  functions:
    - get_active_users
security:
  api_key: your-secret-api-key
rate_limit:
  requests_per_minute: 100
```

- **`database`**: Your SQLAlchemy database connection string.
- **`expose.models`**: A list of your SQLAlchemy models to expose. You can specify which CRUD operations (`list`, `get`, `create`, `update`, `delete`) to enable for each model.
- **`expose.functions`**: A list of regular Python functions you want to expose as secure GET endpoints.
- **`security.api_key`**: The secret key that clients must provide in the `X-API-Key` header to access the API.

### 3. Generate and Run Your API

To generate a runnable application based on your configuration, use the `publish` command:

```bash
autocrud publish
```

This command creates a `main.py`, a `Dockerfile`, and a `requirements.txt` file for you, scaffolding a complete, deployable application.

Now, you can start your new API server with `uvicorn`:

```bash
uvicorn main:app --reload
```

Your API is now live and ready to accept requests!

## Interactive API Documentation

Once your application is running, `autocrud` automatically generates interactive API documentation for you. You can access it by navigating to these URLs in your browser:

- **Swagger UI**: `http://127.0.0.1:8000/docs`
- **ReDoc**: `http://127.0.0.1:8000/redoc`

You will see all your configured endpoints, their expected inputs, and their responses. You can even try them out directly from the browser.

![Swagger UI Screenshot](https://via.placeholder.com/800x400.png?text=AutoCRUD+Swagger+UI)

## Security Considerations

- **API Key**: Your API is protected by an API key. Never expose this key in public client-side code. All requests must include the `X-API-Key` header with your secret key.
- **Model Exposure**: Be very careful about which models and fields you expose. By default, `autocrud` does not expose any of your models. You must explicitly whitelist them in your `autocrud.yml`. Avoid exposing sensitive data like user passwords or other personal identifiable information (PII). `autocrud` will warn you if it detects columns with potentially sensitive names (e.g., `password`, `email`, `ssn`).
- **Database Permissions**: For production environments, it is strongly recommended to use a database user with the least required privileges. For example, if you only need to expose `get` and `list` operations, use a database user with read-only access.

## Contribution Guidelines

We welcome contributions! If you'd like to contribute to the development of `autocrud`, please feel free to fork the repository, make your changes, and submit a pull request. For bugs and feature requests, please open an issue on our GitHub repository.

