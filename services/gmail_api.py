"""Wrapper for Gmail API interactions."""

import sys
import os
import base64
from email.mime.text import MIMEText
from typing import Any, Dict

from googleapiclient.discovery import Resource
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

# Assuming common setup is done correctly
try:
    import config
    from utils.logger import get_logger
    from utils.error_handler import APIError, AuthenticationError
    from utils.retry import retry_on_exception
    from api_clients import build_service
except ImportError:
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    import config
    from utils.logger import get_logger
    from utils.error_handler import APIError, AuthenticationError
    from utils.retry import retry_on_exception
    from api_clients import build_service

logger = get_logger()

# Define common retryable errors for Gmail
RETRYABLE_GMAIL_ERRORS = (HttpError, TimeoutError, ConnectionError)
RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)

def should_retry_gmail(e: Exception) -> bool:
    """Predicate function for retry decorator to check specific HttpError status codes for Gmail."""
    if isinstance(e, HttpError):
        return e.resp.status in RETRYABLE_STATUS_CODES
    return isinstance(e, (TimeoutError, ConnectionError))

class GmailService:
    """Provides methods to interact with the Gmail API."""

    SERVICE_NAME = 'gmail'
    VERSION = 'v1'

    def __init__(self, credentials: Credentials):
        """Initializes the GmailService.

        Args:
            credentials: Valid Google OAuth 2.0 credentials.

        Raises:
            AuthenticationError: If credentials are invalid.
            APIError: If the Gmail service cannot be built.
        """
        logger.debug("Initializing GmailService...")
        self.service: Resource = build_service(self.SERVICE_NAME, self.VERSION, credentials)
        logger.debug("GmailService initialized successfully.")

    def _create_message(self, sender: str, to: str, subject: str, message_text: str) -> Dict[str, str]:
        """Creates a MIME message structure for sending an email.

        Args:
            sender: The sender's email address (usually "me").
            to: The recipient's email address.
            subject: The subject of the email.
            message_text: The plain text body of the email.

        Returns:
            A dictionary containing the base64url encoded raw message string.
        """
        message = MIMEText(message_text)
        message['to'] = to
        # If sender is "me", Gmail API usually fills in the correct address.
        # Explicitly setting it might be necessary in some contexts or cause issues in others.
        # Let's rely on the API default behaviour for sender="me".
        # message['from'] = sender
        message['subject'] = subject

        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        return {'raw': raw_message}

    @retry_on_exception(exceptions=RETRYABLE_GMAIL_ERRORS, max_attempts=3)
    def send_email(self, to_email: str, subject: str, body: str, sender: str = "me") -> Dict[str, Any]:
        """Sends an email using the authenticated user's account.

        Args:
            to_email: The recipient's email address.
            subject: The email subject.
            body: The plain text email body.
            sender: The sender's email address (defaults to "me").

        Returns:
            The response from the Gmail API's send method (contains message ID).

        Raises:
            APIError: If the API call fails after retries.
            ValueError: If email parameters are invalid.
        """
        if not to_email or '@' not in to_email:
            raise ValueError(f"Invalid recipient email address: {to_email}")

        logger.info(f"Preparing to send email to <{to_email}> with subject: '{subject}'")

        try:
            message_body = self._create_message(sender, to_email, subject, body)

            sent_message = self.service.users().messages().send(
                userId=sender,
                body=message_body
            ).execute()

            logger.info(f"Successfully sent email to <{to_email}>. Message ID: {sent_message.get('id')}")
            return sent_message

        except HttpError as e:
            logger.error(f"Failed to send email to <{to_email}>: {e.resp.status} {e.content}", exc_info=config.DEBUG)
            if e.resp.status == 400:
                 # Often indicates malformed request, invalid recipient, etc.
                 logger.error(f"Bad request (400) sending email. Check recipient/body/subject. Content: {e.content}")
                 raise APIError(
                    f"Failed to send email due to bad request (400). Check parameters. Error: {e.content}",
                    status_code=400, service=self.SERVICE_NAME
                 ) from e
            if e.resp.status == 403:
                logger.warning(f"Permission denied (403) sending email from {sender}. Check API permissions/scopes.")
                raise APIError(
                   f"Permission denied (403) sending email from {sender}. Check Gmail API permissions.",
                   status_code=403, service=self.SERVICE_NAME
                ) from e
            raise APIError(
                f"Failed to send email to <{to_email}>: {e.resp.status}",
                status_code=e.resp.status,
                service=self.SERVICE_NAME
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error sending email to <{to_email}>: {e}", exc_info=config.DEBUG)
            raise APIError(f"Unexpected error sending email: {e}", service=self.SERVICE_NAME) from e

# Example usage (for testing - requires successful auth with gmail.send scope)
if __name__ == "__main__":
    from auth import get_credentials
    # --- !!! REPLACE WITH A VALID TEST RECIPIENT EMAIL !!! ---
    TEST_RECIPIENT_EMAIL: Optional[str] = None # e.g., "your_test_email@example.com"
    # ---------------------------------------------------------

    if not TEST_RECIPIENT_EMAIL:
        print("Please set TEST_RECIPIENT_EMAIL in the script to run the example.")
    else:
        try:
            creds = get_credentials()
            if creds:
                # Verify the necessary scope is present
                if "https://www.googleapis.com/auth/gmail.send" not in creds.scopes:
                     print("Error: The required scope 'https://www.googleapis.com/auth/gmail.send' is missing.")
                     print("Please re-authenticate ensuring this scope is requested in config.py and granted.")
                else:
                    print("Gmail send scope verified.")
                    gmail_service = GmailService(creds)

                    test_subject = "Gmail API Test Email"
                    test_body = "This is a test email sent via the Google Classroom AI Grader application using the Gmail API.\n\nRegards,\nYour App"

                    print(f"\n--- Attempting to send test email to: {TEST_RECIPIENT_EMAIL} ---")
                    try:
                        result = gmail_service.send_email(TEST_RECIPIENT_EMAIL, test_subject, test_body)
                        print(f"  Email sent successfully! Message ID: {result.get('id')}")
                    except (APIError, ValueError) as send_error:
                        print(f"Failed to send email: {send_error}")
            else:
                print("Could not obtain credentials.")

        except AuthenticationError as e:
            print(f"Auth Error: {e}")
        except FileNotFoundError as e:
            print(f"File Not Found Error: {e}. Make sure client_secrets.json exists.")
        except Exception as e:
            print(f"An unexpected error occurred: {e}", exc_info=True)

