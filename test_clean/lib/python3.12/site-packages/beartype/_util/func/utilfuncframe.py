#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **call stack frame utilities** (i.e., callables introspecting the
current stack of frame objects, encapsulating the linear chain of calls to
external callables underlying the call to the current callable).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
import sys
from beartype.roar._roarexc import _BeartypeUtilCallFrameException
from beartype.typing import (
    Callable,
    Iterable,
    Optional,
)
from beartype._cave._cavefast import CallableFrameType
from beartype._data.typing.datatyping import TypeException

# ....................{ TESTERS                            }....................
#FIXME: Unit test us up, please.
def is_frame_caller_beartype(
    # Optional parameters.
    ignore_frames: int = 1,
    is_beartype_test: bool = False,
    exception_cls: TypeException = _BeartypeUtilCallFrameException,
) -> bool:
    '''
    :data:`True` only if the **caller** (i.e., callable directly calling this
    getter) resides inside the :mod:`beartype` codebase.

    This tester implicitly ignores the current call to this getter by
    unconditionally adding ``1`` to the passed number of stack frames.

    Parameters
    ----------
    ignore_frames : int, optional
        Number of stack frames on the current call stack to ignore (excluding
        the stack frame encapsulating the call to this getter). Defaults to 1,
        signifying the stack frame of the **caller** directly calling this
        getter.
    is_beartype_test : bool, optional
        :data:`True` only if this tester additionally returns :data:`True` when
        the caller resides inside the related :mod:`beartype_test` codebase.
        Defaults to :data:`False`; thus, this tester returns :data:`False` when
        the caller resides inside the related :mod:`beartype_test` codebase by
        default and treats :mod:`beartype_test` as an external third-party.
    exception_cls : TypeException, optional
        Type of exception to be raised in the event of a fatal error. Defaults
        to :class:`._BeartypeUtilCallFrameException`.

    Returns
    -------
    bool
        :data:`True` only if the caller is in the :mod:`beartype` codebase.
    '''
    assert isinstance(ignore_frames, int), f'{repr(ignore_frames)} not integer.'
    assert isinstance(is_beartype_test, bool), (
        f'{repr(is_beartype_test)} not bool.')

    # Fully-qualified name of the (sub)module declaring the caller (i.e.,
    # callable directly calling this dunder method) if that callable has a
    # (sub)module *or* "None" otherwise (e.g., if that callable resides outside
    # a module, usually due to being declared in an interactive REPL).
    frame_caller_module_name = get_frame_caller_module_name_or_none(
        ignore_frames=ignore_frames + 1, exception_cls=exception_cls)

    # Return true only if
    return (
        # The caller resides inside a module structure *AND*...
        frame_caller_module_name is not None and
        # Either...
        (
            # The caller resides inside the "beartype" package *OR*...
            frame_caller_module_name.startswith('beartype.') or
            (
                # The caller requests that the "beartype_test" package be
                # conflated with the "beartype" package *AND*...
                is_beartype_test and
                # The caller resides inside the "beartype_test" package...
                frame_caller_module_name.startswith('beartype_test.')
            )
        )
    )

