"""Wrapper for Google Drive API interactions."""

import sys
import os
import io
from typing import Any, Dict, Optional, Tuple

from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials

# Assuming common setup is done correctly
try:
    import config
    from utils.logger import get_logger
    from utils.error_handler import APIError, AuthenticationError, ContentExtractionError
    from utils.retry import retry_on_exception
    from api_clients import build_service
except ImportError:
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    import config
    from utils.logger import get_logger
    from utils.error_handler import APIError, AuthenticationError, ContentExtractionError
    from utils.retry import retry_on_exception
    from api_clients import build_service

logger = get_logger()

# Define common retryable errors for Drive
RETRYABLE_DRIVE_ERRORS = (HttpError, TimeoutError, ConnectionError)
RETRYABLE_STATUS_CODES = (403, 429, 500, 502, 503, 504) # Include 403 for potential rate limits

def should_retry_drive(e: Exception) -> bool:
    """Predicate function for retry decorator to check specific HttpError status codes for Drive.

    Retries on common transient errors including rate limits (403/429) and server errors (5xx).
    """
    if isinstance(e, HttpError):
        # Specific check for userRateLimitExceeded or rateLimitExceeded
        # content = getattr(e, 'content', b'').decode('utf-8')
        # if e.resp.status == 403 and ('userRateLimitExceeded' in content or 'rateLimitExceeded' in content):
        #     return True
        # General check for retryable status codes
        return e.resp.status in RETRYABLE_STATUS_CODES
    return isinstance(e, (TimeoutError, ConnectionError))

# MIME types for Google Workspace documents and their export equivalents
GOOGLE_DOCS_MIME_TYPES: Dict[str, str] = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain", # Or application/pdf
}

