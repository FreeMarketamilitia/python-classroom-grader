"""Handles OAuth 2.0 authentication for Google APIs."""

import os
import sys
from typing import List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.errors import HttpError

# Assuming config, logger, and error_handler are set up correctly
# Adjust imports based on final structure
try:
    import config
    from utils.logger import get_logger
    from utils.error_handler import AuthenticationError
except ImportError:
    # Adjust path if run directly or structure differs
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    import config
    from utils.logger import get_logger
    from utils.error_handler import AuthenticationError

logger = get_logger()

def get_credentials() -> Credentials:
    """Gets valid Google API credentials using OAuth 2.0 flow.

    Checks for existing tokens, refreshes if necessary, or runs the
    authorization flow if no valid tokens are found.

    Requires `client_secrets.json` to be present in the location
    specified by `config.CLIENT_SECRETS_FILE`.

    Returns:
        Credentials: Valid Google OAuth 2.0 credentials.

    Raises:
        AuthenticationError: If authentication fails or is cancelled.
        FileNotFoundError: If client_secrets.json is not found.
        ValueError: If client_secrets.json is improperly formatted.
    """
    creds: Optional[Credentials] = None

    # --- 1. Check for existing token file ---
    if os.path.exists(config.TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(config.TOKEN_FILE, config.SCOPES)
            logger.debug(f"Loaded credentials from {config.TOKEN_FILE}")
        except ValueError as e:
            logger.warning(f"Error loading token file {config.TOKEN_FILE}: {e}. Proceeding with re-authentication.")
            creds = None # Force re-authentication
        except Exception as e:
            logger.warning(f"Unexpected error loading token file {config.TOKEN_FILE}: {e}. Proceeding with re-authentication.")
            creds = None # Force re-authentication

    # --- 2. Check if credentials are valid or need refresh ---
    if creds and creds.valid:
        logger.info("Credentials are valid.")
        # Check if refresh is needed (optional, but good practice)
        if creds.expired and creds.refresh_token:
            logger.info("Credentials expired, attempting refresh...")
            try:
                creds.refresh(Request())
                logger.info("Credentials refreshed successfully.")
                # Save the refreshed credentials
                try:
                    with open(config.TOKEN_FILE, "w") as token_file:
                        token_file.write(creds.to_json())
                    logger.debug(f"Refreshed token saved to {config.TOKEN_FILE}")
                except IOError as e:
                    logger.warning(f"Failed to save refreshed token to {config.TOKEN_FILE}: {e}")
            except HttpError as e:
                logger.error(f"Credentials refresh failed with HTTP error: {e.resp.status} {e.content}", exc_info=config.DEBUG)
                # Delete potentially corrupted token file and force re-auth
                if os.path.exists(config.TOKEN_FILE):
                    os.remove(config.TOKEN_FILE)
                raise AuthenticationError(f"Failed to refresh token: {e.resp.status} Error. Please re-authenticate.") from e
            except Exception as e:
                logger.error(f"Credentials refresh failed unexpectedly: {e}", exc_info=config.DEBUG)
                # Delete potentially corrupted token file and force re-auth
                if os.path.exists(config.TOKEN_FILE):
                    os.remove(config.TOKEN_FILE)
                raise AuthenticationError(f"Failed to refresh token due to an unexpected error. Please re-authenticate.") from e
        return creds # Return valid (potentially refreshed) credentials

    # --- 3. Run authorization flow if no valid credentials ---
    if not creds or not creds.valid:
        if creds and creds.expired and not creds.refresh_token:
             logger.warning("Credentials expired and no refresh token available. Need to re-authenticate.")
        else:
             logger.info("No valid credentials found or refresh needed. Starting OAuth flow...")

        if not os.path.exists(config.CLIENT_SECRETS_FILE):
            logger.critical(f"CRITICAL: {config.CLIENT_SECRETS_FILE} not found. Cannot initiate OAuth flow.")
            logger.critical("Please download it from Google Cloud Console and place it in the root directory.")
            raise FileNotFoundError(f"{config.CLIENT_SECRETS_FILE} not found.")

        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                config.CLIENT_SECRETS_FILE, config.SCOPES
            )
            # port=0 selects a random available port
            # Force port 8081 as requested
            logger.info("Running local server for OAuth on port 8081...")
            creds = flow.run_local_server(port=8081) 
            logger.info("Authentication successful.")
        except FileNotFoundError:
             logger.critical(f"CRITICAL: {config.CLIENT_SECRETS_FILE} not found during OAuth flow.")
             raise
        except ValueError as e:
            logger.critical(f"CRITICAL: {config.CLIENT_SECRETS_FILE} seems improperly formatted: {e}")
            raise AuthenticationError(f"Invalid format in {config.CLIENT_SECRETS_FILE}: {e}") from e
        except Exception as e:
            logger.error(f"OAuth flow failed unexpectedly: {e}", exc_info=config.DEBUG)
            raise AuthenticationError(f"OAuth flow failed: {e}") from e

        # Save the new credentials for the next run
        if creds:
            try:
                with open(config.TOKEN_FILE, "w") as token_file:
                    token_file.write(creds.to_json())
                logger.debug(f"New token saved to {config.TOKEN_FILE}")
            except IOError as e:
                logger.warning(f"Failed to save new token to {config.TOKEN_FILE}: {e}")
        else:
             # This should not happen if flow.run_local_server succeeded without error
             # but handle defensively
             raise AuthenticationError("OAuth flow completed but no credentials were obtained.")

        return creds

    # Should be unreachable if logic is correct
    raise AuthenticationError("Reached unexpected state during credential retrieval.")

# Example usage (for testing - requires user interaction and client_secrets.json)
if __name__ == "__main__":
    logger.info("Attempting to get credentials...")
    try:
        credentials = get_credentials()
        logger.info("Successfully obtained credentials.")
        logger.info(f"Token valid: {credentials.valid}")
        logger.info(f"Token expired: {credentials.expired}")
        # Avoid logging the actual token
        logger.info(f"Refresh token exists: {bool(credentials.refresh_token)}")
    except FileNotFoundError as e:
        logger.error(f"Missing file: {e}")
    except AuthenticationError as e:
        logger.error(f"Authentication failed: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)
