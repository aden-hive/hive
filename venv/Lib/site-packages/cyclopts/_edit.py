import os
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path


class EditorError(Exception):
    """Root editor-related error.

    Root exception raised by all exceptions in :func:`.edit`.
    """


class EditorDidNotSaveError(EditorError):
    """User did not save upon exiting :func:`.edit`."""


class EditorDidNotChangeError(EditorError):
    """User did not edit file contents in :func:`.edit`."""


class EditorNotFoundError(EditorError):
    """Could not find a valid text editor for :func`.edit`."""


def edit(
    initial_text: str = "",
    *,
    fallback_editors: Sequence[str] = ("nano", "vim", "notepad", "gedit"),
    editor_args: Sequence[str] = (),
    path: str | Path = "",
    encoding: str = "utf-8",
    save: bool = True,
    required: bool = True,
) -> str:
    """Get text input from a user by launching their default text editor.

    Parameters
    ----------
    initial_text: str
        Initial text to populate the text file with.
    fallback_editors: Sequence[str]
        If the text editor cannot be determined from the environment variable ``EDITOR``, attempt to use these text editors in the order provided.
    editor_args: Sequence[str]
        Additional CLI arguments that are passed along to the editor-launch command.
    path: Union[str, Path]
        If specified, the path to the file that should be opened.
        Text editors typically display this, so a custom path may result in a better user-interface.
        Defaults to a temporary text file.
    encoding: str
        File encoding to use.
    save: bool
        **Require** the user to save before exiting the editor. Otherwise raises :exc:`EditorDidNotSaveError`.
    required: bool
        **Require** for the saved text to be different from ``initial_text``. Otherwise raises :exc:`EditorDidNotChangeError`.

    Raises
    ------
    EditorError
        Base editor error exception. Explicitly raised if editor subcommand
        returned a non-zero exit code.
    EditorNotFoundError
        A suitable text editor could not be found.
    EditorDidNotSaveError
        The user exited the text-editor without saving and ``save=True``.
    EditorDidNotChangeError
        The user did not change the file contents and ``required=True``.

    Returns
    -------
    str
        The resulting text that was saved by the text editor.
    """
    import shutil
    import subprocess

    for editor in (os.environ.get("EDITOR"), *fallback_editors):
        if editor and shutil.which(editor):
            break
    else:
        raise EditorNotFoundError

    if path:
        path = Path(path)
        path.parent.mkdir(exist_ok=True, parents=True)
    else:
        path = Path(tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False).name)
    path.write_text(initial_text, encoding=encoding)
    past_time = time.time() - 5  # arbitrarily set time to 5 seconds ago; some systems only have 1 second precision.
    os.utime(path, (past_time, past_time))  # Set access and modification time
    start_stat = path.stat()

    try:
        subprocess.check_call([editor, path, *editor_args])
        end_stat = path.stat()
        if save and end_stat.st_mtime <= start_stat.st_mtime:
            raise EditorDidNotSaveError
        edited_text = path.read_text(encoding=encoding)
    except subprocess.CalledProcessError as e:
        raise EditorError(f"{editor} exited with status {e.returncode}") from e
    finally:
        path.unlink(missing_ok=True)

    if required and edited_text == initial_text:
        raise EditorDidNotChangeError

    return edited_text
