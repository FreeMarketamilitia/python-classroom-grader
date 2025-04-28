"""Retry decorator for handling transient API errors."""

import time
import random
from functools import wraps
from typing import Any, Callable, Tuple, Type, TypeVar

# Assuming logger and config are set up correctly
# Adjust imports based on final structure
from .logger import get_logger
import config

logger = get_logger()

# Define a generic type variable for the decorated function's return type
F = TypeVar('F', bound=Callable[..., Any])

def retry_on_exception(
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    max_attempts: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    jitter: float = 0.1
) -> Callable[[F], F]:
    """Decorator to retry a function call upon specific exceptions with exponential backoff.

    Args:
        exceptions: A tuple of exception types to catch and retry on.
        max_attempts: Maximum number of attempts (including the initial one).
        initial_delay: Delay before the first retry in seconds.
        backoff_factor: Multiplier for the delay in subsequent retries.
        jitter: Factor for adding random jitter to delay (delay * jitter * random.uniform(-1, 1)).

    Returns:
        A decorator function.
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempts = 0
            delay = initial_delay
            while attempts < max_attempts:
                attempts += 1
                try:
                    if config.DEBUG and attempts > 1:
                        logger.debug(f"Retrying {func.__name__} (Attempt {attempts}/{max_attempts})...")
                    return func(*args, **kwargs)
                except exceptions as e:
                    if attempts >= max_attempts:
                        logger.error(
                            f"Function {func.__name__} failed after {max_attempts} attempts due to {type(e).__name__}.",
                            exc_info=config.DEBUG
                        )
                        raise  # Re-raise the last exception

                    # Calculate delay with backoff and jitter
                    actual_jitter = delay * jitter * random.uniform(-1, 1)
                    wait_time = delay + actual_jitter
                    # Ensure wait time is not negative
                    wait_time = max(0, wait_time)

                    logger.warning(
                        f"Function {func.__name__} failed with {type(e).__name__} (Attempt {attempts}/{max_attempts}). "
                        f"Retrying in {wait_time:.2f} seconds...",
                        exc_info=config.DEBUG # Log traceback only in debug mode for warnings
                    )
                    time.sleep(wait_time)
                    delay *= backoff_factor
            # This line should theoretically not be reached if max_attempts > 0
            # but added for completeness and type checking.
            raise RuntimeError(f"Function {func.__name__} failed unexpectedly after exhausting retries.")

        return wrapper # type: ignore
    return decorator

# Example usage (for testing purposes)
if __name__ == "__main__":
    api_call_counter = 0

    # Define specific exceptions to retry on, e.g., common transient errors
    RETRYABLE_ERRORS = (TimeoutError, ConnectionError)

    @retry_on_exception(exceptions=RETRYABLE_ERRORS, max_attempts=4, initial_delay=0.5)
    def potentially_flaky_api_call(fail_times: int) -> str:
        """Simulates an API call that might fail a few times."""
        global api_call_counter
        api_call_counter += 1
        logger.info(f"Attempting API call #{api_call_counter}...")
        if api_call_counter <= fail_times:
            error_type = random.choice(RETRYABLE_ERRORS)
            raise error_type(f"Simulated transient error on attempt {api_call_counter}")
        logger.info("API call successful!")
        return "Success!"

    logger.info("--- Test Case 1: Success after failures ---")
    api_call_counter = 0 # Reset counter
    try:
        result = potentially_flaky_api_call(fail_times=2)
        logger.info(f"Final result: {result}")
    except Exception as e:
        logger.error(f"Test Case 1 failed unexpectedly: {e}", exc_info=True)

    print("\n" + "-"*20 + "\n")

    logger.info("--- Test Case 2: Failure after max attempts ---")
    api_call_counter = 0 # Reset counter
    try:
        result = potentially_flaky_api_call(fail_times=5) # Will fail more times than max_attempts
        logger.info(f"Final result (should not be reached): {result}")
    except Exception as e:
        logger.error(f"Test Case 2 failed as expected: {type(e).__name__}: {e}")
