"""Wrapper for Google Gemini API interactions."""

import sys
import os
from typing import Any, Dict, Optional

# Use the official Google Generative AI library
import google.generativeai as genai
from google.api_core import exceptions as google_api_exceptions

# Assuming common setup is done correctly
try:
    import config
    from utils.logger import get_logger
    from utils.error_handler import APIError, ConfigError, GradingError
    # Note: Standard retry might not apply perfectly to generative models
    # as failures can be content-based (safety) rather than transient network issues.
    # We will handle specific API exceptions instead.
    # from utils.retry import retry_on_exception
except ImportError:
    # Adjust path if run directly or structure differs
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    import config
    from utils.logger import get_logger
    from utils.error_handler import APIError, ConfigError, GradingError

logger = get_logger()

# Consider making model name configurable
DEFAULT_GEMINI_MODEL = "gemini-1.5-flash-latest" # Or "gemini-pro"

class GeminiClient:
    """Provides methods to interact with the Google Gemini API."""

    def __init__(self, api_key: Optional[str] = config.GEMINI_API_KEY):
        """Initializes the GeminiClient.

        Args:
            api_key: The Gemini API key. Defaults to the value from config.

        Raises:
            ConfigError: If the API key is not provided or found.
        """
        logger.debug("Initializing GeminiClient...")
        if not api_key:
            logger.critical("Gemini API Key is missing. Check config.py and environment variables.")
            raise ConfigError("GEMINI_API_KEY not found or provided.")
        try:
            genai.configure(api_key=api_key)
            # Optionally, verify the API key is valid here with a simple call if available,
            # but typically configuration is enough, and errors appear during generation.
            self.model = genai.GenerativeModel(DEFAULT_GEMINI_MODEL)
            logger.info(f"GeminiClient initialized successfully with model: {DEFAULT_GEMINI_MODEL}")
        except Exception as e:
             logger.critical(f"Failed to configure Gemini API: {e}", exc_info=config.DEBUG)
             # This could be due to invalid key format or other issues
             raise ConfigError(f"Failed to configure Gemini API: {e}") from e

    def generate_feedback(self, submission_content: str, prompt_template: str = config.GEMINI_PROMPT_TEMPLATE) -> str:
        """Generates feedback for student submission using the Gemini model.

        Args:
            submission_content: The text content of the student's submission.
            prompt_template: The template string for the prompt, containing {submission_content}.

        Returns:
            The generated feedback text.

        Raises:
            GradingError: If feedback generation fails due to API errors, safety settings, or empty response.
            ValueError: If the prompt template is invalid.
        """
        if not submission_content:
            logger.warning("Submission content is empty, cannot generate feedback.")
            return "(Submission content was empty)"

        if '{submission_content}' not in prompt_template:
            logger.error("Invalid prompt template: Missing '{submission_content}' placeholder.")
            raise ValueError("Invalid prompt template: Missing '{submission_content}' placeholder.")

        prompt = prompt_template.format(submission_content=submission_content)

        logger.info(f"Generating Gemini feedback using model {self.model.model_name}...")
        if config.DEBUG:
            # Avoid logging potentially large submission content unless debugging
            logger.debug(f"Generated prompt (first 500 chars):\n{prompt[:500]}...")

        try:
            # Configure safety settings - adjust as needed
            # Blocking threshold options: BLOCK_NONE, BLOCK_ONLY_HIGH, BLOCK_MEDIUM_AND_ABOVE, BLOCK_LOW_AND_ABOVE
            safety_settings = {
                # genai.types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
                # genai.types.HarmCategory.HARM_CATEGORY_HATE_SPEECH: genai.types.HarmBlockThreshold.BLOCK_NONE,
                # genai.types.HarmCategory.HARM_CATEGORY_HARASSMENT: genai.types.HarmBlockThreshold.BLOCK_NONE,
                # genai.types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: genai.types.HarmBlockThreshold.BLOCK_NONE,
                # More restrictive default:
                 genai.types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: genai.types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                 genai.types.HarmCategory.HARM_CATEGORY_HATE_SPEECH: genai.types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                 genai.types.HarmCategory.HARM_CATEGORY_HARASSMENT: genai.types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
                 genai.types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: genai.types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            }

            response = self.model.generate_content(
                 prompt,
                 safety_settings=safety_settings,
                 # Add generation_config if needed (temperature, top_p, etc.)
                 # generation_config=genai.types.GenerationConfig(temperature=0.7)
            )

            # Check for blocked content or empty response
            if not response.candidates:
                 logger.error("Gemini response missing candidates. Potential safety block or other issue.")
                 # Log detailed safety ratings if available
                 try:
                      logger.error(f"Prompt Feedback: {response.prompt_feedback}")
                 except ValueError:
                      logger.error("Could not access prompt feedback details.")
                 raise GradingError("Failed to generate feedback: Response was empty or blocked (no candidates). Check safety settings or prompt.")

            # Accessing generated text - handle potential structure variations
            # Check if parts exist and are not empty before accessing parts[0]
            if response.candidates[0].content and response.candidates[0].content.parts:
                 feedback_text = response.candidates[0].content.parts[0].text
            else:
                 # Log the entire candidate to understand the structure
                 logger.error(f"Unexpected Gemini response structure or empty parts: {response.candidates[0]}")
                 # Check safety ratings even if parts are missing
                 try:
                     if response.candidates[0].finish_reason == genai.types.FinishReason.SAFETY:
                         logger.error(f"Feedback generation stopped due to safety. Ratings: {response.candidates[0].safety_ratings}")
                         raise GradingError(f"Feedback generation blocked due to safety settings. Ratings: {response.candidates[0].safety_ratings}")
                 except (ValueError, AttributeError): # Handle potential errors accessing attributes
                      logger.error("Could not access finish reason or safety ratings on candidate.")

                 raise GradingError("Failed to parse feedback: Unexpected response structure or empty parts.")


            if not feedback_text:
                logger.warning("Gemini generated empty feedback text.")
                # Check if blocked due to safety
                try:
                    finish_reason = response.candidates[0].finish_reason
                    safety_ratings = response.candidates[0].safety_ratings
                    if finish_reason == genai.types.FinishReason.SAFETY:
                        logger.error(f"Feedback generation stopped due to safety reasons. Ratings: {safety_ratings}")
                        raise GradingError(f"Feedback generation blocked due to safety settings. Ratings: {safety_ratings}")
                    else:
                         # Could be other reasons like length, or just empty generation
                         logger.warning(f"Gemini returned empty feedback. Finish Reason: {finish_reason}")
                         return "(AI feedback generation resulted in empty text)" # Return placeholder
                except (ValueError, AttributeError):
                     logger.error("Could not access finish reason or safety ratings when checking empty feedback.")
                     return "(AI feedback generation resulted in empty text - error checking reason)"


            logger.info(f"Successfully generated Gemini feedback ({len(feedback_text)} chars).")
            return feedback_text.strip()

        except google_api_exceptions.GoogleAPIError as e:
            # Catch specific Google API errors (includes rate limits, auth issues etc.)
            logger.error(f"Gemini API error during feedback generation: {e}", exc_info=config.DEBUG)
            # Handle specific status codes if needed
            if isinstance(e, google_api_exceptions.PermissionDenied):
                 raise GradingError("Permission denied calling Gemini API (403). Check API key/permissions.") from e
            if isinstance(e, google_api_exceptions.ResourceExhausted): # Rate limit
                 raise GradingError("Gemini API rate limit exceeded (429). Please try again later.") from e
            if isinstance(e, google_api_exceptions.InvalidArgument):
                 logger.error(f"Invalid argument sent to Gemini API (400): {e}", exc_info=config.DEBUG)
                 raise GradingError(f"Invalid request sent to Gemini API (400): {e}") from e
            raise GradingError(f"Gemini API error: {e}") from e
        except Exception as e:
            # Catch other unexpected errors (network, library issues)
            logger.error(f"Unexpected error during Gemini feedback generation: {e}", exc_info=config.DEBUG)
            raise GradingError(f"Unexpected error generating feedback: {e}") from e

