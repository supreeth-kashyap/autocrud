import importlib
import inspect
import logging
import os
import re
import sys
import typing
from typing import Any, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status
from pydantic import ConfigDict, create_model
from sqlalchemy import Column, create_engine, inspect as sa_inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapper, Session, sessionmaker
from .config import ConfigError, get_config, model_options
from .security import make_api_key_dependency, make_rate_limiter, resolve_api_key

logger = logging.getLogger(__name__)

# Environment variable that tells create_app_from_env which config to load
# (used by `autocrud serve --reload`, where uvicorn needs an import string).
CONFIG_ENV_VAR = "AUTOCRUD_CONFIG"

# Pagination bounds for list endpoints.
LIST_LIMIT_DEFAULT = 100
LIST_LIMIT_MAX = 1000

# Exposed columns whose names match this get a warning at startup.
SENSITIVE_FIELD_PATTERN = re.compile(r"password|passwd|secret|token|ssn|email|api_key", re.IGNORECASE)

def _import_module(module_name, key):
    """Imports a module named in the config, importable from the working directory."""
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    try:
        return importlib.import_module(module_name)
    except ImportError as e:
        raise ConfigError(f"Could not import {key} '{module_name}': {e}")

def _is_mapped_class(obj):
    return isinstance(obj, type) and isinstance(sa_inspect(obj, raiseerr=False), Mapper)

def _module_models(module_name):
    """Imports models_module and returns its SQLAlchemy mapped classes by name."""
    module = _import_module(module_name, "models_module")
    return {name: obj for name, obj in vars(module).items() if _is_mapped_class(obj)}

def _resolve_models(config):
    """Maps each model named in expose.models to its mapped class, or raises ConfigError."""
    requested = (config.get('expose') or {}).get('models') or {}
    if not requested:
        return {}
    module_name = config.get('models_module')
    if not module_name:
        raise ConfigError("'models_module' is required to expose models.")
    available = _module_models(module_name)
    unknown = [name for name in requested if name not in available]
    if unknown:
        raise ConfigError(
            f"Unknown model(s) in expose.models: {', '.join(unknown)}. "
            f"Mapped classes available in module '{module_name}': "
            f"{', '.join(sorted(available)) or 'none'}."
        )
    return {name: available[name] for name in requested}

def _resolve_functions(config):
    """Maps each name in expose.functions to a function from functions_module
    (default: models_module), or raises ConfigError."""
    requested = (config.get('expose') or {}).get('functions') or []
    if not requested:
        return {}
    key = 'functions_module' if config.get('functions_module') else 'models_module'
    module_name = config.get(key)
    if not module_name:
        raise ConfigError("'functions_module' or 'models_module' is required to expose functions.")
    module = _import_module(module_name, key)
    unknown = [name for name in requested if not callable(getattr(module, name, None))]
    if unknown:
        available = sorted(
            name for name, obj in vars(module).items()
            if inspect.isfunction(obj) and obj.__module__ == module.__name__
        )
        raise ConfigError(
            f"Unknown function(s) in expose.functions: {', '.join(unknown)}. "
            f"Functions available in module '{module_name}': {', '.join(available) or 'none'}."
        )
    return {name: getattr(module, name) for name in requested}

def _function_endpoint(name, func):
    """
    Wraps func in an endpoint whose parameters are all query parameters,
    typed from func's annotations (unannotated ones are strings) and required
    unless func gives them a default.
    """
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        raise ConfigError(f"Could not read the signature of function '{name}'.")
    try:
        hints = typing.get_type_hints(func)
    except Exception:
        hints = {}
    parameters = []
    for param in signature.parameters.values():
        if param.kind not in (param.POSITIONAL_OR_KEYWORD, param.KEYWORD_ONLY):
            raise ConfigError(
                f"Function '{name}' has parameter '{param.name}' that cannot be passed "
                "by name; only named parameters can become query parameters."
            )
        default = Query(...) if param.default is param.empty else Query(param.default)
        parameters.append(inspect.Parameter(
            param.name, inspect.Parameter.KEYWORD_ONLY,
            default=default, annotation=hints.get(param.name, str),
        ))

    if inspect.iscoroutinefunction(func):
        async def endpoint(**kwargs):
            return await func(**kwargs)
    else:
        def endpoint(**kwargs):
            return func(**kwargs)
    # Not functools.wraps: FastAPI would follow __wrapped__ back to func's signature.
    endpoint.__name__ = name
    endpoint.__doc__ = func.__doc__
    endpoint.__signature__ = inspect.Signature(parameters)
    return endpoint

