from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader
import os
from .config import get_config

API_KEY_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=True)

def get_api_key(api_key: str = Security(api_key_header)):
    """
    Checks for the X-API-Key header and validates it.
    """
    config = get_config("autocrud.yml")
    expected_api_key = config.get("security", {}).get("api_key", None)
    
    if not expected_api_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key not configured on the server."
        )

    if api_key == expected_api_key:
        return api_key
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API Key",
        )

def rate_limit_hook():
    """
    Placeholder for rate limiting logic.
    """
    pass

def request_logging_hook():
    """
    Placeholder for request logging logic.
    """
    pass
