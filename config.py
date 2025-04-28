"""Configuration settings for the Google Classroom AI Grader."""

import os
import logging
from typing import Final, List

# Debug flag: 1 = debug mode (verbose logging), 0 = production mode
DEBUG: Final[int] = int(os.environ.get("GRADER_DEBUG", "0"))

# --- Google API Settings ---

# Scopes required for Google APIs
# Ensure these match the scopes requested during the OAuth flow and enabled in GCP.
SCOPES: Final[List[str]] = [
    "https://www.googleapis.com/auth/classroom.courses.readonly",
    "https://www.googleapis.com/auth/classroom.coursework.students",
    "https://www.googleapis.com/auth/classroom.student-submissions.students.readonly",
    "https://www.googleapis.com/auth/classroom.rosters.readonly", # Added to potentially get student emails if needed
    "https://www.googleapis.com/auth/classroom.profile.emails", # Added to get student emails
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/forms.body.readonly", # Read form structure
    "https://www.googleapis.com/auth/forms.responses.readonly", # Read form responses
    "https://www.googleapis.com/auth/gmail.send",
]

# --- File Paths ---
# Get secrets file path from environment or use default
CLIENT_SECRETS_FILE: Final[str] = os.environ.get("CLIENT_SECRETS_PATH", "client_secrets.json")
# Token file will be stored in the same directory as the secrets file or project root
_token_dir = os.path.dirname(CLIENT_SECRETS_FILE) if os.path.dirname(CLIENT_SECRETS_FILE) else '.'
TOKEN_FILE: Final[str] = os.path.join(_token_dir, "token.json")
# Define log file path within a /logs subdirectory
LOG_DIR: Final[str] = "logs"
LOG_FILE: Final[str] = os.path.join(LOG_DIR, "grader_app.log")

# --- Gemini AI Settings ---

# Load Gemini API Key from environment variable
GEMINI_API_KEY: Final[str | None] = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY and DEBUG:
    logging.warning("GEMINI_API_KEY environment variable not set. Gemini functionality will be disabled.")
elif not GEMINI_API_KEY:
    raise ValueError("Missing required environment variable: GEMINI_API_KEY")

# --- Application Settings ---

# Default prompt template for Gemini feedback
# TODO: Consider making this configurable or adding options
GEMINI_PROMPT_TEMPLATE: Final[str] = """You are a helpful teaching assistant providing feedback on a student's assignment submission.

Focus on being constructive, specific, and encouraging.

Review the following submission content:

```
{submission_content}
```

Provide personalized feedback for the student:"""

# Pagination size for API list calls
DEFAULT_PAGE_SIZE: Final[int] = 50 # As per MVP requirements

# --- Logging Configuration ---
# LOG_LEVEL is used for file logging, console logging is only enabled in DEBUG mode
LOG_LEVEL = logging.DEBUG if DEBUG else logging.INFO
# Structured log format: timestamp, level, logger, module.function:line, message
LOG_FORMAT = '%(asctime)s | %(levelname)s | %(name)s | %(module)s.%(funcName)s:%(lineno)d | %(message)s'

# Basic check
if __name__ == "__main__":
    print(f"Debug Mode: {'On' if DEBUG else 'Off'}")
    print(f"Log Level: {logging.getLevelName(LOG_LEVEL)}")
    print(f"Client Secrets File: {CLIENT_SECRETS_FILE}")
    print(f"Token File: {TOKEN_FILE}")
    print(f"Log File: {LOG_FILE}")
    print(f"Gemini API Key Loaded: {'Yes' if GEMINI_API_KEY else 'No'}")
    print(f"Default Page Size: {DEFAULT_PAGE_SIZE}")
    print("Scopes:")
    for scope in SCOPES:
        print(f"- {scope}")
    print(f"Prompt Template:\n{GEMINI_PROMPT_TEMPLATE}")
