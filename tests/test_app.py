import pytest
from autocrud.config import get_config
from autocrud.generator import generate_app

# Test to ensure the YAML configuration is loaded correctly
def test_config_loading():
    config = get_config('examples/autocrud.yml')
    assert config['database'] == 'sqlite:///dev.db'
    assert 'User' in config['expose']['models']

# Test to ensure the FastAPI app is generated with the correct routes
def test_app_generation():
    config = get_config('examples/autocrud.yml')
    app = generate_app(config)
    
    # Check that routes for the 'User' model are created
    user_routes = [route.path for route in app.routes if 'users' in route.path]
    assert "/users" in user_routes

    # Check that routes for the 'Order' model are created
    order_routes = [route.path for route in app.routes if 'orders' in route.path]
    assert "/orders" in order_routes
