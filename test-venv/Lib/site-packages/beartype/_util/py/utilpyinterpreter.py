#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **Python interpreter** utilities.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar._roarexc import (
    _BeartypeUtilPythonInterpreterException,
)
from beartype._data.typing.datatyping import CommandWords
from beartype._util.cache.utilcachecall import callable_cached
from platform import python_implementation
from sys import executable as sys_executable
from typing import TYPE_CHECKING

# ....................{ TESTERS                            }....................
@callable_cached
def is_python_pypy() -> bool:
    '''
    :data:`True` only if the active Python interpreter is **PyPy**.

    This tester is memoized for efficiency.
    '''

    return python_implementation() == 'PyPy'


def is_python_optimized() -> bool:
    '''
    :data:`True` only if the active Python interpreter is currently
    **optimized** (i.e., either the active Python process was passed one or more
    ``-O`` command-line options *or* the ``${PYTHONOPTIMIZE}`` environment
    variable is currently set to a positive integer).

    This tester is intentionally *not* memoized (e.g., by the
    ``@callable_cached`` decorator), as doing so would prevent this tester from
    detecting dynamic changes to the ``${PYTHONOPTIMIZE}`` environment variable
    manually applied by the external user. Technically, Python itself detects
    *no* such changes. Pragmatically, there's *no* demonstrable justification
    for :mod:`beartype` itself to behave similarly; since testing environment
    variable values is both trivial *and* yields a better outcome for users,
    this tester does so. Indeed, our userbase `explicitly requested that we do
    so <beartype issue_>`__.

    .. _beartype issue:
       https://github.com/beartype/beartype/issues/341
    '''

    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: *THE ORDER OF CONDITIONAL STATEMENTS BELOW IS SIGNIFICANT.*
    # Notably, mypy 0.940 erroneously emits this error when the "TYPE_CHECKING
    # or" condition is *NOT* the first condition of this "if" statement:
    #     beartype/_decor/main.py:294: error: Condition can't be inferred,
    #     unable to merge overloads [misc]
    #
    # See also:
    #     https://github.com/python/mypy/issues/12335#issuecomment-1065591703
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

    # If the active Python interpreter is either...
    if (  # pragma: no cover
        # Running under an external static type-checker (in which case there is
        # *NO* benefit to @beartype runtime type-checking whatsoever) *OR*...
        #
        # Note that this test is largely pointless. By definition, static type
        # checkers should *NOT* actually run any code -- merely parse and
        # analyze that code. Ergo, this boolean constant should *ALWAYS* be
        # false from the runtime context under which @beartype is only ever run.
        # Nonetheless, this test is only performed once per process and is thus
        # effectively free.
        TYPE_CHECKING or
        # Disabling the "__debug__" dunder global, either the current Python
        # process was invoked with one or more ``-O`` command-line option *OR*
        # the "${PYTHONOPTIMIZE}" environment variable was set to a positive
        # integer at process invocation time.
        not __debug__
    ):
        # Then this interpreter was optimized at process invocation time. In
        # this case, immediately return true.
        return True
    # Else, this interpreter is *NOT* running under an external static
    # type-checker and the "__debug__" dunder global is enabled. Although the
    # "${PYTHONOPTIMIZE}" environment variable was *NOT* set to a positive
    # integer at process invocation time, that variable *COULD* have since been
    # set by the external user (e.g., in an interactive REPL). Let's decide.

    # Avoid circular import dependencies.
    from beartype._util.os.utilosshell import get_shell_var_value_or_none

    # String value of this environment variable if set *OR* "None" otherwise.
    PYTHONOPTIMIZE_str = get_shell_var_value_or_none('PYTHONOPTIMIZE')

    # If this environment variable is set...
    if PYTHONOPTIMIZE_str is not None:
        # print(f'Detecting ${{PYTHONOPTIMIZE}} value {PYTHONOPTIMIZE_str}...')

        # Attempt to coerce this string into an integer.
        try:
            PYTHONOPTIMIZE_int = int(PYTHONOPTIMIZE_str)
        # If doing so raises *ANY* exception whatsoever, return false.
        except Exception:
            return False

        # If this integer is non-zero, this environment variable has since been
        # set to a non-zero integer by the user. In this case, return true.
        if PYTHONOPTIMIZE_int > 0:
            return True
        # Else, this environment variable remains zeroed and thus disabled.
    # Else, this environment variable is unset.

    # Return false as a fallback.
    return False

