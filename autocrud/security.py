from fastapi import Security, HTTPException, status
from fastapi.security.api_key import APIKeyHeader
import os
import secrets
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

def make_api_key_dependency(expected_api_key):
    """
    Returns a dependency that checks the X-API-Key header against a key taken
    from an already loaded config, so apps built from any config path work.
    """
    def check_api_key(api_key: str = Security(api_key_header)):
        if not expected_api_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="API key not configured on the server."
            )
        if not secrets.compare_digest(api_key.encode(), expected_api_key.encode()):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API Key",
            )
        return api_key

    return check_api_key

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