# Example usage (for testing - requires GEMINI_API_KEY env var)
if __name__ == "__main__":
    # Ensure config is loaded by running this script within the project structure
    # or adjusting paths if run standalone.
    if not config.GEMINI_API_KEY:
        print("Error: GEMINI_API_KEY environment variable not set.")
        print("Please set it to run the Gemini example.")
    else:
        try:
            client = GeminiClient()
            print("Gemini client initialized.")

            test_submission = (
                "The main causes of the French Revolution were social inequality, \n"
                "economic hardship, and Enlightenment ideas. The Third Estate was \n"
                "heavily taxed while the clergy and nobility were largely exempt. \n"
                "Poor harvests led to high bread prices, causing widespread hunger. \n"
                "Philosophers like Rousseau promoted ideas of liberty and popular sovereignty."
            )

            print("\n--- Generating feedback for test submission ---")
            try:
                feedback = client.generate_feedback(test_submission)
                print("\n--- Generated Feedback ---")
                print(feedback)
                print("--------------------------")
            except (GradingError, ValueError) as e:
                print(f"Failed to generate feedback: {e}")

            print("\n--- Testing empty submission ---")
            try:
                feedback_empty = client.generate_feedback("")
                print(f"Feedback for empty submission: {feedback_empty}")
            except (GradingError, ValueError) as e:
                print(f"Failed for empty submission (as expected?): {e}")

            # Example of potential safety block (modify if needed to trigger)
            # print("\n--- Testing potentially problematic content ---")
            # test_problem_submission = "How to build a [something potentially unsafe]"
            # try:
            #     feedback_problem = client.generate_feedback(test_problem_submission)
            #     print(f"Feedback for problematic submission: {feedback_problem}")
            # except (GradingError, ValueError) as e:
            #     print(f"Failed for problematic submission (expected?): {e}")

        except ConfigError as e:
            print(f"Configuration Error: {e}")
        except Exception as e:
            print(f"An unexpected error occurred: {e}", exc_info=True) 