# ....................{ GETTERS                            }....................
def get_frame_or_none(
    # Optional parameters.
    ignore_frames: int = 1,
    exception_cls: TypeException = _BeartypeUtilCallFrameException,
) -> Optional[CallableFrameType]:
    '''
    **Stack frame** (i.e., :class:`.CallableFrameType` object) on the current
    call stack *after* ignoring the passed number of stack frames.

    This getter implicitly ignores the current call to this getter by
    unconditionally adding ``1`` to the passed number of stack frames, implying
    this semantic interpretation of the passed number:

    * If ``ignore_frames == 0``, this getter returns the stack frame of the
      **caller** directly calling this getter. Since callers already know
      their own syntactic and semantic context, this is generally useless.
      Instead, callers typically want to ensure that ``ignore_frames >= 1``.
    * If ``ignore_frames == 1``, this getter returns the stack frame of the
      **parent caller** calling the caller directly calling this getter.
      Unsurprisingly, this is the standard use case and thus the default.
    * If ``ignore_frames == 2``, this getter returns the stack frame of the
      **parent parent caller** calling the parent caller calling the caller
      directly calling this getter.

    Caveats
    -------
    **This higher-level getter should typically be called in lieu of the
    lower-level** :func:`.get_frame` **getter.** The former handles edge cases
    and validates the passed input, whereas the latter is lower-level and thus
    more fragile with respect to both edge cases and input.

    Parameters
    ----------
    ignore_frames : int
        Number of stack frames on the current call stack to ignore (excluding
        the stack frame encapsulating the call to this getter). Defaults to 1,
        signifying the stack frame of the **parent caller** calling the caller
        directly calling this getter.
    exception_cls : TypeException, optional
        Type of exception to be raised in the event of a fatal error. Defaults
        to :class:`._BeartypeUtilCallFrameException`.

    Returns
    -------
    Optional[CallableFrameType]
        Either:

        * If the active Python interpreter defines the private low-level
          :func:`sys._getframe` getter *and*...

          * If a stack frame exists on the current call stack *after* ignoring
            the passed number of stack frames, that frame.
          * Else, the requested frame exceeds the **frame height** (i.e., total
            number of stack frames) of the current call stack. In this case,
            :data:`None`.

        * Else, :data:`None`.

    Raises
    ------
    exception_cls
        If either:

        * ``ignore_frames`` is *not* an integer.
        * ``ignore_frames`` is a negative integer.
    '''

    # If the passed number of stack frames to ignore is *NOT* a non-negative
    # integer, raise an exception.
    if not isinstance(ignore_frames, int):
        raise exception_cls(f'{repr(ignore_frames)} not integer.')
    if ignore_frames < 0:
        raise exception_cls(f'{repr(ignore_frames)} not non-negative integer.')

    # If the active Python interpreter defines the private low-level
    # sys._getframe() getter...
    if get_frame is not None:
        # Attempt to return the stack frame on the current call stack *AFTER*
        # ignoring the passed number of stack frames (as well as the current
        # call to this getter).
        try:
            return get_frame(ignore_frames + 1)
        # If the above call to sys._getframe() raised a "ValueError" exception,
        # then "ignore_frames + 1 >= frame_height" where "frame_height" is the
        # total number of stack frames on the current call stack. In this case,
        # return "None" instead.
        except ValueError:
            pass
        # If the above call to sys._getframe() raised an "OverflowError"
        # exception, then "ignore_frames + 1 >= frame_height" is almost
        # certainly the case. This case thus reduces to the prior case. Ergo,
        # return "None" instead. This exception message resembles:
        #     OverflowError: Python int too large to convert to C int
        except OverflowError:
            pass
    # Else, this interpreter fails to define that getter. In this case, return
    # "None" instead.

    # Return "None" as a latch-ditch fallback.
    return None


#FIXME: Mypy insists the sys._getframe() getter can return "None" in certain
#edge cases. But... what are those? Official documentation is seemingly silent
#on the issue. *sigh*
get_frame: Optional[Callable[[int], Optional[CallableFrameType]]] = getattr(
    sys, '_getframe', None)
'''
Private low-level :func:`sys._getframe` getter if the active Python interpreter
declares this getter *or* :data:`None` otherwise (i.e., if this interpreter does
*not* declare this getter).

All standard Python interpreters supported by this package including both
CPython *and* PyPy declare this getter. Ergo, this attribute should *always* be
a valid callable rather than :data:`None`.

If this getter is *not* :data:`None`, this getter's signature and docstring
under CPython resembles:

::

    _getframe([depth]) -> frameobject

    Return a frame object from the call stack.  If optional integer depth is
    given, return the frame object that many calls below the top of the
    stack. If that is deeper than the call stack, ValueError is raised. The
    default for depth is zero, returning the frame at the top of the call
    stack.

    Frame objects provide these attributes:
        f_back          next outer frame object (this frame's caller)
        f_builtins      built-in namespace seen by this frame
        f_code          code object being executed in this frame
        f_globals       global namespace seen by this frame
        f_lasti         index of last attempted instruction in bytecode
        f_lineno        current line number in Python source code
        f_locals        local namespace seen by this frame
        f_trace         tracing function for this frame, or None

Caveats
-------
**The higher-level** :func:`.get_frame_or_none` **getter should typically be
called in lieu of this lower-level getter.** The former handles edge cases and
validates the passed input, whereas the latter is lower-level and thus more
fragile with respect to both edge cases and input.

Parameters
----------
depth : int
    0-based index of the stack frame on the current call stack to be returned.
    Defaults to 0, signifying the stack frame encapsulating the lexical scope
    directly calling this getter.

Returns
-------
CallableFrameType
    Stack frame with the passed index on the current call stack.

Raises
------
ValueError
    If this index exceeds the **height** (i.e., total number of stack frames)
    of the current call stack.
'''