# ....................{ GETTERS ~ path                     }....................
@callable_cached
def get_interpreter_command_words() -> CommandWords:
    '''
    **Active Python interpreter command words** (i.e., iterable of one or more
    shell words unambiguously running the executable binary for this interpreter
    and machine architecture).

    This getter is memoized for efficiency.

    Caveats
    -------
    **This high-level getter should always be called in lieu of the low-level**
    :func:`.get_interpreter_filename` **getter** when attempting to rerun this
    interpreter as a subprocess of the active Python process. Why? Because the
    absolute filename of the executable binary for this interpreter is
    insufficient to unambiguously run this binary under edge cases, including:

    * **macOS.** Under macOS, the executable binary for this interpreter may be
      bundled with one or more other executable binaries targeting different
      machine architectures (e.g., 32-bit, 64-bit) in a single so-called
      "universal binary." Distinguishing between these bundled binaries requires
      passing this interpreter to a prefixing macOS-specific command: ``arch``.

    Returns
    -------
    CommandWords
        Iterable of one or more shell words unambiguously running this binary.
    '''

    #FIXME: Uncomment if required. Although this was certainly required a decade
    #ago, it's unclear whether this is still required; indeed, given the
    #increased prevalence of Apple Silicon, it seems likely that an entirely
    #different macOS-specific prefix might be required now. Thus, I sigh. *sigh*
    # # Avoid circular import dependencies.
    # from beartype._util.os.utilostest import is_os_macos
    #
    # # List of such shell words.
    # command_words = None  # type: ignore[assignment]
    #
    # # If the current platform is macOS, this interpreter is only unambiguously runnable via the
    # # macOS-specific "arch" command. In this case...
    # if is_os_macos():
    #     # Run the "arch" command.
    #     command_words = ['arch']
    #
    #     # Instruct this command to run the architecture-specific binary in
    #     # Python's universal binary corresponding to the current architecture.
    #     if is_wordsize_64():
    #         command_words.append('-i386')
    #     else:
    #         command_words.append('-x86_64')
    #
    #     # Instruct this command, lastly, to run this interpreter.
    #     command_words.append(get_interpreter_filename())
    # # Else, this interpreter is unambiguously runnable as is.
    # else:
    #     command_words = [get_interpreter_filename()]

    # Iterable of all interpreter shell words to be returned.
    command_words = (get_interpreter_filename(),)

    # Return this iterable.
    return command_words


@callable_cached
def get_interpreter_filename() -> str:
    '''
    Absolute filename of the executable binary underlying the active Python
    interpreter if Python provides this filename *or* raise an exception
    otherwise (i.e., if Python refuses to provide this filename, typically due
    to this filename being embedded in a frozen bundle of some sort).

    This getter is memoized for efficiency.

    Raises
    ------
    _BeartypeUtilPathException
        If Python successfully queried this filename but no such file exists.
    _BeartypeUtilPythonInterpreterException
        If Python failed to query this filename.

    Returns
    -------
    str
        Absolute filename of this binary.
    '''

    # Avoid circular import dependencies.
    from beartype._util.path.utilpathtest import die_unless_file_executable

    # If Python refuses to provide this filename, raise an exception.
    #
    # Note that this test intentionally matches both the empty string and
    # "None", as the official documentation for "sys.executable" states:
    #     If Python is unable to retrieve the real path to its executable,
    #     sys.executable will be an empty string or None.
    if not sys_executable:
        raise _BeartypeUtilPythonInterpreterException(
            'Absolute filename of active Python interpreter not found.')
    # Else, Python provides this filename.

    # If this file is *NOT* executable, raise an exception.
    die_unless_file_executable(sys_executable)
    # Else, this file is executable.

    # Return this filename.
    return sys_executable
