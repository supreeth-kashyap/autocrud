from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False)
    email = Column(String(50), unique=True, index=True, nullable=False)
    orders = relationship("Order", back_populates="user")

class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    amount = Column(Integer, nullable=False)
    user = relationship("User", back_populates="orders")


def get_active_users():
    """Example function to be exposed via the API."""
    # In a real app, this would query the database for active users
    return [{"id": 1, "name": "John Doe", "status": "active"}]


def greet(name: str, times: int = 1):
    """Example function with typed query parameters: GET /functions/greet?name=Ada&times=2."""
    return {"greeting": " ".join([f"Hello, {name}!"] * times)}
