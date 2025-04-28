"""Custom exception classes for the application."""

class BaseGraderException(Exception):
    """Base exception for all application-specific errors."""
    pass

class ConfigError(BaseGraderException):
    """Error related to configuration loading or values."""
    pass

class AuthenticationError(BaseGraderException):
    """Error during the OAuth 2.0 authentication process."""
    pass

class APIError(BaseGraderException):
    """Error interacting with an external API (Google APIs, Gemini)."""
    def __init__(self, message: str, status_code: int | None = None, service: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.service = service

    def __str__(self) -> str:
        base = super().__str__()
        details = []
        if self.service:
            details.append(f"Service: {self.service}")
        if self.status_code:
            details.append(f"Status Code: {self.status_code}")
        if details:
            return f"{base} ({', '.join(details)})"
        return base

class ContentExtractionError(BaseGraderException):
    """Error extracting content from a student submission (Drive, Docs, Forms)."""
    pass

class GradingError(BaseGraderException):
    """Error during the grading logic or feedback generation."""
    pass

class UserCancelledError(BaseGraderException):
    """Error raised when the user cancels an operation."""
    pass

# Example usage (for testing)
if __name__ == "__main__":
    try:
        raise APIError("Failed to list courses", status_code=403, service="Classroom")
    except APIError as e:
        print(f"Caught API Error: {e}")
        print(f"Status Code: {e.status_code}")
        print(f"Service: {e.service}")

    try:
        raise AuthenticationError("Token expired and refresh failed.")
    except AuthenticationError as e:
        print(f"Caught Auth Error: {e}")

    try:
        raise ConfigError("Missing GEMINI_API_KEY")
    except ConfigError as e:
        print(f"Caught Config Error: {e}")
