"""Main execution script for the Google Classroom AI Grader."""

import sys
import os

# Try to load environment variables from .env file if python-dotenv is available
try:
    from dotenv import load_dotenv
    load_dotenv() # Load variables from .env into environment
    print("Loaded environment variables from .env file.")
except ImportError:
    # python-dotenv is optional, continue without it
    print("python-dotenv not found, skipping .env file loading. Ensure environment variables are set.")
    pass

# Now, setup paths and import project modules
# Ensure the project root directory is in the Python path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import config # Should be available now due to path setup or being in the same dir
    from utils.logger import setup_logger, get_logger
    from utils.error_handler import (AuthenticationError, APIError, ConfigError,
                                     GradingError, UserCancelledError, ContentExtractionError,
                                     BaseGraderException)
    import auth
    # Import Services
    from services.classroom_api import ClassroomService
    from services.drive_api import DriveService
    from services.docs_api import DocsService
    from services.forms_api import FormsService
    from services.gmail_api import GmailService
    from services.gemini_ai import GeminiClient
    # Import Core Logic
    from core.grader import Grader
    # Import UI
    import ui.cli as cli
except ImportError as e:
    print(f"Fatal Error: Could not import necessary modules: {e}", file=sys.stderr)
    print("Please ensure the script is run from the project root directory", file=sys.stderr)
    print(f"Current working directory: {os.getcwd()}", file=sys.stderr)
    print(f"Python path: {sys.path}", file=sys.stderr)
    sys.exit(1)

# Initialize logger as early as possible after config is loaded
logger = setup_logger()