def _python_type(column):
    try:
        return column.type.python_type
    except NotImplementedError:
        return Any

def _columns(model):
    """Maps each column attribute's key to its Column, skipping SQL expressions."""
    return {
        attr.key: attr.columns[0] for attr in sa_inspect(model).column_attrs
        if isinstance(attr.columns[0], Column)
    }

def _required_on_create(column, autoincrement):
    if column.primary_key:
        return column is not autoincrement
    defaulted = column.default is not None or column.server_default is not None
    return not (column.nullable or defaulted)

def _check_exclude_fields(model, operations, exclude):
    """Raises ConfigError for unknown names, or for excluding a column that create needs."""
    columns = _columns(model)
    unknown = [key for key in exclude if key not in columns]
    if unknown:
        raise ConfigError(
            f"Unknown field(s) in exclude_fields for model '{model.__name__}': "
            f"{', '.join(unknown)}. Columns: {', '.join(columns)}."
        )
    if "create" in operations:
        autoincrement = model.__table__.autoincrement_column
        required = [key for key in exclude if _required_on_create(columns[key], autoincrement)]
        if required:
            raise ConfigError(
                f"Model '{model.__name__}' enables create but excludes required "
                f"field(s) {', '.join(required)}; give them a default, make them "
                "nullable, or drop create."
            )

def _warn_sensitive_fields(model, exclude):
    for key in _columns(model):
        if key not in exclude and SENSITIVE_FIELD_PATTERN.search(key):
            logger.warning(
                "Model '%s' exposes column '%s', whose name looks sensitive. "
                "Add it to exclude_fields if clients should not see it.",
                model.__name__, key,
            )

def build_schemas(model, exclude=()):
    """
    Returns (Read, Create, Update) Pydantic models for a mapped class.

    Read has every column. Create leaves out an autoincrement primary key and
    makes nullable or defaulted columns optional. Update has every non-key
    column, all optional; a non-nullable column still rejects an explicit null.
    Columns named in exclude are left out of all three.
    """
    autoincrement = model.__table__.autoincrement_column
    read, create, update = {}, {}, {}
    for key, column in _columns(model).items():
        if key in exclude:
            continue
        python_type = _python_type(column)
        optional_type = Optional[python_type] if column.nullable else python_type
        read[key] = (optional_type, None) if column.nullable else (python_type, ...)
        required = _required_on_create(column, autoincrement)
        if column.primary_key:
            if required:
                create[key] = (python_type, ...)
            continue
        create[key] = (python_type, ...) if required else (optional_type, None)
        update[key] = (optional_type, None)

    name = model.__name__
    return (
        create_model(f"{name}Read", __config__=ConfigDict(from_attributes=True), **read),
        create_model(f"{name}Create", **create),
        create_model(f"{name}Update", **update),
    )

def _make_engine(url):
    # Sessions are opened, used and closed on different threadpool threads.
    connect_args = {}
    if make_url(url).get_backend_name() == "sqlite":
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args)

def make_session_dependency(SessionLocal):
    """Returns a dependency that gives each request its own session: commit on
    success, roll back on error, always close."""
    def get_db():
        db = SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return get_db

def _flush(db):
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The change violates a database constraint.",
        )

