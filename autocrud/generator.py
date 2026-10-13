import importlib
import os
import sys

from fastapi import FastAPI, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base
from .config import ConfigError, get_config
from .security import make_api_key_dependency

# Environment variable that tells create_app_from_env which config to load
# (used by `autocrud serve --reload`, where uvicorn needs an import string).
CONFIG_ENV_VAR = "AUTOCRUD_CONFIG"

# Placeholder for dynamically creating Pydantic models
def create_pydantic_model(sqla_model):
    # This is a simplified version. A real implementation would need to handle more types and relationships.
    fields = {}
    for column in sqla_model.__table__.columns:
        field_type = str
        if isinstance(column.type, Integer):
            field_type = int
        fields[column.name] = (field_type, ...)

    return type(f"{sqla_model.__name__}Schema", (BaseModel,), {"__annotations__": fields})

def _builtin_models():
    """Demo models used when the config does not name a models_module."""
    Base = declarative_base()

    class User(Base):
        __tablename__ = 'users'
        id = Column(Integer, primary_key=True, index=True)
        name = Column(String, index=True)
        email = Column(String, unique=True, index=True)

    class Order(Base):
        __tablename__ = 'orders'
        id = Column(Integer, primary_key=True, index=True)
        user_id = Column(Integer)
        amount = Column(Integer)

    return {"User": User, "Order": Order}

def _module_models(module_name):
    """Imports models_module and returns its SQLAlchemy model classes by name."""
    if os.getcwd() not in sys.path:
        sys.path.insert(0, os.getcwd())
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise ConfigError(f"Could not import models_module '{module_name}': {e}")
    return {
        name: obj for name, obj in vars(module).items()
        if isinstance(obj, type) and hasattr(obj, "__table__")
    }

def _resolve_models(config):
    """Maps each model named in expose.models to its class, or raises ConfigError."""
    requested = (config.get('expose') or {}).get('models') or {}
    if not requested:
        return {}
    module_name = config.get('models_module')
    available = _module_models(module_name) if module_name else _builtin_models()
    unknown = [name for name in requested if name not in available]
    if unknown:
        source = f"module '{module_name}'" if module_name else "the built-in demo models"
        raise ConfigError(
            f"Unknown model(s) in expose.models: {', '.join(unknown)}. "
            f"Available in {source}: {', '.join(sorted(available)) or 'none'}."
        )
    return {name: available[name] for name in requested}

def _add_list_route(app, model, SessionLocal, api_key_dependency):
    @app.get(
        f"/{model.__tablename__}",
        name=f"list_{model.__tablename__}",
        dependencies=[Depends(api_key_dependency)],
    )
    def list_items():
        db = SessionLocal()
        try:
            return db.query(model).all()
        finally:
            db.close()

def generate_app(config):
    app = FastAPI(
        title="AutoCRUD Generated API",
        description="APIs automatically generated from your database models.",
        version="0.1.0",
    )

    models = _resolve_models(config)
    operations = (config.get('expose') or {}).get('models') or {}
    api_key_dependency = make_api_key_dependency(config['security']['api_key'])

    engine = create_engine(config['database'])
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    for metadata in {id(m.metadata): m.metadata for m in models.values()}.values():
        metadata.create_all(bind=engine)

    for name, model in models.items():
        if "list" in operations[name]:
            _add_list_route(app, model, SessionLocal, api_key_dependency)

    return app

def create_app_from_env():
    """App factory for `autocrud serve --reload`; reads the config path from the environment."""
    return generate_app(get_config(os.environ.get(CONFIG_ENV_VAR, "autocrud.yml")))