def main():
    """Main function to run the grading assistant workflow."""
    logger.info("Starting Google Classroom AI Grader main workflow.")
    cli.display_welcome()

    credentials = None
    classroom_service = None
    drive_service = None
    docs_service = None
    forms_service = None
    gmail_service = None
    gemini_client = None
    grader_instance = None

    try:
        # --- Step 1: Authentication --- 
        cli.display_step(1, "Authenticating with Google...")
        credentials = auth.get_credentials()
        cli.display_success("Authentication successful.")

        # --- Step 2: Initialize Services --- 
        cli.display_step(2, "Initializing API Services...")
        classroom_service = ClassroomService(credentials)
        drive_service = DriveService(credentials)
        docs_service = DocsService(credentials)
        forms_service = FormsService(credentials)
        gmail_service = GmailService(credentials)

        # Initialize Gemini only if API key exists
        if config.GEMINI_API_KEY:
            try:
                gemini_client = GeminiClient()
                cli.display_success("Gemini AI Client initialized.")
            except ConfigError as e:
                 logger.error(f"Gemini configuration error: {e}")
                 cli.display_warning(f"Could not initialize Gemini Client: {e}. AI feedback will be disabled.")
        else:
             cli.display_warning("GEMINI_API_KEY not found. AI feedback generation will be disabled.")

        # Instantiate the Grader
        grader_instance = Grader(
            classroom_service, drive_service, docs_service,
            forms_service, gmail_service, gemini_client
        )
        cli.display_success("All required services initialized.")

        # --- Step 3: Select Course --- 
        cli.display_step(3, "Fetching Your Courses...")
        courses = classroom_service.list_courses()
        if not courses:
            cli.display_error("No active courses found for your account. Exiting.")
            return
        selected_course = cli.prompt_for_selection(courses, cli.format_course_for_display, "Please select a course to grade:")
        if not selected_course:
             # prompt_for_selection raises UserCancelledError if cancelled
             return # Should not be reached if cancelled
        course_id = selected_course['id']
        logger.info(f"User selected course: {selected_course['name']} (ID: {course_id})")

        # --- Step 4: Select Assignment --- 
        cli.display_step(4, f"Fetching Assignments for course '{selected_course['name']}'...")
        assignments = classroom_service.list_assignments(course_id)
        if not assignments:
            cli.display_error(f"No assignments found for course '{selected_course['name']}'. Exiting.")
            return
        selected_assignment = cli.prompt_for_selection(assignments, cli.format_assignment_for_display, "Please select an assignment to grade:")
        if not selected_assignment:
             return # Should not be reached if cancelled
        assignment_id = selected_assignment['id']
        logger.info(f"User selected assignment: {selected_assignment['title']} (ID: {assignment_id})")

        # --- Step 5: Process Submissions --- 
        cli.display_step(5, f"Processing Submissions for assignment '{selected_assignment['title']}'...")
        if not cli.confirm_action(f"Process {selected_assignment['title']}? This may take some time.", default=True):
            raise UserCancelledError("User cancelled processing.")

        processed_submissions = grader_instance.process_assignment(course_id, assignment_id)

        # --- Step 6: Display Summary --- 
        cli.display_step(6, "Displaying Processing Summary...")
        cli.display_processed_summary(processed_submissions)

        if not processed_submissions:
            cli.display_warning("No submissions were processed, cannot proceed with actions.")
            return

        # Check if there is any feedback generated before offering actions
        has_feedback = any(sub.get('feedback') for sub in processed_submissions)
        has_successful_processing = any(not sub.get('error') for sub in processed_submissions)

        if not has_successful_processing:
             cli.display_warning("No submissions were processed successfully. Cannot apply comments or email feedback.")
             return

        # --- Step 7: Apply Grades as Drafts (Optional) ---
        cli.display_step(7, "Apply Grades as Drafts (Teacher Review Required)...")
        if cli.confirm_action("Apply grades as drafts to submissions in Google Classroom? (Teachers can review and finalize)", default=True):
            grader_instance.apply_grades_and_comments(course_id, assignment_id, processed_submissions, apply_grades=True, post_comments=False)
            cli.display_success("Draft grades were patched to Classroom. Teachers must review and return them manually.")
        else:
            logger.info("User skipped applying grades.")

        # --- Step 8: Post Comments (Optional) --- 
        cli.display_step(8, "Post Feedback as Private Comments...")
        if not has_feedback:
             cli.display_warning("No feedback was generated (check Gemini setup/errors). Cannot post comments.")
        elif cli.confirm_action("Post generated feedback as private comments to Classroom?", default=True):
            grader_instance.apply_grades_and_comments(course_id, assignment_id, processed_submissions, post_comments=True)
            cli.display_success("Attempted to post comments where feedback was available.")
        else:
            logger.info("User skipped posting comments.")

        # --- Step 8: Send Emails (Optional) --- 
        cli.display_step(8, "Email Feedback to Students...")
        if not has_feedback:
             cli.display_warning("No feedback was generated. Cannot email feedback.")
        elif cli.confirm_action("Send feedback emails to students (where email and feedback are available)?", default=False):
            grader_instance.email_feedback(processed_submissions)
            cli.display_success("Attempted to send feedback emails.")
        else:
            logger.info("User skipped sending emails.")

    except FileNotFoundError as e:
        logger.critical(f"Configuration file not found: {e}. Please ensure required files (e.g., client_secrets.json) are present.")
        cli.display_error(f"Missing required file: {e}")
    except (AuthenticationError, ConfigError) as e:
        logger.critical(f"Setup or Authentication Error: {e}", exc_info=config.DEBUG)
        cli.display_error(f"Setup Error: {e}")
    except APIError as e:
        logger.error(f"Google API Error: {e}", exc_info=config.DEBUG)
        cli.display_error(f"API Error ({e.service or 'Unknown'}): {e}")
    except UserCancelledError as e:
        logger.info(f"Operation cancelled by user: {e}")
        cli.display_warning(f"Operation cancelled: {e}")
    except KeyboardInterrupt:
         logger.info("Operation interrupted by user (Ctrl+C).")
         cli.display_warning("Operation interrupted.")
    except Exception as e:
        # Catch-all for unexpected errors
        logger.critical(f"An unexpected error occurred: {e}", exc_info=True)
        cli.display_error(f"An unexpected error occurred: {e}. Check logs for details.")
    finally:
        cli.display_farewell()

if __name__ == "__main__":
    # Basic check for client secrets file before starting
    if not os.path.exists(config.CLIENT_SECRETS_FILE):
         print(f"[ERROR] {config.CLIENT_SECRETS_FILE} not found in {os.getcwd()}.")
         print("Please download your OAuth 2.0 Client credentials from Google Cloud Console")
         print("and save the file as 'client_secrets.json' in the project directory.")
         sys.exit(1)
    # Check for Gemini Key only if DEBUG is off, as it's checked later otherwise
    if not config.DEBUG and not config.GEMINI_API_KEY:
         print("[ERROR] GEMINI_API_KEY environment variable not set.")
         print("Please set this variable to enable AI feedback generation.")
         # Optionally exit, or let the main logic handle the warning
         # sys.exit(1)

    main()
