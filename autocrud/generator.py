from fastapi import FastAPI, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker, declarative_base
from .security import get_api_key

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

def generate_app(config):
    app = FastAPI(
        title="AutoCRUD Generated API",
        description="APIs automatically generated from your database models.",
        version="0.1.0",
    )

    engine = create_engine(config['database'])
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()

    # This is where you would dynamically import and discover models
    # For this example, we will define them directly.

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

    Base.metadata.create_all(bind=engine)

    models_to_expose = {model_name:-1 for model_name in config['expose']['models']}
    if "User" in models_to_expose:
        UserSchema = create_pydantic_model(User)
        @app.get("/users", dependencies=[Depends(get_api_key)])
        def list_users():
            db = SessionLocal()
            return db.query(User).all()

    if "Order" in models_to_expose:
        OrderSchema = create_pydantic_model(Order)
        @app.get("/orders", dependencies=[Depends(get_api_key)])
        def list_orders():
            db = SessionLocal()
            return db.query(Order).all()

    return app