# ....................{ GETTERS ~ name : package           }....................
#FIXME: Unit test us up, please.
def get_frame_package_name_or_none(frame: CallableFrameType) -> Optional[str]:
    '''
    Fully-qualified name of the (sub)package of the (sub)module declaring the
    callable whose code object is that of the passed **stack frame** (i.e.,
    :class:`.CallableFrameType` instance encapsulating all metadata describing a
    single call on the current call stack) if that (sub)module has a
    (sub)package *or* :data:`None` otherwise (e.g., if that (sub)module is
    either a top-level module or script residing outside any package structure).

    Parameters
    ----------
    frame : CallableFrameType
        Stack frame to be inspected.

    Returns
    -------
    Optional[str]
        Either:

        * If the callable described by this frame resides in a package, the
          fully-qualified name of that package.
        * Else, :data:`None`.

    Raises
    ------
    exception_cls
         If that callable has *no* code object and is thus *not* pure-Python.

    See Also
    --------
    :func:`beartype._util.func.utilfunccodeobj.get_func_codeobj_basename`
        Related getter getting the unqualified basename of that callable.
    '''
    assert isinstance(frame, CallableFrameType), (
        f'{repr(frame)} not stack frame.')

    # Fully-qualified name of the parent package of the child module declaring
    # the callable whose code object is that of this stack frame's if that
    # module declares its name *OR* the empty string otherwise (e.g., if that
    # module is either a top-level module or script residing outside any parent
    # package structure).
    frame_package_name = frame.f_globals.get('__package__')

    # Return the name of this parent package.
    return frame_package_name

# ....................{ GETTERS ~ name : module            }....................
#FIXME: Unit test us up, please.
def get_frame_caller_module_name_or_none(
    # Optional parameters.
    ignore_frames: int = 1,
    exception_cls: TypeException = _BeartypeUtilCallFrameException,
) -> Optional[str]:
    '''
    Fully-qualified name of the (sub)module declaring the **caller** (i.e.,
    callable directly calling this getter) if that callable has a (sub)module
    *or* :data:`None` (e.g., if that callable resides outside any module
    structure, typically due to being declared directly in an interactive REPL).

    This getter implicitly ignores the current call to this getter by
    unconditionally adding ``1`` to the passed number of stack frames.

    Parameters
    ----------
    ignore_frames : int
        Number of stack frames on the current call stack to ignore (excluding
        the stack frame encapsulating the call to this getter). Defaults to 1,
        signifying the stack frame of the **caller** directly calling this
        getter.
    exception_cls : TypeException, optional
        Type of exception to be raised in the event of a fatal error. Defaults
        to :class:`._BeartypeUtilCallFrameException`.

    Returns
    -------
    Optional[str]
        Either:

        * If the callable described by this frame resides in a module, the
          fully-qualified name of that module.
        * Else, :data:`None`.

    See Also
    --------
    :func:`beartype._util.func.utilfunccodeobj.get_func_codeobj_basename`
        Related getter getting the unqualified basename of that callable.
    '''

    # Stack frame of the caller directly calling this getter, obtained by
    # ignoring the stack frame of the current call to this getter.
    frame_caller = get_frame_or_none(
        ignore_frames=ignore_frames + 1, exception_cls=exception_cls)

    # Return either...
    return (
        # If this stack frame exists, return either the fully-qualified name of
        # the module defining the caller if the caller resides in a module *OR*
        # "None" otherwise (e.g., if the caller was defined in a REPL).
        get_frame_module_name_or_none(frame_caller)
        if frame_caller is not None else
        # Else, *NO* such stack frame exists, implying this getter was probably
        # directly called from an interactive REPL (e.g., "ipython"). In this
        # case, return "None".
        None
    )


