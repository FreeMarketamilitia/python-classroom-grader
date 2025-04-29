"""Core logic for fetching submissions, extracting content, and orchestrating grading."""

import sys
import os
import textwrap
import json
import re
from typing import List, Dict, Any, Optional, Tuple

# Assuming common setup is done correctly
try:
    import config
    from utils.logger import get_logger
    from utils.error_handler import APIError, ContentExtractionError, GradingError
    # Import Service Wrappers
    from services.classroom_api import ClassroomService
    from services.drive_api import DriveService
    from services.docs_api import DocsService
    from services.forms_api import FormsService
    from services.gmail_api import GmailService
    from services.gemini_ai import GeminiClient
except ImportError:
    # Adjust path if run directly or structure differs
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    import config
    from utils.logger import get_logger
    from utils.error_handler import APIError, ContentExtractionError, GradingError
    from services.classroom_api import ClassroomService
    from services.drive_api import DriveService
    from services.docs_api import DocsService
    from services.forms_api import FormsService
    from services.gmail_api import GmailService
    from services.gemini_ai import GeminiClient

logger = get_logger()

# Define a type alias for processed submission data
ProcessedSubmission = Dict[str, Any] # keys: submission_id, user_id, student_email, content, feedback, error, state, current_grade

class Grader:
    """Orchestrates the assignment grading process."""

    def __init__(
        self,
        classroom_service: ClassroomService,
        drive_service: DriveService,
        docs_service: DocsService,
        forms_service: FormsService,
        gmail_service: GmailService,
        gemini_client: Optional[GeminiClient] # Optional for now, if API key is missing
    ):
        """Initializes the Grader with necessary API service clients."""
        self.classroom_service = classroom_service
        self.drive_service = drive_service
        self.docs_service = docs_service
        self.forms_service = forms_service
        self.gmail_service = gmail_service
        self.gemini_client = gemini_client
        logger.info("Grader initialized with services: Classroom, Drive, Docs, Forms, Gmail, Gemini=%s", bool(gemini_client))

    def _extract_submission_content(self, submission: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """
        Extracts relevant text content from a student submission attachment, supporting Google Drive files, Docs, Forms, and links.
        Uses a unified handler registry for extensibility and robust error aggregation.
        """
        submission_id = submission.get('id')
        user_id = submission.get('userId')
        logger.debug(f"Extracting content for submission {submission_id} (user {user_id})")
        logger.debug(f"RAW submission object: {json.dumps(submission, indent=2)}")

        # Gather all attachments: student + assignment-level
        attachments = list(submission.get('assignmentSubmission', {}).get('attachments', []))
        logger.debug(f"Student-level attachments: {submission.get('assignmentSubmission', {}).get('attachments', [])}")
        assignment_attachments = []
        if not attachments:
            # Try to get assignment-level attachments from submission or context
            if 'courseWork' in submission:
                assignment_attachments = submission['courseWork'].get('materials', [])
            elif 'assignment_attachments' in submission:
                assignment_attachments = submission['assignment_attachments']
            elif hasattr(self, 'current_assignment') and self.current_assignment:
                assignment_attachments = self.current_assignment.get('materials', [])
        logger.debug(f"Assignment-level attachments: {assignment_attachments}")
        attachments += assignment_attachments

        if not attachments:
            logger.warning(f"Submission {submission_id} for user {user_id} has no attachments (student or assignment-level).")
            return None, "No attachments found."

        # Handler registry: list of (predicate, handler) tuples
        def is_drive_file(att):
            return 'driveFile' in att
        def is_form(att):
            return 'form' in att
        def is_link(att):
            return 'link' in att
        # Add new handler predicates here as needed

        def handle_drive_file(att):
            drive_file = att['driveFile']
            file_id = drive_file.get('id')
            file_title = drive_file.get('title', 'Untitled Drive File')
            if not file_id:
                return None, "Drive file missing file ID."
            logger.info(f"Processing Drive file attachment: '{file_title}' (ID: {file_id}) for submission {submission_id}.")
            try:
                mime_type, file_bytes = self.drive_service.download_file_content(file_id)
                if not file_bytes:
                    return None, f"File '{file_title}' is empty."
                if mime_type and mime_type.startswith("text/"):
                    try:
                        content = file_bytes.decode('utf-8')
                    except UnicodeDecodeError:
                        try:
                            content = file_bytes.decode('latin-1')
                        except UnicodeDecodeError:
                            return None, f"Could not decode file '{file_title}' as text."
                else:
                    return None, f"File '{file_title}' is not a text-based document (MIME: {mime_type})."
                return content, None
            except (APIError, ContentExtractionError) as e:
                return None, f"Error accessing Drive file '{file_title}': {e}"
            except Exception as e:
                return None, f"Unexpected error with Drive file '{file_title}': {e}"

        def handle_form(att):
            form_response_info = att['form']
            form_url = form_response_info.get('formUrl')
            response_url = form_response_info.get('responseUrl')
            form_title = form_response_info.get('title', 'Untitled Form')
            if not form_url:
                return None, "Form attachment has no URL."
            # Parse form ID from URL
            match = re.search(r'/d/([^/]+)', form_url)
            if not match:
                return None, f"Could not parse Form ID from URL: {form_url}"
            form_id = match.group(1)
            logger.info(f"Processing Form attachment: '{form_title}' (ID: {form_id}) for submission {submission_id}.")
            try:
                form_structure, all_responses = self.forms_service.parse_form_and_responses(form_id)
                student_email = submission.get('student_email')
                matching_response = None
                if student_email:
                    email_to_response = self.forms_service.match_responses_to_emails(all_responses, [student_email])
                    matching_response = email_to_response.get(student_email)
                if not matching_response and response_url and '/viewresponse?id=' in response_url:
                    try:
                        target_response_id = response_url.split('id=')[1].split('&')[0]
                        logger.debug(f"Extracted target response ID from URL: {target_response_id}")
                        matching_response = next((r for r in all_responses if r.get('responseId') == target_response_id), None)
                    except Exception:
                        logger.warning(f"Could not parse or match response ID from responseUrl: {response_url}")
                if not matching_response:
                    logger.warning(f"No matching response found for student {student_email} in form {form_id}. Using all responses for debug.")
                    matching_responses = all_responses
                else:
                    matching_responses = [matching_response]
                if not matching_responses:
                    return None, f"No responses found or matched for form '{form_title}'."
                extracted_form_data = [
                    self.forms_service.extract_student_form_data(form_structure, resp)
                    for resp in matching_responses
                ]
                submission['form_response_data'] = extracted_form_data
                formatted_responses = self.forms_service.format_responses_for_llm(form_structure, matching_responses)
                if formatted_responses:
                    if len(formatted_responses) > 1:
                        logger.warning(f"Multiple responses formatted for form {form_id} (submission {submission_id}). Combining text.")
                        content = "\n\n---\n\n".join([fr['formatted_text'] for fr in formatted_responses])
                    else:
                        content = formatted_responses[0]['formatted_text']
                    return content, None
                else:
                    return None, f"Failed to format responses for form '{form_title}'."
            except (APIError, ContentExtractionError) as e:
                return None, f"Error accessing form '{form_title}': {e}"
            except Exception as e:
                return None, f"Unexpected error with form '{form_title}': {e}"

        def handle_link(att):
            link = att['link']
            url = link.get('url')
            title = link.get('title', 'Untitled Link')
            logger.info(f"Processing link attachment: '{title}' ({url}) for submission {submission_id}.")
            doc_id = None
            # Try Google Docs/Sheets/Slides
            if url and ('docs.google.com/document' in url or 'docs.google.com' in url):
                try:
                    doc_id = url.split('/d/')[1].split('/')[0]
                except Exception:
                    return None, f"Could not extract doc ID from link: {url}"
            if doc_id:
                try:
                    logger.info(f"Attempting to fetch content from Google Doc link (ID: {doc_id})")
                    doc_content = self.docs_service.get_document_text(doc_id)
                    if doc_content:
                        return doc_content, None
                    else:
                        return None, f"Google Doc link '{title}' is empty or could not be read."
                except (APIError, ContentExtractionError) as e:
                    return None, f"Error accessing Google Doc link '{title}': {e}"
                except Exception as e:
                    return None, f"Unexpected error processing Google Doc link '{title}': {e}"
            return None, f"Link attachment '{title}' not supported or not a Google Doc."

        handler_registry = [
            (is_drive_file, handle_drive_file),
            (is_form, handle_form),
            (is_link, handle_link),
            # Add new (predicate, handler) pairs here for extensibility
        ]

        extraction_results = []
        error_details = []
        for att in attachments:
            handled = False
            for predicate, handler in handler_registry:
                if predicate(att):
                    content, error = handler(att)
                    handled = True
                    if content:
                        extraction_results.append(content)
                    else:
                        error_details.append(f"Attachment {self._describe_attachment(att)}: {error}")
                    break
            if not handled:
                error_details.append(f"Attachment {self._describe_attachment(att)}: No handler found.")
        if extraction_results:
            # Join multiple valid extractions with separator
            return "\n\n---\n\n".join(extraction_results), None
        else:
            logger.warning(f"No supported attachment type found or content extracted for submission {submission_id}. Errors: {error_details}")
            return None, "No supported attachment type found or content extracted. Details:\n" + "\n".join(error_details)

    def _describe_attachment(self, att: Dict[str, Any]) -> str:
        if 'driveFile' in att:
            f = att['driveFile']
            return f"DriveFile[{f.get('title','untitled')}:{f.get('id','no-id')}]"
        if 'form' in att:
            f = att['form']
            return f"Form[{f.get('title','untitled')}]"
        if 'link' in att:
            f = att['link']
            return f"Link[{f.get('title','untitled')}]"
        return 'UnknownAttachmentType'


    def _get_student_email(self, user_id: str) -> Optional[str]:
        """Helper to get student email from their profile ID."""
        try:
            profile = self.classroom_service.get_student_profile(user_id)
            email = profile.get('emailAddress')
            if not email:
                logger.warning(f"Could not find email address in profile for user ID {user_id}.")
                return None
            logger.debug(f"Found email {email} for user ID {user_id}.")
            return email
        except APIError as e:
            logger.error(f"Failed to get profile/email for user ID {user_id}: {e}")
            return None

    def process_assignment(self, course_id: str, coursework_id: str) -> List[ProcessedSubmission]:
        """Processes all submissions for a given assignment.

        Fetches submissions, extracts content, generates AI feedback (if enabled),
        and gathers student emails.

        Args:
            course_id: The ID of the course.
            coursework_id: The ID of the assignment.

        Returns:
            A list of dictionaries, each representing a processed submission
            with extracted content, feedback, errors, and student info.
        """
        logger.info(f"Starting processing for assignment {coursework_id} in course {course_id}.")
        processed_results: List[ProcessedSubmission] = []

        # Fetch the assignment/coursework object to get its title
        try:
            coursework = None
            try:
                assignments = self.classroom_service.list_assignments(course_id)
                coursework = next((a for a in assignments if a.get('id') == coursework_id), None)
                if coursework:
                    logger.info(f"Fetched assignment title: {coursework.get('title')}")
                    self.current_assignment = coursework
                    logger.debug(f"Set current_assignment: {json.dumps(coursework, indent=2)}")
                else:
                    logger.warning(f"Could not find assignment with id {coursework_id} in course {course_id}.")
            except Exception as e:
                logger.warning(f"Could not fetch assignment title for coursework_id {coursework_id}: {e}")

            submissions = self.classroom_service.list_submissions(course_id, coursework_id)
            logger.debug(f"RAW submissions payload: {json.dumps(submissions, indent=2)}")
        except APIError as e:
            logger.critical(f"Failed to list submissions for assignment {coursework_id}: {e}. Aborting processing.")
            return []

        logger.info(f"Found {len(submissions)} submissions to process.")

        for i, sub in enumerate(submissions):
            logger.debug(f"Submission payload: {json.dumps(sub, indent=2)}")
            submission_id = sub.get('id')
            user_id = sub.get('userId')
            state = sub.get('state')
            assigned_grade = sub.get('assignedGrade')

            logger.info(f"Processing submission {i+1}/{len(submissions)} (ID: {submission_id}, User: {user_id}, State: {state})...")

            result: ProcessedSubmission = {
                'submission_id': submission_id,
                'user_id': user_id,
                'student_email': None,
                'content': None,
                'feedback': None,
                'error': None,
                'state': state,
                'current_grade': assigned_grade,
                'assignment_title': coursework.get('title') if coursework else None
            }

            result['student_email'] = self._get_student_email(user_id)
            if not result['student_email']:
                 logger.warning(f"Could not retrieve email for student {user_id}, proceeding without it.")

            if state not in ['TURNED_IN', 'CREATED']:
                 logger.info(f"Skipping submission {submission_id} due to state: {state}")
                 result['error'] = f"Submission not in processable state ({state})"
                 processed_results.append(result)
                 continue

            content, error = self._extract_submission_content(sub)
            if error:
                logger.error(f"Content extraction failed for submission {submission_id}: {error}")
                result['error'] = f"Content extraction failed: {error}"
                processed_results.append(result)
                continue
            elif not content:
                logger.warning(f"No content extracted for submission {submission_id}, but no explicit error reported.")
                result['error'] = "No content could be extracted (unknown reason)."
                processed_results.append(result)
                continue
            else:
                result['content'] = content
                logger.info(f"Successfully extracted content for submission {submission_id} ({len(content)} chars).")

            if self.gemini_client and result['content']:
                try:
                    feedback = self.gemini_client.generate_feedback(result['content'])
                    result['feedback'] = feedback
                    logger.info(f"Successfully generated AI feedback for submission {submission_id}.")
                    if config.DEBUG:
                        logger.debug(f"Feedback preview: {textwrap.shorten(feedback, width=100)}")
                except (GradingError, ValueError) as e:
                    logger.error(f"AI feedback generation failed for submission {submission_id}: {e}")
                    result['error'] = f"AI feedback generation failed: {e}"
                except Exception as e:
                    logger.error(f"Unexpected error during AI feedback generation for {submission_id}: {e}", exc_info=True)
                    result['error'] = f"Unexpected AI feedback error: {e}"
            elif not self.gemini_client:
                logger.warning("Gemini client not available, skipping feedback generation.")
                result['error'] = (result['error'] + "; AI feedback skipped (no client)").lstrip("; ") if result['error'] else "AI feedback skipped (no client)"

            processed_results.append(result)

        logger.info(f"Finished processing assignment {coursework_id}. Processed {len(processed_results)} submissions.")
        return processed_results

    def apply_grades_and_comments(self, course_id: str, coursework_id: str, processed_submissions: List[ProcessedSubmission], apply_grades: bool = False, post_comments: bool = True):
        """Applies grades (optional) and comments to submissions via Classroom API.

        Args:
            course_id: The ID of the course.
            coursework_id: The ID of the assignment.
            processed_submissions: List of processed submission data from `process_assignment`.
            apply_grades: If True, attempts to patch grades (requires grading logic).
                          **NOTE: Grading logic is NOT implemented in MVP.**
            post_comments: If True, posts the generated AI feedback as a private comment.
        """
        if not processed_submissions:
            logger.warning("No submissions provided to apply grades/comments.")
            return

        logger.info(f"Applying actions to {len(processed_submissions)} submissions for assignment {coursework_id}...")
        logger.info(f"Apply Grades: {apply_grades}, Post Comments: {post_comments}")

        for i, result in enumerate(processed_submissions):
            submission_id = result.get('submission_id')
            feedback = result.get('feedback')
            error = result.get('error')

            if not submission_id:
                logger.warning(f"Skipping result {i+1} due to missing submission ID.")
                continue

            should_skip_actions = False
            if error and ("extraction failed" in error or "AI feedback generation failed" in error or "AI feedback skipped" in error):
                logger.warning(f"Skipping actions for submission {submission_id} due to previous processing error: {error}")
                should_skip_actions = True

            if should_skip_actions:
                continue

            logger.debug(f"Processing actions for submission {submission_id}...")

            if apply_grades:
                # Try to get a grade from the processed result; default to 100 if not present
                grade = result.get('grade')
                if grade is None:
                    grade = result.get('current_grade')
                if grade is None:
                    grade = 100  # Default grade if none present
                logger.info(f"[GRADER] About to patch grade for submission {submission_id}: course_id={course_id}, coursework_id={coursework_id}, grade={grade}")
                logger.debug(f"[GRADER] Submission state before patch: {result}")
                try:
                    patch_response = self.classroom_service.patch_grade(course_id, coursework_id, submission_id, grade)
                    logger.info(f"[GRADER] Patch grade response for submission {submission_id}: {patch_response}")
                except APIError as e:
                    logger.error(f"[GRADER] Failed to patch grade for submission {submission_id}: {e}")
                except Exception as e:
                    logger.error(f"[GRADER] Unexpected exception during patch_grade for submission {submission_id}: {e}", exc_info=True)
                logger.debug(f"[GRADER] Submission state after patch: {result}")

            if post_comments and feedback:
                logger.info(f"Attempting to add comment to submission {submission_id}.")
                try:
                    comment_text = f"[AI Generated Feedback]:\n\n{feedback}"
                    self.classroom_service.add_comment(course_id, coursework_id, submission_id, comment_text)
                except APIError as e:
                    logger.error(f"Failed to add comment to submission {submission_id}: {e}")
            elif post_comments and not feedback:
                 logger.warning(f"Cannot post comment for submission {submission_id}: No feedback available.")

        logger.info("Finished applying grades/comments.")

    def email_feedback(self, processed_submissions: List[ProcessedSubmission]):
        """Emails the generated feedback to each student.

        Args:
            processed_submissions: List of processed submission data.
        """
        if not processed_submissions:
            logger.warning("No submissions provided to email feedback.")
            return

        logger.info(f"Preparing to email feedback for {len(processed_submissions)} submissions...")
        emails_sent = 0
        emails_failed = 0

        for i, result in enumerate(processed_submissions):
            student_email = result.get('student_email')
            feedback = result.get('feedback')
            submission_id = result.get('submission_id', 'Unknown Submission')
            error = result.get('error')

            if not student_email:
                logger.warning(f"Skipping email for submission {submission_id}: Student email not found.")
                emails_failed += 1
                continue
            if not feedback:
                logger.warning(f"Skipping email for submission {submission_id}: No feedback generated.")
                if not error or "feedback skipped" not in error:
                    emails_failed += 1
                continue
            if error and ("extraction failed" in error or "AI feedback generation failed" in error):
                 logger.warning(f"Skipping email for submission {submission_id} due to prior critical error: {error}")
                 emails_failed += 1
                 continue

            logger.info(f"Attempting to send feedback email to {student_email} for submission {submission_id}.")
            try:
                # --- Fetch and cache student name from Classroom API ---
                if not hasattr(self, '_student_name_cache'):
                    self._student_name_cache = {}
                user_id = result.get('user_id')
                student_name = None
                if user_id:
                    student_name = self._student_name_cache.get(user_id)
                    if not student_name:
                        try:
                            profile = self.classroom_service.get_student_profile(user_id)
                            # Google Classroom API returns: { ... 'name': {'fullName': ...}, ... }
                            student_name = (
                                profile.get('name', {}).get('fullName')
                                or profile.get('name', {}).get('givenName')
                                or profile.get('name', {}).get('displayName')
                                or "Student"
                            )
                            self._student_name_cache[user_id] = student_name
                        except Exception as e:
                            student_name = "Student"
                if not student_name:
                    student_name = result.get('student_name') or result.get('name') or "Student"
                # --- Get submission title as before ---
                # Try all possible keys for assignment/assignment title
                submission_title = (
                    result.get('assignment_title')
                    or result.get('submission_title')
                    or result.get('title')
                    or result.get('assignment')
                    or result.get('coursework_title')
                    or "Assignment"
                )
                # --- Subject and HTML body ---
                subject = f"{student_name}, your feedback for '{submission_title}'"
                # --- Sanitize feedback to remove placeholders, greetings, and assignment title ---
                import re
                clean_feedback = feedback
                # Remove '[StudentName]' or similar placeholders
                clean_feedback = re.sub(r'\[ ?Student(Name)? ?\]', '', clean_feedback, flags=re.IGNORECASE)
                # Remove lines starting with a greeting (Hi|Hello|Dear), possibly followed by a name/placeholder
                clean_feedback = re.sub(r'^(\s)*(hi|hello|dear)[^\n]*[\n\r]+', '', clean_feedback, flags=re.IGNORECASE|re.MULTILINE)
                # Remove lines mentioning the assignment title or generic assignment references
                assignment_terms = [re.escape(submission_title), r'assignment', r'homework', r'task', r'project']
                assignment_pattern = r'^(.*(' + '|'.join(assignment_terms) + r').*)[\n\r]+'
                clean_feedback = re.sub(assignment_pattern, '', clean_feedback, flags=re.IGNORECASE|re.MULTILINE)
                clean_feedback = clean_feedback.strip()
                html_body = f'''
                <!DOCTYPE html>
                <html lang="en">
                <head>
                  <meta charset="UTF-8">
                  <meta name="viewport" content="width=device-width, initial-scale=1.0">
                  <title>Assignment Feedback</title>
                  <style>
                    body {{
                      background: linear-gradient(135deg, #e0e7ff 0%, #f8fafc 100%);
                      margin: 0;
                      padding: 0;
                      font-family: 'Segoe UI', 'Roboto', Arial, sans-serif;
                      color: #232946;
                    }}
                    .container {{
                      max-width: 600px;
                      margin: 32px auto;
                      background: #fff;
                      border-radius: 18px;
                      box-shadow: 0 10px 32px 0 rgba(51,102,204,0.10), 0 1.5px 8px 0 rgba(51,102,204,0.07);
                      padding: 0 0 36px 0;
                      overflow: hidden;
                    }}
                    .header {{
                      background: linear-gradient(90deg, #3366cc 0%, #5f9fff 100%);
                      color: #fff;
                      padding: 28px 36px 18px 36px;
                      display: flex;
                      align-items: center;
                    }}
                    .header-icon {{
                      font-size: 2.3em;
                      margin-right: 18px;
                    }}
                    .header-title {{
                      font-size: 1.7em;
                      font-weight: 600;
                      letter-spacing: 1px;
                    }}
                    .greeting {{
                      margin: 32px 36px 0 36px;
                      font-size: 1.08em;
                      color: #232946;
                    }}
                    .desc {{
                      margin: 12px 36px 0 36px;
                      color: #4f5d75;
                      font-size: 1.08em;
                    }}
                    .feedback-section {{
                      margin: 28px 36px 0 36px;
                      background: linear-gradient(90deg, #f0f4fc 80%, #e6f0ff 100%);
                      border-left: 7px solid #3366cc;
                      border-radius: 6px;
                      box-shadow: 0 1px 6px 0 rgba(51,102,204,0.05);
                      padding: 24px 20px 18px 22px;
                      font-size: 1.13em;
                      color: #263159;
                      line-height: 1.7;
                    }}
                    .footer {{
                      margin: 38px 36px 0 36px;
                      font-size: 1em;
                      color: #7a7a7a;
                      border-top: 1px solid #e0e7ff;
                      padding-top: 18px;
                    }}
                    @media (max-width: 650px) {{
                      .container, .header, .greeting, .desc, .feedback-section, .footer {{
                        margin-left: 0 !important;
                        margin-right: 0 !important;
                        padding-left: 10px !important;
                        padding-right: 10px !important;
                      }}
                      .header {{
                        flex-direction: column;
                        align-items: flex-start;
                        padding: 22px 10px 12px 10px;
                      }}
                    }}
                  </style>
                </head>
                <body>
                  <div class="container">
                    <div class="header">
                      <div class="header-icon">📚</div>
                      <div class="header-title">Your Assignment Feedback</div>
                    </div>
                    <div class="greeting">Hello {student_name},</div>
                    <div class="desc">Here is your personalized feedback:</div>
                    <div class="feedback-section">{clean_feedback}</div>
                    <div class="footer">
                      <div>Best regards,<br><b>Your Teacher</b> <span style="color:#3366cc;">(via AI Assistant)</span></div>
                      <div style="margin-top: 10px; font-size:0.95em; color:#b4b4b4;">This message was generated by the Google Classroom AI Grading Assistant.<br>Keep learning and growing! 🚀</div>
                    </div>
                  </div>
                </body>
                </html>
                '''
                self.gmail_service.send_email(student_email, subject, html_body, is_html=True)
                emails_sent += 1
            except (APIError, ValueError) as e:
                logger.error(f"Failed to send feedback email to {student_email} for submission {submission_id}: {e}")
                emails_failed += 1
            except Exception as e:
                 logger.error(f"Unexpected error sending email to {student_email} for {submission_id}: {e}", exc_info=True)
                 emails_failed += 1

        logger.info(f"Finished emailing feedback. Sent: {emails_sent}, Failed/Skipped: {emails_failed}.")


# Example usage (for testing - requires successful auth and valid IDs)
if __name__ == "__main__":
    print("This script contains the Grader class logic.")
    print("Run main.py for a full execution test.") 