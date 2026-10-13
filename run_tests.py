import os
import secrets

from autocrud.config import get_config
from autocrud.generator import generate_app
from autocrud.security import API_KEY_ENV_VAR

def run_tests():
    print("Running tests...")
    # The example config commits no key; generate_app refuses to start without one.
    os.environ.setdefault(API_KEY_ENV_VAR, secrets.token_urlsafe(32))
    try:
        # Test 1: Config Loading
        config = get_config('examples/autocrud.yml')
        assert config['database'] == 'sqlite:///dev.db'
        assert 'User' in config['expose']['models']
        print("Test 1: Config Loading - PASSED")

        # Test 2: App Generation
        app = generate_app(config)
        user_routes = [route.path for route in app.routes if 'users' in route.path]
        assert "/users" in user_routes
        order_routes = [route.path for route in app.routes if 'orders' in route.path]
        assert "/orders" in order_routes
        print("Test 2: App Generation - PASSED")

    except Exception as e:
        print(f"A test failed: {e}")

if __name__ == "__main__":
    run_tests()