def _add_crud_routes(app, model, operations, exclude, get_db, api_key_dependency):
    """Registers only the configured operations for one mapped class."""
    table = model.__tablename__
    _check_exclude_fields(model, operations, exclude)
    _warn_sensitive_fields(model, exclude)
    Read, Create, Update = build_schemas(model, exclude)
    dependencies = [Depends(api_key_dependency)]
    pk_columns = sa_inspect(model).primary_key
    if len(pk_columns) != 1 and any(op in operations for op in ("get", "update", "delete")):
        raise ConfigError(
            f"Model '{model.__name__}' has a composite primary key; "
            "only list and create are supported for it."
        )
    pk_type = _python_type(pk_columns[0])

    def get_or_404(db, pk):
        obj = db.get(model, pk)
        if obj is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{model.__name__} {pk} not found.",
            )
        return obj

    if "list" in operations:
        @app.get(f"/{table}", name=f"list_{table}", response_model=List[Read],
                 dependencies=dependencies)
        def list_items(
            limit: int = Query(LIST_LIMIT_DEFAULT, ge=1, le=LIST_LIMIT_MAX),
            offset: int = Query(0, ge=0),
            db: Session = Depends(get_db),
        ):
            query = select(model).order_by(*pk_columns).offset(offset).limit(limit)
            return db.scalars(query).all()

    if "get" in operations:
        @app.get(f"/{table}/{{pk}}", name=f"get_{table}", response_model=Read,
                 dependencies=dependencies)
        def get_item(pk: pk_type, db: Session = Depends(get_db)):
            return get_or_404(db, pk)

    if "create" in operations:
        @app.post(f"/{table}", name=f"create_{table}", response_model=Read,
                  status_code=status.HTTP_201_CREATED, dependencies=dependencies)
        def create_item(payload: Create, db: Session = Depends(get_db)):
            obj = model(**payload.model_dump(exclude_unset=True))
            db.add(obj)
            _flush(db)
            db.refresh(obj)
            return obj

    if "update" in operations:
        @app.patch(f"/{table}/{{pk}}", name=f"update_{table}", response_model=Read,
                   dependencies=dependencies)
        def update_item(pk: pk_type, payload: Update, db: Session = Depends(get_db)):
            obj = get_or_404(db, pk)
            for key, value in payload.model_dump(exclude_unset=True).items():
                setattr(obj, key, value)
            _flush(db)
            db.refresh(obj)
            return obj

    if "delete" in operations:
        @app.delete(f"/{table}/{{pk}}", name=f"delete_{table}",
                    status_code=status.HTTP_204_NO_CONTENT, response_class=Response,
                    dependencies=dependencies)
        def delete_item(pk: pk_type, db: Session = Depends(get_db)):
            db.delete(get_or_404(db, pk))
            _flush(db)
            return Response(status_code=status.HTTP_204_NO_CONTENT)

def generate_app(config):
    app = FastAPI(
        title="AutoCRUD Generated API",
        description="APIs automatically generated from your database models.",
        version="0.1.0",
    )

    # Resolved once, so a missing or example key stops startup instead of
    # failing each request.
    api_key_dependency = make_api_key_dependency(
        resolve_api_key(config), make_rate_limiter(config),
    )
    models = _resolve_models(config)
    functions = _resolve_functions(config)
    options = (config.get('expose') or {}).get('models') or {}

    # Tables are not created here: they belong to the user's database.
    SessionLocal = sessionmaker(bind=_make_engine(config['database']), autoflush=False)
    get_db = make_session_dependency(SessionLocal)

    for name, model in models.items():
        operations, exclude = model_options(options[name])
        _add_crud_routes(app, model, operations, exclude, get_db, api_key_dependency)

    for name, func in functions.items():
        app.add_api_route(
            f"/functions/{name}", _function_endpoint(name, func), methods=["GET"],
            name=f"function_{name}", dependencies=[Depends(api_key_dependency)],
        )

    return app

def create_app_from_env():
    """App factory for `autocrud serve --reload`; reads the config path from the environment."""
    return generate_app(get_config(os.environ.get(CONFIG_ENV_VAR, "autocrud.yml")))