#FIXME: Unit test us up, please.
def get_frame_module_name_or_none(frame: CallableFrameType) -> Optional[str]:
    '''
    Fully-qualified name of the (sub)module declaring the callable whose code
    object is that of the passed **stack frame** (i.e.,
    :class:`.CallableFrameType` instance encapsulating all metadata describing a
    single call on the current call stack) if that callable has a (sub)module
    *or* :data:`None` otherwise (e.g., if that callable resides outside any
    module structure, typically due to being declared directly in an interactive
    REPL).

    Parameters
    ----------
    frame : CallableFrameType
        Stack frame to be inspected.
    exception_cls : TypeException
        Type of exception to be raised in = _BeartypeUtilCallFrameException,

    Returns
    -------
    Optional[str]
        Either:

        * If the callable described by this frame resides in a module, the
          fully-qualified name of that module.
        * Else, :data:`None`.

    See Also
    --------
    :func:`beartype._util.func.utilfunccodeobj.get_func_codeobj_basename`
        Related getter getting the unqualified basename of that callable.
    '''
    assert isinstance(frame, CallableFrameType), (
        f'{repr(frame)} not stack frame.')

    # Fully-qualified name of the module declaring the callable described by
    # this frame.
    frame_module_name = frame.f_globals.get('__name__')

    # Return this name.
    return frame_module_name


#FIXME: Preserved for posterity. Currently unused, but potentially useful.
# from beartype._data.func.datafunccodeobj import FUNC_CODEOBJ_NAME_MODULE
# #FIXME: Unit test us up, please.
# def get_frame_name(
#     # Mandatory parameters.
#     frame: CallableFrameType,
#
#     # Optional parameters.
#     exception_cls: TypeException = _BeartypeUtilCallFrameException,
# ) -> str:
#     '''
#     Fully-qualified name of the callable whose code object is that of the passed
#     **stack frame** (i.e., :class:`types.CallableFrameType` instance
#     encapsulating all metadata describing a single call on the current call
#     stack).
#
#     Parameters
#     ----------
#     frame : CallableFrameType
#         Stack frame to be inspected.
#
#     Returns
#     -------
#     str
#         Fully-qualified name of the callable described by this frame.
#     '''
#
#     # Avoid circular import dependencies.
#     from beartype._util.func.utilfunccodeobj import get_func_codeobj_basename
#
#     # Fully-qualified name of the module declaring the callable described by
#     # this frame.
#     frame_module_name = get_frame_module_name_or_none(
#         frame=frame, exception_cls=exception_cls)
#
#     # Unqualified basename of that callable.
#     frame_basename = get_func_codeobj_basename(
#         func=frame, exception_cls=exception_cls)
#
#     # Possibly fully-qualified name of that callable, defined as either...
#     frame_name = (
#         # If that callable is *NOT* actually a callable but instead the
#         # top-level lexical scope of a module, omit the prefixing module name
#         # (which is, in any case, the meaningless magic string "<module>");
#         frame_basename
#         if frame_module_name == FUNC_CODEOBJ_NAME_MODULE else
#         # Else, that callable is actually a callable. In this case, prefix the
#         # unqualified basename of that callable by the fully-qualified name of
#         # the module declaring that callable.
#         f'{frame_module_name}.{frame_basename}'
#     )
#
#     # Return this name.
#     return frame_name

