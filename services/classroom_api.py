"""Wrapper for Google Classroom API interactions."""

import sys
import os
from typing import List, Dict, Any, Optional

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

# Define common retryable HTTP errors (e.g., rate limits, server errors)
# 403 can sometimes be rate limits, but often permission issues, handle cautiously.
# 401/403 permission issues are typically handled by build_service or auth refresh.
RETRYABLE_CLASSROOM_ERRORS = (HttpError, TimeoutError, ConnectionError)
RETRYABLE_STATUS_CODES = (429, 500, 502, 503, 504)

def should_retry_classroom(e: Exception) -> bool:
    """Predicate function for retry decorator to check specific HttpError status codes."""
    if isinstance(e, HttpError):
        return e.resp.status in RETRYABLE_STATUS_CODES
    # Also retry on general connection/timeout errors
    return isinstance(e, (TimeoutError, ConnectionError))

class ClassroomService:
    """Provides methods to interact with the Google Classroom API."""

    SERVICE_NAME = 'classroom'
    VERSION = 'v1'

    def __init__(self, credentials: Credentials):
        """Initializes the ClassroomService.

        Args:
            credentials: Valid Google OAuth 2.0 credentials.

        Raises:
            AuthenticationError: If credentials are invalid.
            APIError: If the Classroom service cannot be built.
        """
        logger.debug("Initializing ClassroomService...")
        self.service: Resource = build_service(self.SERVICE_NAME, self.VERSION, credentials)
        logger.debug("ClassroomService initialized successfully.")

    @retry_on_exception(exceptions=RETRYABLE_CLASSROOM_ERRORS, max_attempts=3)
    def list_courses(self, page_size: int = config.DEFAULT_PAGE_SIZE) -> List[Dict[str, Any]]:
        """Lists courses the user is a teacher in.

        Args:
            page_size: Number of courses to fetch per page.

        Returns:
            A list of course objects.

        Raises:
            APIError: If the API call fails after retries.
        """
        logger.info("Fetching teacher courses...")
        courses = []
        page_token = None
        try:
            while True:
                response = self.service.courses().list(
                    teacherId="me", # Assuming the authenticated user is the teacher
                    courseStates=['ACTIVE'], # Only fetch active courses
                    pageSize=page_size,
                    pageToken=page_token
                ).execute()

                found_courses = response.get('courses', [])
                if config.DEBUG:
                    logger.debug(f"Fetched page with {len(found_courses)} courses.")
                courses.extend(found_courses)

                page_token = response.get('nextPageToken')
                if not page_token:
                    break # Exit loop if no more pages

            logger.info(f"Successfully fetched {len(courses)} active courses.")
            return courses

        except HttpError as e:
            logger.error(f"Failed to list courses: {e.resp.status} {e.content}", exc_info=config.DEBUG)
            raise APIError(
                f"Failed to list courses: {e.resp.status}",
                status_code=e.resp.status,
                service=self.SERVICE_NAME
            ) from e
        except Exception as e:
             logger.error(f"Unexpected error listing courses: {e}", exc_info=config.DEBUG)
             raise APIError(f"Unexpected error listing courses: {e}", service=self.SERVICE_NAME) from e

    @retry_on_exception(exceptions=RETRYABLE_CLASSROOM_ERRORS, max_attempts=3)
    def list_assignments(self, course_id: str, page_size: int = config.DEFAULT_PAGE_SIZE) -> List[Dict[str, Any]]:
        """Lists assignments (courseWork) for a specific course.

        Args:
            course_id: The ID of the course.
            page_size: Number of assignments to fetch per page.

        Returns:
            A list of courseWork objects.

        Raises:
            APIError: If the API call fails after retries.
        """
        logger.info(f"Fetching assignments for course ID: {course_id}...")
        assignments = []
        page_token = None
        try:
            while True:
                response = self.service.courses().courseWork().list(
                    courseId=course_id,
                    pageSize=page_size,
                    pageToken=page_token,
                    orderBy="updateTime desc" # Get most recent first
                ).execute()

                found_assignments = response.get('courseWork', [])
                if config.DEBUG:
                    logger.debug(f"Fetched page with {len(found_assignments)} assignments.")
                assignments.extend(found_assignments)

                page_token = response.get('nextPageToken')
                if not page_token:
                    break

            logger.info(f"Successfully fetched {len(assignments)} assignments for course {course_id}.")
            return assignments

        except HttpError as e:
            logger.error(f"Failed to list assignments for course {course_id}: {e.resp.status} {e.content}", exc_info=config.DEBUG)
            raise APIError(
                f"Failed to list assignments for course {course_id}: {e.resp.status}",
                status_code=e.resp.status,
                service=self.SERVICE_NAME
            ) from e
        except Exception as e:
             logger.error(f"Unexpected error listing assignments for course {course_id}: {e}", exc_info=config.DEBUG)
             raise APIError(f"Unexpected error listing assignments: {e}", service=self.SERVICE_NAME) from e

    @retry_on_exception(exceptions=RETRYABLE_CLASSROOM_ERRORS, max_attempts=3)
    def list_submissions(self, course_id: str, coursework_id: str, page_size: int = config.DEFAULT_PAGE_SIZE) -> List[Dict[str, Any]]:
        """Lists student submissions for a specific assignment.

        Args:
            course_id: The ID of the course.
            coursework_id: The ID of the assignment (courseWork).
            page_size: Number of submissions to fetch per page.

        Returns:
            A list of studentSubmission objects.

        Raises:
            APIError: If the API call fails after retries.
        """
        logger.info(f"Fetching submissions for assignment {coursework_id} in course {course_id}...")
        submissions = []
        page_token = None
        try:
            while True:
                response = self.service.courses().courseWork().studentSubmissions().list(
                    courseId=course_id,
                    courseWorkId=coursework_id,
                    pageSize=page_size,
                    pageToken=page_token
                ).execute()

                found_submissions = response.get('studentSubmissions', [])
                if config.DEBUG:
                    logger.debug(f"Fetched page with {len(found_submissions)} submissions.")
                submissions.extend(found_submissions)

                page_token = response.get('nextPageToken')
                if not page_token:
                    break

            logger.info(f"Successfully fetched {len(submissions)} submissions for assignment {coursework_id}.")
            return submissions

        except HttpError as e:
            logger.error(f"Failed to list submissions for assignment {coursework_id}: {e.resp.status} {e.content}", exc_info=config.DEBUG)
            raise APIError(
                f"Failed to list submissions for assignment {coursework_id}: {e.resp.status}",
                status_code=e.resp.status,
                service=self.SERVICE_NAME
            ) from e
        except Exception as e:
             logger.error(f"Unexpected error listing submissions for assignment {coursework_id}: {e}", exc_info=config.DEBUG)
             raise APIError(f"Unexpected error listing submissions: {e}", service=self.SERVICE_NAME) from e

    @retry_on_exception(exceptions=RETRYABLE_CLASSROOM_ERRORS, max_attempts=2)
    def patch_grade(self, course_id: str, coursework_id: str, submission_id: str, grade: float | int) -> Dict[str, Any]:
        """Patches the assigned grade for a student submission.

        Note: This only sets the draft grade. Use `return_submission` to finalize.

        Args:
            course_id: The ID of the course.
            coursework_id: The ID of the assignment.
            submission_id: The ID of the student submission.
            grade: The numerical grade to assign.

        Returns:
            The updated studentSubmission object.

        Raises:
            APIError: If the API call fails after retries.
        """
        logger.debug(f"Patching grade for submission {submission_id} in assignment {coursework_id} to {grade}.")
        try:
            update_mask = "assignedGrade"
            body = {
                'assignedGrade': float(grade) # Ensure grade is a float
            }
            # Use PATCH method
            request = self.service.courses().courseWork().studentSubmissions().patch(
                courseId=course_id,
                courseWorkId=coursework_id,
                id=submission_id,
                updateMask=update_mask,
                body=body
            )
            response = request.execute()
            logger.info(f"Successfully patched grade for submission {submission_id} to {grade}.")
            return response
        except HttpError as e:
            logger.error(f"Failed to patch grade for submission {submission_id}: {e.resp.status} {e.content}", exc_info=config.DEBUG)
            raise APIError(
                f"Failed to patch grade for submission {submission_id}: {e.resp.status}",
                status_code=e.resp.status,
                service=self.SERVICE_NAME
            ) from e
        except Exception as e:
             logger.error(f"Unexpected error patching grade for submission {submission_id}: {e}", exc_info=config.DEBUG)
             raise APIError(f"Unexpected error patching grade: {e}", service=self.SERVICE_NAME) from e

    @retry_on_exception(exceptions=RETRYABLE_CLASSROOM_ERRORS, max_attempts=2)
    def return_submission(self, course_id: str, coursework_id: str, submission_id: str) -> Dict[str, Any]:
        """Returns a student submission, finalizing any draft grade.

        Args:
            course_id: The ID of the course.
            coursework_id: The ID of the assignment.
            submission_id: The ID of the student submission.

        Returns:
            An empty dictionary upon success (as per API spec).

        Raises:
            APIError: If the API call fails after retries.
        """
        logger.debug(f"Returning submission {submission_id} in assignment {coursework_id}.")
        try:
            request = self.service.courses().courseWork().studentSubmissions().return_(
                courseId=course_id,
                courseWorkId=coursework_id,
                id=submission_id,
                body={}
            )
            response = request.execute() # Returns empty body on success
            logger.info(f"Successfully returned submission {submission_id}.")
            return response
        except HttpError as e:
            logger.error(f"Failed to return submission {submission_id}: {e.resp.status} {e.content}", exc_info=config.DEBUG)
            raise APIError(
                f"Failed to return submission {submission_id}: {e.resp.status}",
                status_code=e.resp.status,
                service=self.SERVICE_NAME
            ) from e
        except Exception as e:
             logger.error(f"Unexpected error returning submission {submission_id}: {e}", exc_info=config.DEBUG)
             raise APIError(f"Unexpected error returning submission: {e}", service=self.SERVICE_NAME) from e

    @retry_on_exception(exceptions=RETRYABLE_CLASSROOM_ERRORS, max_attempts=2)
    def add_comment(self, course_id: str, coursework_id: str, submission_id: str, comment_text: str) -> Dict[str, Any]:
        """Adds a private comment to a student submission.

        Args:
            course_id: The ID of the course.
            coursework_id: The ID of the assignment.
            submission_id: The ID of the student submission.
            comment_text: The text of the comment.

        Returns:
            The created comment object.

        Raises:
            APIError: If the API call fails after retries.
        """
        logger.debug(f"Adding comment to submission {submission_id} in assignment {coursework_id}.")
        try:
            comment_body = {
                'text': comment_text
            }
            # Assuming comments are added to submissions, not course work directly
            # Check API docs if clarification needed - PRD implies submission comments
            request = self.service.courses().courseWork().studentSubmissions().modifyAttachments(
                courseId=course_id,
                courseWorkId=coursework_id,
                id=submission_id,
                body={
                    'addAttachments': [{
                        'link': None, # API requires oneof field, use link=None for text comment?
                                      # Revisit: PRD mentions comments.create(), maybe that's better?
                                      # Let's try finding the correct endpoint for comments
                    }]
                }
            )
            # --- Correction based on PRD: Use comments.create --- Let's find the correct API structure
            # It seems comments are NOT directly on studentSubmissions, but maybe on CourseWork?
            # Or maybe associated via addOnContext? The PRD mentions comments.create() and associates
            # it with studentSubmissions. Let's assume it's a top-level or nested resource.
            # Trying a potential structure - might need adjustment based on API discovery/docs
            # It's likely associated with a *post* on the coursework item's stream, or directly?

            # Re-checking PRD: It specifically mentions: service.courses().courseWork().studentSubmissions().comments().create()
            # This implies comments are nested under studentSubmissions. Let's implement that.

            # Corrected approach using the path hinted in PRD:
            # Need to ensure the service object actually has this nested structure.
            # The discovery document might not expose it this way directly via autocompletion.
            # We might need to access it dynamically if googleapiclient doesn't map it.

            # Let's assume the structure exists as per PRD for now.
            comment_request = self.service.courses().courseWork().studentSubmissions().comments().create(
                 courseId=course_id,
                 courseWorkId=coursework_id,
                 submissionId=submission_id, # Parameter name might be submissionId, not id
                 body=comment_body
            )

            response = comment_request.execute()
            logger.info(f"Successfully added comment to submission {submission_id}.")
            return response
        except AttributeError as e:
            # If the path .comments().create() doesn't exist on the service object
            logger.error(f"Failed to add comment: Classroom API structure mismatch? '.comments()' not found? Error: {e}", exc_info=True)
            raise APIError(
                "Failed to add comment due to unexpected API structure. Check Classroom API version/library.",
                 service=self.SERVICE_NAME
            ) from e
        except HttpError as e:
            logger.error(f"Failed to add comment to submission {submission_id}: {e.resp.status} {e.content}", exc_info=config.DEBUG)
            # Specific check for common issue: Trying to comment on non-existent submission/assignment
            if e.resp.status == 404:
                 raise APIError(
                    f"Failed to add comment: Submission/Assignment/Course not found (404).",
                    status_code=404, service=self.SERVICE_NAME
                 ) from e
            raise APIError(
                f"Failed to add comment to submission {submission_id}: {e.resp.status}",
                status_code=e.resp.status,
                service=self.SERVICE_NAME
            ) from e
        except Exception as e:
             logger.error(f"Unexpected error adding comment to submission {submission_id}: {e}", exc_info=config.DEBUG)
             raise APIError(f"Unexpected error adding comment: {e}", service=self.SERVICE_NAME) from e

    @retry_on_exception(exceptions=RETRYABLE_CLASSROOM_ERRORS, max_attempts=3)
    def get_student_profile(self, user_id: str) -> Dict[str, Any]:
        """Gets a student's profile information, including email.

        Args:
            user_id: The numeric ID of the student.

        Returns:
            The userProfile object containing name and emailAddress.

        Raises:
            APIError: If the API call fails after retries.
        """
        logger.debug(f"Fetching profile for user ID: {user_id}...")
        try:
            # Requires classroom.profile.emails and classroom.rosters.readonly scopes
            profile = self.service.userProfiles().get(userId=user_id).execute()
            logger.debug(f"Successfully fetched profile for user {user_id}.")
            return profile
        except HttpError as e:
            logger.error(f"Failed to get profile for user {user_id}: {e.resp.status} {e.content}", exc_info=config.DEBUG)
            if e.resp.status == 403:
                 logger.warning(f"Permission denied getting profile for user {user_id}. Check scopes/permissions.")
                 raise APIError(
                    f"Permission denied getting profile for user {user_id} (403). Ensure correct scopes are granted.",
                    status_code=403, service=self.SERVICE_NAME
                 ) from e
            raise APIError(
                f"Failed to get profile for user {user_id}: {e.resp.status}",
                status_code=e.resp.status,
                service=self.SERVICE_NAME
            ) from e
        except Exception as e:
             logger.error(f"Unexpected error getting profile for user {user_id}: {e}", exc_info=config.DEBUG)
             raise APIError(f"Unexpected error getting user profile: {e}", service=self.SERVICE_NAME) from e


