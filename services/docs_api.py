"""Wrapper for Google Docs API interactions."""

import sys
import os
from typing import Any, Dict

from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError
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

# Define common retryable errors for Docs
RETRYABLE_DOCS_ERRORS = (HttpError, TimeoutError, ConnectionError)
RETRYABLE_STATUS_CODES = (403, 429, 500, 502, 503, 504) # Include 403 for potential rate limits

def should_retry_docs(e: Exception) -> bool:
    """Predicate function for retry decorator to check specific HttpError status codes for Docs."""
    if isinstance(e, HttpError):
        return e.resp.status in RETRYABLE_STATUS_CODES
    return isinstance(e, (TimeoutError, ConnectionError))

class DocsService:
    """Provides methods to interact with the Google Docs API."""

    SERVICE_NAME = 'docs'
    VERSION = 'v1'

    def __init__(self, credentials: Credentials):
        """Initializes the DocsService.

        Args:
            credentials: Valid Google OAuth 2.0 credentials.

        Raises:
            AuthenticationError: If credentials are invalid.
            APIError: If the Docs service cannot be built.
        """
        logger.debug("Initializing DocsService...")
        self.service: Resource = build_service(self.SERVICE_NAME, self.VERSION, credentials)
        logger.debug("DocsService initialized successfully.")

    @retry_on_exception(exceptions=RETRYABLE_DOCS_ERRORS, max_attempts=3)
    def get_document_content(self, document_id: str) -> str:
        """Retrieves and extracts the text content of a Google Document.

        Args:
            document_id: The ID of the Google Document.

        Returns:
            The extracted text content as a single string.

        Raises:
            APIError: If the API call fails after retries (including 404).
            ContentExtractionError: If the document structure is unexpected or content cannot be parsed.
        """
        logger.info(f"Fetching content for Google Document ID: {document_id}...")
        try:
            document = self.service.documents().get(documentId=document_id).execute()
            logger.debug(f"Successfully retrieved document object for ID: {document_id}")

            # Extract text from the document body content
            # The content is structured in a list of Structural Elements.
            # We need to iterate through them and extract text runs.
            content = document.get('body', {}).get('content', [])
            extracted_text = ""
            for element in content:
                if 'paragraph' in element:
                    paragraph = element.get('paragraph')
                    for paragraph_element in paragraph.get('elements', []):
                        text_run = paragraph_element.get('textRun')
                        if text_run:
                            extracted_text += text_run.get('content', '')
                elif 'table' in element:
                    # Handle tables: iterate through rows and cells
                    table = element.get('table')
                    for row in table.get('tableRows', []):
                        for cell in row.get('tableCells', []):
                            # Recursively process content within the cell
                            for cell_element in cell.get('content', []):
                                if 'paragraph' in cell_element:
                                     cell_paragraph = cell_element.get('paragraph')
                                     for cell_para_element in cell_paragraph.get('elements', []):
                                         cell_text_run = cell_para_element.get('textRun')
                                         if cell_text_run:
                                             extracted_text += cell_text_run.get('content', '')
                        extracted_text += '\n' # Add newline after each table row
                # TODO: Handle other structural elements if needed (e.g., lists, images - skip images for now)

            if not extracted_text:
                 logger.warning(f"Extracted empty content from document {document_id}. Title: {document.get('title')}")
            else:
                 logger.info(f"Successfully extracted {len(extracted_text)} characters from document {document_id}.")

            return extracted_text.strip()

        except HttpError as e:
            logger.error(f"Failed to get document {document_id}: {e.resp.status} {e.content}", exc_info=config.DEBUG)
            if e.resp.status == 404:
                raise APIError(
                    f"Google Document not found (404) with ID: {document_id}",
                    status_code=404, service=self.SERVICE_NAME
                ) from e
            if e.resp.status == 403:
                 logger.warning(f"Permission denied (403) accessing document {document_id}. Check permissions.")
                 raise APIError(
                    f"Permission denied (403) accessing document {document_id}.",
                    status_code=403, service=self.SERVICE_NAME
                 ) from e
            raise APIError(
                f"Failed to get document {document_id}: {e.resp.status}",
                status_code=e.resp.status,
                service=self.SERVICE_NAME
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error getting or parsing document {document_id}: {e}", exc_info=config.DEBUG)
            raise ContentExtractionError(f"Unexpected error getting/parsing document {document_id}: {e}") from e

# Example usage (for testing - requires successful auth and a valid Google Doc ID)
if __name__ == "__main__":
    from auth import get_credentials
    # --- !!! REPLACE WITH A VALID GOOGLE DOC ID YOU HAVE ACCESS TO !!! ---
    TEST_DOC_ID: Optional[str] = None # e.g., "1aBcDeFgHiJkLmNoPqRsTuVwXyZ12345AbCdEfG_doc"
    # -------------------------------------------------------------------

    if not TEST_DOC_ID:
        print("Please set TEST_DOC_ID in the script to run the example.")
    else:
        try:
            creds = get_credentials()
            if creds:
                docs_service = DocsService(creds)

                print(f"\n--- Getting Content for Doc ID: {TEST_DOC_ID} ---")
                try:
                    content = docs_service.get_document_content(TEST_DOC_ID)
                    print(f"Successfully extracted {len(content)} characters.")
                    print("\n--- Extracted Content (first 1000 chars) ---")
                    print(content[:1000])
                    print("--------------------------------------------")
                except (APIError, ContentExtractionError) as e:
                    print(f"Failed to get document content: {e}")

            else:
                print("Could not obtain credentials.")

        except AuthenticationError as e:
            print(f"Auth Error: {e}")
        except FileNotFoundError as e:
            print(f"File Not Found Error: {e}. Make sure client_secrets.json exists.")
        except Exception as e:
            print(f"An unexpected error occurred: {e}", exc_info=True)
