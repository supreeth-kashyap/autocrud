from fastapi import FastAPI
from autocrud.generator import generate_app
from autocrud.config import get_config

# This is the main application file that will be run with uvicorn.
# It uses the autocrud library to generate the API from the config file.

app = generate_app(get_config('../autocrud.yml'))
