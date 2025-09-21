import yaml

def get_config(path="autocrud.yml"):
    """Reads and parses the YAML config file."""
    try:
        with open(path, 'r') as f:
            return yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Config file not found at: {path}")

def set_default_config(path="autocrud.yml"):
    """Creates a default config file."""
    default_config = {
        'database': 'sqlite:///dev.db',
        'expose': {
            'models': {
                'User': ['list', 'get', 'create'],
                'Order': ['list', 'get']
            },
            'functions': ['get_active_users']
        },
        'security': {
            'api_key': 'test-secret'
        },
        'rate_limit': {
            'requests_per_minute': 100
        }
    }
    with open(path, 'w') as f:
        yaml.dump(default_config, f, default_flow_style=False)
