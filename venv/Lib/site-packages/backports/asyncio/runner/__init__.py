"""Entrypoint for asyncio.Runner backport.

Below is a quick summary of the changes.

asyncio.tasks._PyTask was overridden to be able to patch some behavior in Python < 3.11 and allow
this backport to function. _CTask implementation of the API is not in scope of this backport at this time.

The list of minimal changes backported are the following:
  1. contextvars.copy_context behavior change on __init__.
  2. _num_cancels_requested attribute
  3. cancelling() function
  4. uncancel() function

All of these are implemented in [CTask](https://github.com/python/cpython/blob/3.11/Modules/_asynciomodule.c)
in Python 3.11, but the _CTask implementations were not backported. Trying to provide 1-1 Task implementation
in this backport to Python 3.11 is not in scope and not needed.

For #1, since we can't mimic how `contextvars.copy_context` is used in Python 3.11 in the new __init__:

```python
if context is None:
    self._context = contextvars.copy_context()
else:
    self._context = context
```

This is achieved in `Runner.run` by patching `contextvars.copy_context` temporarily to return
our copied context instead. This assures the contextvars are preserved when the runner runs.

This approach was necessary since versions below 3.11 always run `self._context = contextvars.copy_context()`
right before being scheduled. This helps us avoid having to backport the Task context kwarg signature and
the new task factory implementation.
"""

from .runner import Runner

__all__ = ["Runner"]
