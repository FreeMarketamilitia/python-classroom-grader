"""Command Line Interface (CLI) for user interaction."""

import sys
import os
from typing import List, Dict, Any, TypeVar, Callable, Optional

# Use rich for better CLI output, fall back to standard print if not available
RICH_AVAILABLE = False
try:
    from rich.console import Console
    from rich.table import Table
    from rich.prompt import Prompt, Confirm, IntPrompt
    from rich.panel import Panel
    from rich.text import Text
    RICH_AVAILABLE = True
except ImportError:
    print("Warning: 'rich' library not found. Falling back to basic CLI.")
    # Define dummy classes/functions if rich is not available
    class Console:
        def print(self, *args, **kwargs): print(*args)
        def rule(self, *args, **kwargs): print("-"*20)
    class Prompt:
        @staticmethod
        def ask(prompt, choices=None, default=None, show_default=True):
            full_prompt = prompt
            if choices:
                full_prompt += f" (Choices: {', '.join(choices)})"
            if default:
                full_prompt += f" [default: {default}]"
            return input(full_prompt + ": ")
    class Confirm:
        @staticmethod
        def ask(prompt, default=False):
            response = input(prompt + f" ('y'/'n') [default: {'y' if default else 'n'}]: ").lower()
            if not response:
                return default
            return response == 'y'
    class IntPrompt:
         @staticmethod
         def ask(prompt, choices=None, default=None):
             while True:
                 try:
                    val_str = Prompt.ask(prompt, choices=[str(c) for c in choices] if choices else None, default=default)
                    val = int(val_str)
                    if choices and str(val) not in choices:
                         print("Invalid choice, please try again.")
                         continue
                    return val
                 except ValueError:
                     print("Invalid input. Please enter a number.")
    class Panel: # Dummy Panel
        def __init__(self, content, *args, **kwargs): self.content = content
        def __rich_console__(self, console, options): yield self.content # Just yield content

# Assuming common setup is done correctly
try:
    import config
    from utils.logger import get_logger
    from utils.error_handler import UserCancelledError
except ImportError:
    # Adjust path if run directly or structure differs
    sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
    import config
    from utils.logger import get_logger
    from utils.error_handler import UserCancelledError

logger = get_logger()
console = Console()

T = TypeVar('T') # Generic type for selection items

def display_welcome():
    """Displays a welcome message."""
    console.print(Panel(
        "[bold green]🚀 Welcome to the Google Classroom AI Grading Assistant 🚀[/bold green]",
        title="Welcome",
        border_style="blue"
    ))
    console.print("This tool helps automate grading using Google APIs and Gemini AI.")
    console.rule()

def display_farewell():
    """Displays a farewell message."""
    console.rule()
    console.print("[bold cyan]👋 Grading process complete. Exiting.[/bold cyan]")

def display_error(message: str):
    """Displays an error message in a standard format."""
    console.print(Panel(f"[bold red]Error:[/bold red] {message}", title="Error", border_style="red"))

def display_warning(message: str):
    """Displays a warning message."""
    console.print(f"[yellow]Warning:[/yellow] {message}")

def display_success(message: str):
    """Displays a success message."""
    console.print(f"[green]Success:[/green] {message}")

def display_step(step_number: int, description: str):
    """Displays the current step in the process."""
    console.print(f"\n[bold blue]Step {step_number}:[/bold blue] {description}")
    console.rule()

