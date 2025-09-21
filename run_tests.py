from autocrud.config import get_config
from autocrud.generator import generate_app

def run_tests():
    print("Running tests...")
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
