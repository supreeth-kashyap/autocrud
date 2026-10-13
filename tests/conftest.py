import os
import sys

# Make the repository root importable so configs can name
# models_module: examples.demo_app.models from any working directory.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