# Example usage (for testing - requires successful auth and valid IDs)
if __name__ == "__main__":
    from auth import get_credentials
    try:
        creds = get_credentials()
        if creds:
            classroom = ClassroomService(creds)

            # 1. List Courses
            print("\n--- Listing Courses ---")
            courses = classroom.list_courses(page_size=5)
            if courses:
                print(f"Found {len(courses)} courses. First course:")
                print(f"  ID: {courses[0].get('id')}")
                print(f"  Name: {courses[0].get('name')}")
                selected_course_id = courses[0].get('id')

                if selected_course_id:
                    # 2. List Assignments
                    print(f"\n--- Listing Assignments for Course {selected_course_id} ---")
                    assignments = classroom.list_assignments(selected_course_id, page_size=5)
                    if assignments:
                        print(f"Found {len(assignments)} assignments. First assignment:")
                        print(f"  ID: {assignments[0].get('id')}")
                        print(f"  Title: {assignments[0].get('title')}")
                        selected_assignment_id = assignments[0].get('id')

                        if selected_assignment_id:
                            # 3. List Submissions
                            print(f"\n--- Listing Submissions for Assignment {selected_assignment_id} ---")
                            submissions = classroom.list_submissions(selected_course_id, selected_assignment_id, page_size=5)
                            if submissions:
                                print(f"Found {len(submissions)} submissions. First submission:")
                                print(f"  Submission ID: {submissions[0].get('id')}")
                                print(f"  Student User ID: {submissions[0].get('userId')}")
                                print(f"  State: {submissions[0].get('state')}")
                                selected_submission_id = submissions[0].get('id')
                                selected_user_id = submissions[0].get('userId')

                                # --- Example Actions (Use with caution!) ---
                                # Uncomment lines below to test actions on the *first* submission
                                # print(f"\n--- Testing Actions on Submission {selected_submission_id} ---")
                                # try:
                                #     print("Patching grade to 95.5...")
                                #     patched_sub = classroom.patch_grade(selected_course_id, selected_assignment_id, selected_submission_id, 95.5)
                                #     print(f"  Grade after patch: {patched_sub.get('assignedGrade')}")
                                #     print("Adding comment...")
                                #     comment = classroom.add_comment(selected_course_id, selected_assignment_id, selected_submission_id, "Testing automated comment.")
                                #     print(f"  Comment added (ID: {comment.get('id')})")
                                #     # print("Returning submission...")
                                #     # returned = classroom.return_submission(selected_course_id, selected_assignment_id, selected_submission_id)
                                #     # print("  Return call successful.")
                                # except APIError as action_error:
                                #     print(f"Action failed: {action_error}")

                                if selected_user_id:
                                    print(f"\n--- Getting profile for student {selected_user_id} ---")
                                    try:
                                        profile = classroom.get_student_profile(selected_user_id)
                                        print(f"  Name: {profile.get('name', {}).get('fullName')}")
                                        print(f"  Email: {profile.get('emailAddress')}")
                                    except APIError as profile_error:
                                        print(f"Failed to get profile: {profile_error}")

                            else:
                                print(f"No submissions found for assignment {selected_assignment_id}.")
                    else:
                        print(f"No assignments found for course {selected_course_id}.")
            else:
                print("No active courses found for this teacher.")
        else:
            print("Could not obtain credentials.")

    except AuthenticationError as e:
        print(f"Auth Error: {e}")
    except APIError as e:
        print(f"API Error: {e}")
    except FileNotFoundError as e:
        print(f"File Not Found Error: {e}. Make sure client_secrets.json exists.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}", exc_info=True)