def prompt_for_selection(items: List[T], display_func: Callable[[T], str], prompt_message: str) -> Optional[T]:
    """Prompts the user to select an item from a list.

    Args:
        items: The list of items to choose from.
        display_func: A function that takes an item and returns a string representation for display.
        prompt_message: The message to display before the list.

    Returns:
        The selected item, or None if the user cancels or no items are available.

    Raises:
        UserCancelledError: If the user explicitly cancels (e.g., by entering 0).
    """
    if not items:
        console.print("[yellow]No items available for selection.[/yellow]")
        return None

    console.print(prompt_message)

    if RICH_AVAILABLE:
        table = Table(title="Available Items", show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Item Details", style="cyan")

        choices = []
        for i, item in enumerate(items):
            display_text = display_func(item)
            table.add_row(str(i + 1), display_text)
            choices.append(str(i + 1))

        console.print(table)
        console.print("Enter 0 to cancel.")

        try:
            choice = IntPrompt.ask("Select item number", choices=choices + ["0"])
            if choice == 0:
                raise UserCancelledError("User cancelled selection.")
            return items[choice - 1]
        except Exception as e:
             # Catch potential rich prompt errors or other issues
             logger.error(f"Error during rich prompt selection: {e}", exc_info=config.DEBUG)
             raise UserCancelledError("Selection failed or cancelled.") from e

    else: # Basic fallback
        for i, item in enumerate(items):
            print(f"  {i + 1}: {display_func(item)}")
        print("  0: Cancel")

        while True:
            try:
                choice_str = input("Select item number: ")
                choice = int(choice_str)
                if choice == 0:
                    raise UserCancelledError("User cancelled selection.")
                if 1 <= choice <= len(items):
                    return items[choice - 1]
                else:
                    print("Invalid choice, please try again.")
            except ValueError:
                print("Invalid input. Please enter a number.")
            except UserCancelledError:
                raise # Propagate cancellation
            except Exception as e:
                 logger.error(f"Error during basic prompt selection: {e}", exc_info=config.DEBUG)
                 raise UserCancelledError("Selection failed or cancelled.") from e

def confirm_action(message: str, default: bool = True) -> bool:
    """Asks the user for confirmation.

    Args:
        message: The confirmation prompt message.
        default: The default action if the user just presses Enter.

    Returns:
        True if the user confirms, False otherwise.
    """
    if RICH_AVAILABLE:
        return Confirm.ask(message, default=default)
    else:
        response = input(message + f" ('y'/'n') [default: {'y' if default else 'n'}]: ").lower().strip()
        if not response:
            return default
        return response == 'y'

def display_processed_summary(processed_submissions: List[Dict[str, Any]]):
    """Displays a summary table of processed submissions.

    Args:
        processed_submissions: List of processed submission dictionaries.
    """
    if not processed_submissions:
        console.print("[yellow]No submissions were processed.[/yellow]")
        return

    console.print("\n[bold]Processing Summary:[/bold]")

    if RICH_AVAILABLE:
        table = Table(title="Submission Processing Results", show_header=True, header_style="bold magenta")
        table.add_column("Submission ID", style="dim")
        table.add_column("User ID", style="dim")
        table.add_column("Email", style="cyan")
        table.add_column("Content Status", style="green")
        table.add_column("Feedback Status", style="blue")
        table.add_column("Errors", style="red")

        success_count = 0
        error_count = 0

        for sub in processed_submissions:
            content_status = "Extracted" if sub.get('content') else "-"
            feedback_status = "Generated" if sub.get('feedback') else "-"
            error_text = sub.get('error') or "None"

            if sub.get('error') and ("extraction failed" in sub['error'] or "AI feedback" in sub['error']):
                 error_count += 1
                 content_status = Text(content_status, style="yellow")
                 feedback_status = Text(feedback_status, style="yellow")
                 error_text = Text(error_text, style="bold yellow")
            elif sub.get('error'):
                error_count += 1 # Count other errors too
                error_text = Text(error_text, style="yellow") # Less severe error style
            else:
                 success_count += 1
                 error_text = Text(error_text, style="dim green")

            table.add_row(
                sub.get('submission_id', 'N/A'),
                sub.get('user_id', 'N/A'),
                sub.get('student_email', 'N/A'),
                content_status,
                feedback_status,
                error_text
            )

        console.print(table)
        console.print(f"Summary: {success_count} processed successfully, {error_count} encountered errors.")
    else:
        # Basic text summary
        for i, sub in enumerate(processed_submissions):
            print(f"\n--- Submission {i+1} ---")
            print(f"  ID: {sub.get('submission_id', 'N/A')}")
            print(f"  User ID: {sub.get('user_id', 'N/A')}")
            print(f"  Email: {sub.get('student_email', 'N/A')}")
            print(f"  Content Extracted: {'Yes' if sub.get('content') else 'No'}")
            print(f"  Feedback Generated: {'Yes' if sub.get('feedback') else 'No'}")
            print(f"  Error: {sub.get('error') or 'None'}")
        print("-"*20)

# --- Display functions for specific items ---

def format_course_for_display(course: Dict[str, Any]) -> str:
    """Formats a course dictionary for display in selection prompts."""
    return f"{course.get('name', 'Unnamed Course')} (ID: {course.get('id', 'N/A')})"

def format_assignment_for_display(assignment: Dict[str, Any]) -> str:
    """Formats an assignment dictionary for display in selection prompts."""
    return f"{assignment.get('title', 'Untitled Assignment')} (ID: {assignment.get('id', 'N/A')})"

# Example usage (for testing CLI elements)
if __name__ == "__main__":
    display_welcome()

    display_step(1, "Testing Selection")
    # Mock data
    mock_courses = [
        {'id': '123', 'name': 'Test Course Alpha'},
        {'id': '456', 'name': 'Another Course Beta'},
        {'id': '789', 'name': 'History 101'}
    ]
    try:
        selected_course = prompt_for_selection(mock_courses, format_course_for_display, "Please select a course:")
        if selected_course:
            console.print(f"\nYou selected: {format_course_for_display(selected_course)}", style="bold green")
        else:
            console.print("\nNo course selected.")
    except UserCancelledError:
        console.print("\nUser cancelled selection.")

    display_step(2, "Testing Confirmation")
    confirmed = confirm_action("Do you want to proceed with the next step?", default=True)
    console.print(f"\nUser confirmed: {confirmed}")

    display_step(3, "Testing Summary Display")
    mock_processed = [
        {'submission_id': 'sub1', 'user_id': 'user1', 'student_email': 's1@example.com', 'content': 'abc', 'feedback': 'Good job!', 'error': None},
        {'submission_id': 'sub2', 'user_id': 'user2', 'student_email': 's2@example.com', 'content': None, 'feedback': None, 'error': 'Content extraction failed: File not found'},
        {'submission_id': 'sub3', 'user_id': 'user3', 'student_email': 's3@example.com', 'content': 'def', 'feedback': None, 'error': 'AI feedback skipped (no client)'}
    ]
    display_processed_summary(mock_processed)

    display_farewell()
