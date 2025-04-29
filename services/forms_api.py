"""Wrapper for Google Forms API interactions."""

import sys
import os
from typing import Any, Dict, List, Optional, Tuple

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

# Define common retryable errors for Forms
RETRYABLE_FORMS_ERRORS = (HttpError, TimeoutError, ConnectionError)
RETRYABLE_STATUS_CODES = (403, 429, 500, 502, 503, 504) # Include 403 for potential rate limits

def should_retry_forms(e: Exception) -> bool:
    """Predicate function for retry decorator to check specific HttpError status codes for Forms."""
    if isinstance(e, HttpError):
        return e.resp.status in RETRYABLE_STATUS_CODES
    return isinstance(e, (TimeoutError, ConnectionError))

class FormsService:
    """
    Provides methods to interact with the Google Forms API.
    SOLID-compliant: All logic for fetching, parsing, and matching Google Form responses is encapsulated here.
    """

    """Provides methods to interact with the Google Forms API."""

    SERVICE_NAME = 'forms'
    VERSION = 'v1'

    def __init__(self, credentials: Credentials):
        """Initializes the FormsService.

        Args:
            credentials: Valid Google OAuth 2.0 credentials.

        Raises:
            AuthenticationError: If credentials are invalid.
            APIError: If the Forms service cannot be built.
        """
        logger.debug("Initializing FormsService...")
        # Note: Forms API is not available via discovery build by default in google-api-python-client
        # as of some versions. It might require specifying the discoveryServiceUrl.
        # Let's try standard build first, but be aware it might fail.
        # If it fails, we might need: discoveryServiceUrl=f'https://{self.SERVICE_NAME}.googleapis.com/$discovery/rest?version={self.VERSION}'
        try:
            self.service: Resource = build_service(self.SERVICE_NAME, self.VERSION, credentials)
        except APIError as e:
             # Specifically check if the error is due to Forms API not being discoverable
             if "GoogleApiClientUnacceptableResponseError" in str(e) or e.status_code == 404:
                 logger.warning("Standard Forms API build failed. Trying with explicit discovery URL...")
                 try:
                    discovery_url = f'https://{self.SERVICE_NAME}.googleapis.com/$discovery/rest?version={self.VERSION}'
                    self.service = build(self.SERVICE_NAME, self.VERSION, credentials=credentials, discoveryServiceUrl=discovery_url, static_discovery=False)
                 except Exception as build_err:
                     logger.critical(f"Failed to build Forms service even with explicit discovery URL: {build_err}", exc_info=True)
                     raise APIError(f"Could not build Forms API service: {build_err}", service=self.SERVICE_NAME) from build_err
             else:
                  raise # Re-raise original APIError if it wasn't a discovery issue

        logger.debug("FormsService initialized successfully.")

    @retry_on_exception(exceptions=RETRYABLE_FORMS_ERRORS, max_attempts=3)
    def get_form(self, form_id: str) -> Dict[str, Any]:
        """Retrieves the structure of a Google Form (questions, title, etc.).

        Args:
            form_id: The ID of the Google Form.

        Returns:
            The Form object as a dictionary.

        Raises:
            APIError: If the API call fails after retries (including 404).
        """
        logger.info(f"Fetching structure for Google Form ID: {form_id}...")
        try:
            form = self.service.forms().get(formId=form_id).execute()
            logger.debug(f"Successfully retrieved form structure for ID: {form_id}")
            return form
        except HttpError as e:
            logger.error(f"Failed to get form {form_id}: {e.resp.status} {e.content}", exc_info=config.DEBUG)
            if e.resp.status == 404:
                raise APIError(
                    f"Google Form not found (404) with ID: {form_id}",
                    status_code=404, service=self.SERVICE_NAME
                ) from e
            if e.resp.status == 403:
                 logger.warning(f"Permission denied (403) accessing form {form_id}. Check permissions.")
                 raise APIError(
                    f"Permission denied (403) accessing form {form_id}.",
                    status_code=403, service=self.SERVICE_NAME
                 ) from e
            raise APIError(
                f"Failed to get form {form_id}: {e.resp.status}",
                status_code=e.resp.status,
                service=self.SERVICE_NAME
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error getting form {form_id}: {e}", exc_info=config.DEBUG)
            raise APIError(f"Unexpected error getting form {form_id}: {e}", service=self.SERVICE_NAME) from e

    @retry_on_exception(exceptions=RETRYABLE_FORMS_ERRORS, max_attempts=3)
    def list_responses(self, form_id: str, page_size: int = config.DEFAULT_PAGE_SIZE) -> List[Dict[str, Any]]:
        """Retrieves all responses for a Google Form.

        Args:
            form_id: The ID of the Google Form.
            page_size: Maximum number of responses to retrieve per page.

        Returns:
            A list of form response objects.

        Raises:
            APIError: If the API call fails after retries (including 404, 403).
        """
        logger.info(f"Fetching responses for Google Form ID: {form_id}...")
        responses_list = []
        page_token = None
        try:
            while True:
                response = self.service.forms().responses().list(
                    formId=form_id,
                    pageSize=page_size, # Note: API documentation suggests this might not be supported yet
                    pageToken=page_token
                ).execute()

                found_responses = response.get('responses', [])
                if config.DEBUG:
                    logger.debug(f"Fetched page with {len(found_responses)} form responses.")
                responses_list.extend(found_responses)

                page_token = response.get('nextPageToken')
                if not page_token:
                    break

            logger.info(f"Successfully fetched {len(responses_list)} responses for form {form_id}.")
            return responses_list

        except HttpError as e:
            logger.error(f"Failed to list responses for form {form_id}: {e.resp.status} {e.content}", exc_info=config.DEBUG)
            if e.resp.status == 404:
                raise APIError(
                    f"Google Form not found (404) when listing responses: {form_id}",
                    status_code=404, service=self.SERVICE_NAME
                ) from e
            if e.resp.status == 403:
                logger.warning(f"Permission denied (403) listing responses for form {form_id}. Check permissions.")
                raise APIError(
                   f"Permission denied (403) listing responses for form {form_id}. Ensure you have edit access or sufficient permissions.",
                   status_code=403, service=self.SERVICE_NAME
                ) from e
            raise APIError(
                f"Failed to list responses for form {form_id}: {e.resp.status}",
                status_code=e.resp.status,
                service=self.SERVICE_NAME
            ) from e
        except Exception as e:
            logger.error(f"Unexpected error listing responses for form {form_id}: {e}", exc_info=config.DEBUG)
            raise APIError(f"Unexpected error listing form responses {form_id}: {e}", service=self.SERVICE_NAME) from e

    def parse_form_and_responses(self, form_id: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Fetches form structure and all responses, returning both.

        Args:
            form_id: The ID of the Google Form.

        Returns:
            A tuple containing:
                - The form structure dictionary.
                - A list of form response dictionaries.

        Raises:
            APIError: If fetching form or responses fails.
            ContentExtractionError: If parsing fails unexpectedly.
        """
        logger.info(f"Parsing form structure and responses for ID: {form_id}")
        try:
            form_structure = self.get_form(form_id)
            form_responses = self.list_responses(form_id)
            logger.info(f"Successfully parsed form and {len(form_responses)} responses for {form_id}.")
            return form_structure, form_responses
        except APIError as e:
            # Logged in underlying methods, just re-raise
            raise
        except Exception as e:
            logger.error(f"Unexpected error parsing form and responses for {form_id}: {e}", exc_info=True)
            raise ContentExtractionError(f"Failed to parse form/responses for {form_id}: {e}") from e

    def get_form_questions_and_correct_answers(self, form_structure: Dict[str, Any]) -> List[Dict[str, Any]]:
        logger.debug(f"[get_form_questions_and_correct_answers] Called with form_structure keys: {list(form_structure.keys()) if isinstance(form_structure, dict) else type(form_structure)}")
        questions = []
        """
        Extracts all questions and their correct answers (if present) from the form structure.
        Args:
            form_structure: The dictionary representing the form structure (from get_form).
        Returns:
            A list of dictionaries, each with keys: 'question_id', 'question_text', 'correct_answers' (if quiz), 'type'.
        """
        questions = []
        for idx, item in enumerate(form_structure.get('items', [])):
            logger.debug(f"[get_form_questions_and_correct_answers] Processing item {idx}: keys={list(item.keys())}")
            if 'questionItem' in item:
                q = item['questionItem']['question']
                logger.debug(f"[get_form_questions_and_correct_answers] Question object: {q}")
                question_id = q.get('questionId', item.get('itemId'))
                question_text = item.get('title', '')
                q_type = q.get('questionType', 'UNKNOWN')
                correct_answers = None
                if 'grading' in q:
                    correct_answers = q['grading'].get('correctAnswers')
                    logger.debug(f"[get_form_questions_and_correct_answers] Found grading: {q['grading']}")
                questions.append({
                    'question_id': question_id,
                    'question_text': question_text,
                    'type': q_type,
                    'correct_answers': correct_answers
                })
                logger.debug(f"[get_form_questions_and_correct_answers] Appended question: id={question_id}, text={question_text}, type={q_type}, correct_answers={correct_answers}")
        logger.debug(f"[get_form_questions_and_correct_answers] Returning {len(questions)} questions.")
        return questions

    def match_responses_to_emails(self, form_responses: List[Dict[str, Any]], student_emails: List[str]) -> Dict[str, Dict[str, Any]]:
        logger.debug(f"[match_responses_to_emails] Called with {len(form_responses)} responses and {len(student_emails)} student emails.")
        logger.debug(f"[match_responses_to_emails] Student emails: {student_emails}")
        email_to_response = {}
        """
        Matches each form response to a student email (if email collection is enabled).
        Args:
            form_responses: List of form response dicts.
            student_emails: List of student email addresses from Classroom.
        Returns:
            Dict mapping student_email -> form_response (if found).
        """
        email_to_response = {}
        for idx, response in enumerate(form_responses):
            respondent_email = response.get('respondentEmail')
            logger.debug(f"[match_responses_to_emails] Response {idx}: respondent_email={respondent_email}")
            if respondent_email and respondent_email in student_emails:
                logger.debug(f"[match_responses_to_emails] Matched respondent_email={respondent_email}")
                email_to_response[respondent_email] = response
            else:
                logger.debug(f"[match_responses_to_emails] No match for respondent_email={respondent_email}")
        logger.debug(f"[match_responses_to_emails] Returning {len(email_to_response)} matched responses.")
        return email_to_response

    def extract_student_form_data(self, form_structure: Dict[str, Any], form_response: Dict[str, Any]) -> Dict[str, Any]:
        logger.debug(f"[extract_student_form_data] Called with form_structure keys: {list(form_structure.keys()) if isinstance(form_structure, dict) else type(form_structure)}, form_response keys: {list(form_response.keys()) if isinstance(form_response, dict) else type(form_response)}")
        questions_meta = self.get_form_questions_and_correct_answers(form_structure)
        logger.debug(f"[extract_student_form_data] Extracted {len(questions_meta)} questions from form_structure.")
        answers = form_response.get('answers', {})
        logger.debug(f"[extract_student_form_data] Answers keys: {list(answers.keys()) if isinstance(answers, dict) else type(answers)}")
        result = {
            'respondent_email': form_response.get('respondentEmail'),
            'response_id': form_response.get('responseId'),
            'questions': [],
            'score': form_response.get('totalScore'),
        }
        """
        Extracts structured Q&A data for a single student response.
        Args:
            form_structure: The dictionary representing the form structure (from get_form).
            form_response: The dictionary representing a single student's response.
        Returns:
            Dict with keys: 'questions' (list of dicts with question_id, question_text, student_answer, correct_answer, is_correct), 'score', 'respondent_email'.
        """
        questions_meta = self.get_form_questions_and_correct_answers(form_structure)
        answers = form_response.get('answers', {})
        result = {
            'respondent_email': form_response.get('respondentEmail'),
            'response_id': form_response.get('responseId'),
            'questions': [],
            'score': form_response.get('totalScore'),
        }
        for idx, q in enumerate(questions_meta):
            qid = q['question_id']
            logger.debug(f"[extract_student_form_data] Processing question {idx}: id={qid}, text={q['question_text']}")
            student_answer = None
            if qid in answers:
                text_answers = answers[qid].get('textAnswers', {}).get('answers', [])
                logger.debug(f"[extract_student_form_data] Found text_answers for qid={qid}: {text_answers}")
                student_answer = [a.get('value') for a in text_answers if 'value' in a]
            else:
                logger.debug(f"[extract_student_form_data] No answer for qid={qid}")
            correct = None
            if q['correct_answers']:
                correct = q['correct_answers'].get('answers')
                logger.debug(f"[extract_student_form_data] Correct answers for qid={qid}: {correct}")
            is_correct = (student_answer == correct) if (student_answer and correct) else None
            logger.debug(f"[extract_student_form_data] Result for qid={qid}: student_answer={student_answer}, correct={correct}, is_correct={is_correct}")
            result['questions'].append({
                'question_id': qid,
                'question_text': q['question_text'],
                'student_answer': student_answer,
                'correct_answer': correct,
                'is_correct': is_correct
            })
        logger.debug(f"[extract_student_form_data] Returning result: {result}")
        return result

    def format_responses_for_llm(self, form_structure: Dict[str, Any], form_responses: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        """Formats form questions and individual student responses into a text format suitable for an LLM.

        Args:
            form_structure: The dictionary representing the form structure (from get_form).
            form_responses: A list of dictionaries, each representing a single student's response (from list_responses).

        Returns:
            A list of dictionaries, where each dictionary contains:
                'respondent_email': The email of the respondent (if available).
                'response_id': The ID of the response.
                'formatted_text': A string combining questions and answers for that respondent.
        """
        logger.debug(f"Formatting {len(form_responses)} form responses for LLM...")
        formatted_outputs = []
        questions = {item['itemId']: item for item in form_structure.get('items', []) if 'questionItem' in item}

        for response in form_responses:
            respondent_email = response.get('respondentEmail', 'anonymous')
            response_id = response.get('responseId', 'unknown')
            output_text = f"Form Title: {form_structure.get('info', {}).get('title', 'Untitled Form')}\n"
            output_text += f"Respondent: {respondent_email}\nResponse ID: {response_id}\n---\n\n"

            answers = response.get('answers', {})
            for item_id, question_data in questions.items():
                question_info = question_data.get('questionItem', {}).get('question', {})
                question_title = question_data.get('title', f"Question ID {item_id}")
                question_id = question_info.get('questionId', item_id)

                output_text += f"Q: {question_title}\n"

                # List options for choice questions
                cq = question_info.get('choiceQuestion', {})
                opts = cq.get('options', [])
                if opts:
                    values = [opt.get('value', '') for opt in opts]
                    output_text += f"Options: {', '.join(values)}\n"
                # List correct answer(s) if quiz grading exists
                grading = question_info.get('grading', {})
                ca = grading.get('correctAnswers', {}).get('answers', [])
                if ca:
                    correct_vals = [ans.get('value', '') for ans in ca]
                    output_text += f"Correct Answer: {', '.join(correct_vals)}\n"

                answer_data = answers.get(question_id)
                if answer_data:
                    text_answers = answer_data.get('textAnswers', {}).get('answers', [])
                    answer_text = ", ".join([ans.get('value', '') for ans in text_answers])
                    output_text += f"A: {answer_text}\n\n"
                else:
                    output_text += "A: (No answer provided)\n\n"

            formatted_outputs.append({
                'respondent_email': respondent_email,
                'response_id': response_id,
                'formatted_text': output_text.strip()
            })

        logger.debug(f"Finished formatting {len(formatted_outputs)} responses.")
        return formatted_outputs


# Example usage (for testing - requires successful auth and a valid Form ID)
if __name__ == "__main__":
    from auth import get_credentials
    # --- !!! REPLACE WITH A VALID FORM ID YOU HAVE ACCESS TO !!! ---
    # Ensure the authenticated user has at least read access to the form and responses
    TEST_FORM_ID: Optional[str] = None # e.g., "1aBcDeFgHiJkLmNoPqRsTuVwXyZ12345AbCdEfG_form"
    # ---------------------------------------------------------------

    if not TEST_FORM_ID:
        print("Please set TEST_FORM_ID in the script to run the example.")
    else:
        try:
            creds = get_credentials()
            if creds:
                forms_service = FormsService(creds)

                # 1. Get Form Structure
                print(f"\n--- Getting Structure for Form ID: {TEST_FORM_ID} ---")
                try:
                    form = forms_service.get_form(TEST_FORM_ID)
                    print(f"  Form Title: {form.get('info', {}).get('title')}")
                    print(f"  Item Count: {len(form.get('items', []))}")
                except APIError as form_error:
                    print(f"Failed to get form structure: {form_error}")
                    sys.exit(1)

                # 2. List Responses
                print(f"\n--- Listing Responses for Form ID: {TEST_FORM_ID} ---")
                try:
                    responses = forms_service.list_responses(TEST_FORM_ID)
                    print(f"  Found {len(responses)} responses.")
                    if responses:
                        print(f"  First response ID: {responses[0].get('responseId')}")
                        print(f"  Respondent Email (if available): {responses[0].get('respondentEmail')}")

                        # 3. Format for LLM
                        print(f"\n--- Formatting Responses for LLM ---")
                        formatted = forms_service.format_responses_for_llm(form, responses)
                        if formatted:
                            print(f"  Formatted {len(formatted)} responses. Preview of first response:")
                            print("  " + "-"*40)
                            print(formatted[0]['formatted_text'][:1000]) # Print first 1000 chars
                            print("  " + "-"*40)
                        else:
                            print("  Formatting produced no output.")

                except APIError as resp_error:
                    print(f"Failed to list responses: {resp_error}")
                except ContentExtractionError as fmt_error:
                     print(f"Failed to format responses: {fmt_error}")

            else:
                print("Could not obtain credentials.")

        except AuthenticationError as e:
            print(f"Auth Error: {e}")
        except FileNotFoundError as e:
            print(f"File Not Found Error: {e}. Make sure client_secrets.json exists.")
        except Exception as e:
            print(f"An unexpected error occurred: {e}", exc_info=True)
