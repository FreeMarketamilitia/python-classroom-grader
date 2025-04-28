# Google Classroom AI Grading Assistant (Python MVP)

This project provides a Python-based CLI tool to help teachers automate parts of the grading process for Google Classroom assignments.

It uses official Google APIs (Classroom, Drive, Docs, Forms, Gmail) and the Google Gemini API to:

*   Fetch courses and assignments.
*   Retrieve student submissions (Google Docs, Drive files, Forms).
*   Extract text content from submissions.
*   Generate AI-powered feedback using Gemini.
*   Post feedback as private comments back to Google Classroom.
*   Email feedback directly to students.

**Disclaimer:** This is an MVP (Minimum Viable Product). Automated grading and feedback should always be reviewed by the teacher before finalizing grades or sending comments.

## Features

*   OAuth 2.0 Authentication with Google.
*   CLI interface for selecting courses and assignments.
*   Handles submissions via Google Drive files (exporting Docs/Sheets/Slides to text), and Google Forms.
*   Integrates with Gemini API for feedback generation.
*   Posts feedback as private comments.
*   Sends feedback via Gmail.
*   Configurable logging (debug/info levels).
*   Basic retry mechanism for transient API errors.

## Setup

1.  **Clone the Repository:**
    ```bash
    git clone <repository_url>
    cd classroom-ai-grader 
    ```

2.  **Create a Virtual Environment:**
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Google Cloud Setup:**
    *   Create a project in the [Google Cloud Console](https://console.cloud.google.com/).
    *   Enable the following APIs for your project:
        *   Google Classroom API
        *   Google Drive API
        *   Google Docs API
        *   Google Forms API
        *   Gmail API
    *   Go to "Credentials" -> "Create Credentials" -> "OAuth client ID".
    *   Select "Desktop app" as the application type.
    *   Download the credentials JSON file.
    *   **Add `http://localhost:8081` to the list of Authorized redirect URIs** in the OAuth client settings in Google Cloud Console.
    *   **Rename the downloaded file to `client_secrets.json` and place it in the root directory of this project (`classroom_ai_grader/`), OR set the `CLIENT_SECRETS_PATH` environment variable in your `.env` file to point to its location.**

5.  **Gemini API Key:**
    *   Obtain a Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey).
    *   Create a file named `.env` in the project root directory (`classroom_ai_grader/`) by copying the example:
        ```bash
        cp .env.example .env
        ```
    *   **Edit the `.env` file and replace `"YOUR_GEMINI_API_KEY_HERE"` with your actual Gemini API key.**
    *   *(Optional)* If you placed `client_secrets.json` somewhere other than the project root, uncomment and set the `CLIENT_SECRETS_PATH` variable in `.env`.

6.  **(Optional) Debug Mode:**
    *   Edit the `.env` file and set `GRADER_DEBUG=1` for verbose logging.

## Usage

Ensure your virtual environment is active (`source venv/bin/activate`).

Run the main script from the `classroom_ai_grader` directory:

```bash
python main.py
```

*   The first time you run it, you will be prompted to authorize the application via your web browser. Follow the instructions (this will use `http://localhost:8081`).
*   A `token.json` file will be created to store your authorization token for future runs.
*   Follow the CLI prompts to select your course and assignment.
*   Confirm the actions (processing, posting comments, sending emails).
*   Logs will be written to `grader_app.log`.
*   Logs will be written to `logs/grader_app.log`.

## Project Structure

```
classroom_ai_grader/
├── core/                 # Core application logic (Grader class)
│   ├── __init__.py
│   └── grader.py
├── services/             # Wrappers for external APIs
│   ├── __init__.py
│   ├── api_clients.py    # Factory for building Google API clients
│   ├── classroom_api.py
│   ├── docs_api.py
│   ├── drive_api.py
│   ├── forms_api.py
│   ├── gemini_ai.py
│   └── gmail_api.py
├── ui/                   # User interface elements (CLI)
│   ├── __init__.py
│   └── cli.py
├── utils/                # Utility functions (logging, errors, retry)
│   ├── __init__.py
│   ├── error_handler.py
│   ├── logger.py
│   └── retry.py
├── tests/                # Unit/Integration tests (optional)
│   └── __init__.py
├── logs/                 # Log files (created automatically)
├── .env                  # Local environment variables (ignored by git)
├── .env.example          # Example environment variables
├── .gitignore            # Git ignore file
├── auth.py               # Handles Google OAuth 2.0 flow
├── config.py             # Configuration settings
├── main.py               # Main execution script
├── prd.md                # Product Requirements Document
├── README.md             # This file
└── requirements.txt      # Python dependencies
```

## TODO / Future Improvements

*   Implement automated grading logic (MVP only posts comments/emails).
*   Support non-text attachments (images, PDFs).
*   More robust error handling and recovery.
*   Better handling of multiple attachments per submission.
*   More sophisticated Form response matching (e.g., using respondent email).
*   Allow configuration of Gemini prompt/model/safety settings.
*   Add unit and integration tests.
*   Refactor for potential web UI.
