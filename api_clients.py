"""Factory function for creating Google API service clients."""

import sys
import os
from typing import Any

from googleapiclient.discovery import build, Resource
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

# Assuming config, logger, and error_handler are set up correctly
try:
    import config
    from utils.logger import get_logger
    from utils.error_handler import APIError, AuthenticationError
except ImportError:
    # Adjust path if run directly or structure differs
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    import config
    from utils.logger import get_logger
    from utils.error_handler import APIError, AuthenticationError

logger = get_logger()

# Cache for built services to avoid rebuilding them unnecessarily
_service_cache: dict[tuple[str, str], Resource] = {}

def build_service(service_name: str, version: str, credentials: Credentials) -> Resource:
    """Builds and returns a Google API service client.

    Uses cached service object if available for the same service, version,
    and credentials (by checking credential validity).

    Args:
        service_name: The name of the service (e.g., 'classroom', 'drive').
        version: The version of the service (e.g., 'v1', 'v3').
        credentials: Valid Google OAuth 2.0 credentials.

    Returns:
        Resource: The Google API service client resource object.

    Raises:
        AuthenticationError: If credentials are invalid or expired.
        APIError: If the service fails to build due to API issues.
    """
    if not credentials or not credentials.valid:
        logger.error(f"Attempted to build service '{service_name}' with invalid credentials.")
        raise AuthenticationError(f"Invalid or expired credentials provided for service '{service_name}'. Please re-authenticate.")

    cache_key = (service_name, version)

    # Check cache - basic check, assumes credentials object validity implies usability
    # A more robust check might involve comparing token expiry or scopes
    if cache_key in _service_cache:
        logger.debug(f"Using cached service client for {service_name} {version}")
        return _service_cache[cache_key]

    logger.debug(f"Building new service client for {service_name} {version}...")
    try:
        # Build the service object
        # cache_discovery=False can sometimes help resolve issues with outdated discovery docs,
        # but usually default (True) is fine and faster.
        service = build(service_name, version, credentials=credentials, cache_discovery=True)
        logger.info(f"Successfully built service client for {service_name} {version}.")
        _service_cache[cache_key] = service # Cache the newly built service
        return service
    except HttpError as e:
        logger.error(
            f"Failed to build service '{service_name}' {version} due to HTTP error: {e.resp.status} {e.content}",
            exc_info=config.DEBUG
        )
        # Check for common auth-related errors
        if e.resp.status in [401, 403]:
             raise AuthenticationError(
                 f"Authentication/Authorization error building service '{service_name}': {e.resp.status}. "
                 "Check permissions and credentials." 
             ) from e
        raise APIError(
            f"Failed to build service '{service_name}' {version} due to HTTP error {e.resp.status}.",
            status_code=e.resp.status,
            service=service_name
        ) from e
    except Exception as e:
        # Catch other potential errors during build (e.g., network issues)
        logger.error(
            f"An unexpected error occurred while building service '{service_name}' {version}: {e}",
            exc_info=config.DEBUG
        )
        raise APIError(f"Unexpected error building service '{service_name}': {e}", service=service_name) from e

# Example usage (for testing)
if __name__ == "__main__":
    # Requires successful authentication first via auth.py
    from auth import get_credentials
    try:
        creds = get_credentials()
        if creds:
            print("Building Classroom service...")
            classroom_service = build_service('classroom', 'v1', creds)
            print(f"Classroom service built: {type(classroom_service)}")

            print("\nBuilding Drive service...")
            drive_service = build_service('drive', 'v3', creds)
            print(f"Drive service built: {type(drive_service)}")

            print("\nBuilding Classroom service again (should use cache)...")
            classroom_service_cached = build_service('classroom', 'v1', creds)
            print(f"Classroom service (cached) built: {type(classroom_service_cached)}")
            print(f"Is same object? {classroom_service is classroom_service_cached}")

        else:
            print("Could not obtain credentials.")

    except AuthenticationError as e:
        print(f"Auth Error: {e}")
    except APIError as e:
        print(f"API Error: {e}")
    except FileNotFoundError as e:
        print(f"File Not Found Error: {e}. Make sure client_secrets.json exists.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