# ....................{ ITERATORS                          }....................
def iter_frames(
    # Optional parameters.
    func_stack_frames_ignore: int = 0,
) -> Iterable[CallableFrameType]:
    '''
    Generator yielding one **frame** (i.e., :class:`types.CallableFrameType`
    instance) for each call on the current **call stack** (i.e., stack of frame
    objects, encapsulating the linear chain of calls to external callables
    underlying the current call to this callable).

    Notably, for each:

    * **C-based callable call** (i.e., call of a C-based rather than
      pure-Python callable), this generator yields one frame encapsulating *no*
      code object. Only pure-Python frame objects have code objects.
    * **Class-scoped callable call** (i.e., call of an arbitrary callable
      occurring at class scope rather than from within the body of a callable
      or class, typically due to a method being decorated), this generator
      yields one frame ``func_frame`` for that class ``cls`` such that
      ``func_frame.f_code.co_name == cls.__name__`` (i.e., the name of the code
      object encapsulated by that frame is the unqualified name of the class
      encapsulating the lexical scope of this call). Actually, we just made all
      of that up. That is *probably* (but *not* necessarily) the case. Research
      is warranted.
    * **Module-scoped callable call** (i.e., call of an arbitrary callable
      occurring at module scope rather than from within the body of a callable
      or class, typically due to a function or class being decorated), this
      generator yields one frame ``func_frame`` such that
      ``func_frame.f_code.co_name == '<module>'`` (i.e., the name of the code
      object encapsulated by that frame is the placeholder string assigned by
      the active Python interpreter to all scopes encapsulating the top-most
      lexical scope of a module in the current call stack).

    The above constraints imply that frames yielded by this generator *cannot*
    be assumed to encapsulate code objects. See the "Examples" subsection for
    standard logic handling this edge case.

    Caveats
    -------
    **This high-level iterator requires the private low-level**
    :func:`sys._getframe` **getter.** If that getter is undefined, this iterator
    reduces to the empty generator yielding nothing rather than raising an
    exception. Since all standard Python implementations (e.g., CPython, PyPy)
    define that getter, this should typically *not* be a real-world concern.

    Parameters
    ----------
    func_stack_frames_ignore : int, optional
        Number of frames on the call stack to be ignored (i.e., silently
        incremented past). Defaults to 0.

    Returns
    -------
    Iterable[CallableFrameType]
        Generator yielding one frame for each call on the current call stack.

    See Also
    --------
    :func:`.get_frame`
        Further details on stack frame objects.

    Examples
    --------
    :: code-block:: pycon

       >>> from beartype._util.func.utilfunccodeobj import (
       ...     get_func_codeobj_or_none)
       >>> from beartype._util.func.utilfuncframe import iter_frames

       # For each stack frame on the call stack...
       >>> for func_frame in iter_frames():
       ...     # Code object underlying this frame's scope if this scope is
       ...     # pure-Python *OR* "None" otherwise.
       ...     func_frame_codeobj = get_func_codeobj_or_none(func_frame)
       ...
       ...     # If this code object does *NOT* exist, this scope is C-based.
       ...     # In this case, silently ignore this scope and proceed to the
       ...     # next frame in the call stack.
       ...     if func_frame_codeobj is None:
       ...         continue
       ...     # Else, this code object exists, implying this scope to be
       ...     # pure-Python.
       ...
       ...     # Fully-qualified name of this scope's module.
       ...     func_frame_module_name = func_frame.f_globals['__name__']
       ...
       ...     # Unqualified name of this scope.
       ...     func_frame_name = func_frame_codeobj.co_name
       ...
       ...     # Print the fully-qualified name of this scope.
       ...     print(f'On {func_frame_module_name}.{func_frame_name}()!')
    '''
    assert isinstance(func_stack_frames_ignore, int), (
        f'{func_stack_frames_ignore} not integer.')
    assert func_stack_frames_ignore >= 0, (
        f'{func_stack_frames_ignore} negative.')

    # If the active Python interpreter fails to declare the private
    # sys._getframe() getter, reduce to the empty generator (i.e., noop).
    if get_frame is None:  # pragma: no cover
        yield from ()
        return
    # Else, the active Python interpreter declares the sys._getframe() getter.

    # Attempt to obtain the...
    try:
        # Next non-ignored frame following the last ignored frame, ignoring an
        # additional frame embodying the current call to this iterator.
        func_frame = get_frame(func_stack_frames_ignore + 1)  # type: ignore[misc]
    # If doing so raises a "ValueError" exception...
    except ValueError as value_error:
        # Whose message matches this standard boilerplate, the caller requested
        # that this generator ignore more stack frames than currently exist on
        # the call stack. Permitting this exception to unwind the call stack
        # would only needlessly increase the fragility of this already fragile
        # mission-critical generator. Instead, swallow this exception and
        # silently reduce to the empty generator (i.e., noop).
        if str(value_error) == 'call stack is not deep enough':
            yield from ()
            return
        # Whose message does *NOT* match this standard boilerplate, an
        # unexpected exception occurred. In this case, re-raise this exception.

        raise
    # Else, doing so raised *NO* "ValueError" exception.
    # print(f'start frame: {repr(func_frame)}')

    # While at least one frame remains on the call stack...
    while func_frame:
        # print(f'current frame: {repr(func_frame)}')

        # Yield this frame to the caller.
        yield func_frame

        # Iterate to the next frame on the call stack.
        func_frame = func_frame.f_back