class DriveService:
    """Provides methods to interact with the Google Drive API."""

    SERVICE_NAME = 'drive'
    VERSION = 'v3'

    def __init__(self, credentials: Credentials):
        """Initializes the DriveService.

        Args:
            credentials: Valid Google OAuth 2.0 credentials.

        Raises:
            AuthenticationError: If credentials are invalid.
            APIError: If the Drive service cannot be built.
        """
        logger.debug("Initializing DriveService...")
        self.service: Resource = build_service(self.SERVICE_NAME, self.VERSION, credentials)
        logger.debug("DriveService initialized successfully.")

    @retry_on_exception(exceptions=RETRYABLE_DRIVE_ERRORS, max_attempts=3)
    def get_file_metadata(self, file_id: str, fields: str = "id, name, mimeType, parents") -> Dict[str, Any]:
        """Gets metadata for a specific file.

        Args:
            file_id: The ID of the file.
            fields: Comma-separated string of fields to retrieve (e.g., "id, name, mimeType").

        Returns:
            A dictionary containing the requested file metadata.

        Raises:
            APIError: If the API call fails after retries, including 404 Not Found.
        """
        logger.debug(f"Getting metadata for file ID: {file_id} with fields: {fields}")
        try:
            file_metadata = self.service.files().get(
                fileId=file_id,
                fields=fields,
                supportsAllDrives=True # Important for Shared Drive files
            ).execute()
            logger.debug(f"Successfully retrieved metadata for file: {file_metadata.get('name')}")
            return file_metadata
        except HttpError as e:
            logger.error(f"Failed to get metadata for file {file_id}: {e.resp.status} {e.content}", exc_info=config.DEBUG)
            if e.resp.status == 404:
                raise APIError(
                    f"File not found (404) with ID: {file_id}",
                    status_code=404,
                    service=self.SERVICE_NAME
                ) from e
            raise APIError(
                f"Failed to get metadata for file {file_id}: {e.resp.status}",
                status_code=e.resp.status,
                service=self.SERVICE_NAME
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error getting metadata for file {file_id}: {e}", exc_info=config.DEBUG)
            raise APIError(f"Unexpected error getting file metadata: {e}", service=self.SERVICE_NAME) from e

    @retry_on_exception(exceptions=RETRYABLE_DRIVE_ERRORS, max_attempts=3)
    def download_file_content(self, file_id: str) -> Tuple[str | None, bytes | None]:
        """Downloads or exports file content.

        Handles both standard Drive files and Google Workspace documents (exporting them).

        Args:
            file_id: The ID of the file.

        Returns:
            A tuple containing:
            - The determined MIME type of the *content* (e.g., text/plain for exported Doc).
            - The file content as bytes.
            Returns (None, None) if content cannot be retrieved or is empty.

        Raises:
            APIError: If the API call fails after retries.
            ContentExtractionError: If download/export fails for logical reasons.
        """
        logger.info(f"Attempting to download/export content for file ID: {file_id}...")
        try:
            # First, get mimeType to determine if it's a Google Doc that needs export
            metadata = self.get_file_metadata(file_id, fields="id, name, mimeType")
            original_mime_type = metadata.get('mimeType')
            file_name = metadata.get('name', 'unknown_file')
            logger.debug(f"File '{file_name}' has MIME type: {original_mime_type}")

            request: Any
            target_mime_type: Optional[str] = original_mime_type

            if original_mime_type in GOOGLE_DOCS_MIME_TYPES:
                # Export Google Workspace files
                target_mime_type = GOOGLE_DOCS_MIME_TYPES[original_mime_type]
                logger.debug(f"Exporting Google Workspace file as {target_mime_type}...")
                request = self.service.files().export_media(
                    fileId=file_id,
                    mimeType=target_mime_type
                )
            elif original_mime_type and original_mime_type.startswith('application/vnd.google-apps'):
                 # Other Google Workspace types not explicitly handled (e.g., Forms, Sites, Drawings)
                 logger.warning(f"Cannot directly download content for Google Workspace type: {original_mime_type}. Skipping file {file_id} ('{file_name}').")
                 # Forms content needs to be fetched via Forms API
                 raise ContentExtractionError(f"Unsupported Google Workspace type for direct download: {original_mime_type}")
            else:
                # Download other file types directly
                logger.debug("Downloading standard Drive file...")
                request = self.service.files().get_media(
                    fileId=file_id,
                    supportsAllDrives=True
                )

            # Execute the download/export request
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if config.DEBUG:
                    logger.debug(f"Download progress: {int(status.progress() * 100)}%")

            content = fh.getvalue()
            logger.info(f"Successfully downloaded/exported {len(content)} bytes for file '{file_name}' ({file_id}). Target MIME type: {target_mime_type}")
            return target_mime_type, content

        except HttpError as e:
            logger.error(f"Failed to download/export file {file_id}: {e.resp.status} {e.content}", exc_info=config.DEBUG)
            if e.resp.status == 404:
                raise APIError(
                    f"File not found (404) for download/export: {file_id}",
                    status_code=404, service=self.SERVICE_NAME
                ) from e
            # 403 could be permission or rate limit - retry handles rate limit
            if e.resp.status == 403:
                 logger.warning(f"Permission denied (403) downloading/exporting file {file_id}. Check file access permissions.")
                 raise APIError(
                    f"Permission denied (403) downloading/exporting file {file_id}.",
                    status_code=403, service=self.SERVICE_NAME
                 ) from e
            raise APIError(
                f"Failed to download/export file {file_id}: {e.resp.status}",
                status_code=e.resp.status,
                service=self.SERVICE_NAME
            ) from e
        except ContentExtractionError: # Re-raise specific extraction errors
            raise
        except Exception as e:
            logger.error(f"Unexpected error downloading/exporting file {file_id}: {e}", exc_info=config.DEBUG)
            raise ContentExtractionError(f"Unexpected error downloading/exporting file {file_id}: {e}") from e

# Example usage (for testing - requires successful auth and a valid file ID)
if __name__ == "__main__":
    from auth import get_credentials
    # --- !!! REPLACE WITH A VALID FILE ID YOU HAVE ACCESS TO !!! ---
    # Find one via Google Drive UI (URL) or list_files (not implemented here)
    TEST_FILE_ID: Optional[str] = None # e.g., "1aBcDeFgHiJkLmNoPqRsTuVwXyZ12345AbCdEfG"
    # TEST_FILE_ID = "YOUR_TEST_GOOGLE_DOC_ID_HERE" # Example for a Google Doc
    # TEST_FILE_ID = "YOUR_TEST_PDF_ID_HERE"      # Example for a PDF
    # -------------------------------------------------------------

    if not TEST_FILE_ID:
        print("Please set TEST_FILE_ID in the script to run the example.")
    else:
        try:
            creds = get_credentials()
            if creds:
                drive = DriveService(creds)

                # 1. Get Metadata
                print(f"\n--- Getting Metadata for File ID: {TEST_FILE_ID} ---")
                try:
                    metadata = drive.get_file_metadata(TEST_FILE_ID)
                    print(f"  Name: {metadata.get('name')}")
                    print(f"  MIME Type: {metadata.get('mimeType')}")
                    print(f"  ID: {metadata.get('id')}")
                except APIError as meta_error:
                    print(f"Failed to get metadata: {meta_error}")
                    # Exit if metadata fails, as download depends on it
                    sys.exit(1)

                # 2. Download Content
                print(f"\n--- Downloading/Exporting Content for File ID: {TEST_FILE_ID} ---")
                try:
                    content_mime_type, content_bytes = drive.download_file_content(TEST_FILE_ID)
                    if content_bytes is not None:
                        print(f"  Successfully downloaded/exported {len(content_bytes)} bytes.")
                        print(f"  Content MIME Type: {content_mime_type}")
                        # Optionally save or display content (be careful with large files)
                        if content_mime_type and content_mime_type.startswith('text/'):
                            print("\n  Content Preview (first 500 chars):")
                            try:
                                print(content_bytes[:500].decode('utf-8', errors='ignore'))
                            except Exception as decode_err:
                                print(f"    Could not decode as UTF-8: {decode_err}")
                        else:
                            print("  Content is binary or non-text, not previewing.")
                            # Example: Save binary content
                            # try:
                            #     save_name = metadata.get('name', 'downloaded_file')
                            #     with open(save_name, 'wb') as f:
                            #         f.write(content_bytes)
                            #     print(f"  Binary content saved as {save_name}")
                            # except IOError as save_err:
                            #     print(f"  Error saving file: {save_err}")
                    else:
                        print("  Download returned no content.")
                except (APIError, ContentExtractionError) as download_error:
                    print(f"Failed to download/export content: {download_error}")

            else:
                print("Could not obtain credentials.")

        except AuthenticationError as e:
            print(f"Auth Error: {e}")
        except FileNotFoundError as e:
            print(f"File Not Found Error: {e}. Make sure client_secrets.json exists.")
        except Exception as e:
            print(f"An unexpected error occurred: {e}", exc_info=True)
