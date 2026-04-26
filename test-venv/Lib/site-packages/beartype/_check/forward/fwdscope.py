#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **forward scope classes** (i.e., dictionary subclasses deferring the
resolutions of local and global scopes of classes and callables decorated by the
:func:`beartype.beartype` decorator when dynamically evaluating stringified type
hints for those classes and callables).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
#FIXME: The BeartypeForwardScope.__init__() "scope_dict: LexicalScope" parameter
#should probably instead be typed as:
#from collections import ChainMap
#...
#    def __init__(self, scope_dict: ChainMap, scope_name: str) -> None:
#
#Why? Because "ChainMap" exists to literally solve this *EXACT* problem.
#Notably, the current approach effectively forces a "BeartypeForwardScope" to
#take a possibly desynchronized "snapshot" of a lexical scope at a certain point
#in time. If either the locals or globals of that scope are subsequently
#modified by an external caller, however, that "BeartypeForwardScope" will then
#be desynchronized from those locals and globals.
#
#A "ChainMap" trivially resolves this. How? Internally, a "ChainMap" only
#holds *REFERENCES* to external locals and globals dictionaries. External
#updates to those external dictionaries are thus *IMMEDIATELY* reflected inside
#the "ChainMap" itself, resolving any desynchronization woes. *facepalm*

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintForwardRefException
from beartype.typing import Type
from beartype._data.typing.datatyping import LexicalScope
from beartype._check.forward.reference.fwdrefabc import (
    _BeartypeForwardRefIndexableABC)
from beartype._check.forward.reference.fwdrefmake import (
    make_forwardref_indexable_subtype)
from beartype._util.func.utilfuncframe import (
    get_frame_caller_module_name_or_none,
    is_frame_caller_beartype,
)
from beartype._util.text.utiltextidentifier import die_unless_identifier

# ....................{ SUBCLASSES                         }....................
#FIXME: Unit test us up, please.
class BeartypeForwardScope(LexicalScope):
    '''
    **Forward scope** (i.e., dictionary mapping from the name to value of each
    locally and globally accessible attribute in the local and global scope of a
    class or callable as well as deferring the resolution of each currently
    undeclared attribute in that scope by replacing that attribute with a
    forward reference proxy resolved only when that attribute is passed as the
    second parameter to an :func:`isinstance`-based runtime type-check).

    This dictionary is principally employed to dynamically evaluate stringified
    type hints, including:

    * :pep:`484`-compliant forward references.
    * :pep:`563`-postponed type hints.

    Attributes
    ----------
    _scope_dict : LexicalScope
        **Composite local and global scope** (i.e., dictionary mapping from
        the name to value of each locally and globally accessible attribute
        in the local and global scope of some class or callable) underlying
        this forward scope. See the :meth:`__init__` method for details.
    _scope_name : str
        Fully-qualified name of this forward scope. See the :meth:`__init__`
        method for details.
    '''

    # ..................{ CLASS VARIABLES                    }..................
    # Slot all instance variables defined on this object to minimize the time
    # complexity of both reading and writing variables across frequently
    # called @beartype decorations. Slotting has been shown to reduce read and
    # write costs by approximately ~10%, which is non-trivial.
    __slots__ = (
        '_scope_dict',
        '_scope_name',
    )

    # ..................{ INITIALIZERS                       }..................
    def __init__(self, scope_dict: LexicalScope, scope_name: str) -> None:
        '''
        Initialize this forward scope.

        Attributes
        ----------
        scope_dict : LexicalScope
            **Composite local and global scope** (i.e., dictionary mapping from
            the name to value of each locally and globally accessible attribute
            in the local and global scope of some class or callable) underlying
            this forward scope.

            Crucially, **this dictionary must composite both the local and
            global scopes for that class or callable.** This dictionary must
            *not* provide only the local or global scope; this dictionary must
            provide both. Why? Because this forward scope is principally
            intended to be passed as the second and last parameter to the
            :func:`eval` builtin, called by the
            :func:`beartype._check.forward.fwdresolve.resolve_hint` function. For
            unknown reasons, :func:`eval` only calls the :meth:`__missing__`
            dunder method of this forward scope when passed only two parameters
            (i.e., when passed only a global scope); :func:`eval` does *not*
            call the :meth:`__missing__` dunder method of this forward scope
            when passed three parameters (i.e., when passed both a global and
            local scope). Presumably, this edge case pertains to the official
            :func:`eval` docstring -- which reads:

                The globals must be a dictionary and locals can be any mapping,
                defaulting to the current globals and locals.
                If only globals is given, locals defaults to it.

            Clearly, :func:`eval` treats globals and locals fundamentally
            differently (probably for efficiency or obscure C implementation
            details). Since :func:`eval` only supports a single unified globals
            dictionary for our use case, the caller *must* composite together
            the global and local scopes into this dictionary. Praise to Guido.
        scope_name : str
            Fully-qualified name of this forward scope. For example:

            * ``"some_package.some_module"`` for a module scope (e.g., to
              resolve a global class or callable against this scope).
            * ``"some_package.some_module.SomeClass"`` for a class scope (e.g.,
              to resolve a nested class or callable against this scope).

        Raises
        ------
        BeartypeDecorHintForwardRefException
            If this scope name is *not* a valid Python attribute name.
        '''
        assert isinstance(scope_dict, dict), (
            f'{repr(scope_dict)} not dictionary.')

        # Initialize our superclass with this lexical scope, efficiently
        # pre-populating this dictionary with all previously declared attributes
        # underlying this forward scope.
        super().__init__(scope_dict)

        # If this scope name is syntactically invalid, raise an exception.
        die_unless_identifier(
            text=scope_name,
            exception_cls=BeartypeDecorHintForwardRefException,
            exception_prefix='Forward scope name ',
        )
        # Else, this scope name is syntactically valid.

        # Classify all passed parameters.
        self._scope_dict = scope_dict
        self._scope_name = scope_name

    # ..................{ DUNDERS                            }..................
    def __missing__(
        self, hint_name: str) -> Type[_BeartypeForwardRefIndexableABC]:
        '''
        Dunder method explicitly called by the superclass
        :meth:`dict.__getitem__` method implicitly called on each ``[``- and
        ``]``-delimited attempt to access an **unresolved type hint** (i.e.,
        *not* currently defined in this scope) with the passed name.

        This dunder method transparently replaces this unresolved type hint with
        a **forward reference proxy** (i.e., concrete subclass of the private
        :class:`beartype._check.forward.reference.fwdrefabc.BeartypeForwardRefABC`
        abstract base class (ABC), which resolves this type hint on the first
        call to the :func:`isinstance` builtin whose second argument is that
        subclass).

        This dunder method assumes that:

        * This scope is only partially initialized.
        * This type hint has yet to be declared in this scope.
        * This type hint will be declared in this scope by the later time that
          this dunder method is called.

        Caveats
        -------
        **This dunder method is susceptible to misuse by third-party frameworks
        that perform call stack inspection.** The higher-level
        :func:`beartype._check.forward.fwdresolve.resolve_hint` internally invokes
        this dunder method by calling the :func:`eval` builtin, which then adds
        a new stack frame to the call stack whose ``f_locals`` and ``f_globals``
        attributes are this dictionary. If a third-party framework introspects
        the call stack containing this new stack frame, this dictionary's
        failure to conform to the behavior of a lexical scope could induce
        failure in that third-party framework. Does this edge case arise in
        real-world usage, though? It does.

        Consider ``pytest``, which detects whether each frame on the call stack
        defines the ``pytest``-specific ``__tracebackhide__`` dunder attribute:

        .. code-block:: python

           def ishidden(self, excinfo: ExceptionInfo[BaseException] | None) -> bool:
               """Return True if the current frame has a var __tracebackhide__
               resolving to True.

               If __tracebackhide__ is a callable, it gets called with the
               ExceptionInfo instance and can decide whether to hide the traceback.

               Mostly for internal use.
               """
               tbh: bool | Callable[[ExceptionInfo[BaseException] | None], bool] = False
               for maybe_ns_dct in (self.frame.f_locals, self.frame.f_globals):
                   # in normal cases, f_locals and f_globals are dictionaries
                   # however via `exec(...)` / `eval(...)` they can be other types
                   # (even incorrect types!).
                   # as such, we suppress all exceptions while accessing __tracebackhide__
                   try:
                       tbh = maybe_ns_dct["__tracebackhide__"]
                   except Exception:
                       pass
                   else:
                       break
               if tbh and callable(tbh):
                   return tbh(excinfo)

        In obscure edge cases involving :mod:`beartype`, ``pytest``, and
        :pep:`563`, one or both of the ``self.frame.f_locals`` and/or
        ``self.frame.f_globals`` dictionaries are instances of the
        :class:`beartype._check.forward.fwdscope.BeartypeForwardScope`
        dictionary subclass. The ``tbh = maybe_ns_dct["__tracebackhide__"]``
        statement then implicitly invokes this dunder method, which then creates
        and returns a new forward reference proxy encapsulating the missing
        ``__tracebackhide__`` attribute: e.g.,

        .. code-block:: python

           tbh = <forwardref__tracebackhide__(
                     __name_beartype__='__tracebackhide__',
                     __scope_name_beartype__='beartype_test.a00_unit.data.pep.pep563.pep695.data_pep563_pep695'
           )>

        Since forward reference proxies are types *and* since types are callable
        (in the sense that "calling" a type instantiates that type), forward
        reference proxies are callable. However, they're not. The
        :class:`beartype._check.forward.reference.fwdrefabc.BeartypeForwardRefABC`
        superclass prohibits instantiation by defining a ``__new__()`` dunder
        method that unconditionally raises exceptions, which then induces the
        ``pytest`` to raise the same exceptions on attempting to
        ``return tbh(excinfo)``.

        This dunder method avoids that and all similar issues by:

        * Detecting whether this dunder method is called by a caller defined
          inside or outside the :mod:`beartype` codebase.
        * If this dunder method is called by a caller defined inside the
          :mod:`beartype` codebase, creating and returning a forward reference
          proxy.
        * If this dunder method is called by a caller defined outside the
          :mod:`beartype` codebase, raising a standard :class:`AttributeError`.

        Parameters
        ----------
        hint_name : str
            Relative (i.e., unqualified) or absolute (i.e., fully-qualified)
            name of this unresolved type hint.

        Returns
        -------
        Type[_BeartypeForwardRefIndexableABC]
            Forward reference proxy deferring the resolution of this unresolved
            type hint.

        Raises
        ------
        BeartypeDecorHintForwardRefException
            If this type hint name is *not* a valid Python attribute name.
        '''
        # print(f'Missing type hint: {repr(hint_name)}')

        # If this type hint name is syntactically invalid, raise an exception.
        die_unless_identifier(
            text=hint_name,
            exception_cls=BeartypeDecorHintForwardRefException,
            exception_prefix='Forward reference ',
        )
        # Else, this type hint name is syntactically valid.

        # If it is *NOT* the case that...
        if not (  # pragma: no cover
            # The caller directly resides inside the "beartype" package *OR*...
            is_frame_caller_beartype(ignore_frames=1) or
            # The caller indirectly resides inside the "beartype" package. This
            # common edge cases arises when the parent
            # beartype._check.forward.fwdresolve.resolve_hint() function calls the
            # eval() builtin to dynamically evaluate the passed stringified type
            # hint: e.g.,
            #     # This is the eval() call triggering this call.
            #     hint_resolved = eval(hint, decor_meta.func_wrappee_scope_forward)
            #
            # In this case, the prior call to the is_frame_caller_beartype()
            # tester tested the stack frame of that eval() call and,
            # specifically, the "__name__" attribute of the global namespace of
            # the external user-defined module proxied by this forward scope.
            # Naturally, that module is external and thus *NOT* inside the
            # "beartype" package. Ignore this stack frame in the hopes that the
            # parent stack frame of that eval() call will be the
            # "beartype._check.forward.fwdresolve" submodule performing that call.
            # Look. We don't like this fragility any more than you do, but
            # Python shenanigans leave us little choice. Our paws are tied!
            is_frame_caller_beartype(ignore_frames=2)
        ):
            # Then the caller is a third-party. In this case, assume this
            # erroneous attempt to access a non-existent attribute of this
            # forward scope to *ACTUALLY* be an Easier to Ask for Permission
            # than Forgiveness (EAFP)-driven to detect whether this forward
            # scope defines this attribute ala the hasattr() builtin. In this
            # case, raise the expected "AttributeError." See the "Caveats"
            # subsection of this dunder method's docstring for commentary.

            # print(f'caller+1: {get_frame_caller_module_name_or_none(ignore_frames=1)}')
            # print(f'caller+2: {get_frame_caller_module_name_or_none(ignore_frames=2)}')
            # print(f'caller+3: {get_frame_caller_module_name_or_none(ignore_frames=3)}')

            # Exception message to be raised.
            exception_message = (
                f'Forward reference scope "{self._scope_name}" '
                f'attribute "{hint_name}" '
            )

            # Fully-qualified name of the module declaring the caller if any
            # *OR* "None" otherwise (e.g., if declared in an interactive REPL).
            frame_caller_module_name = get_frame_caller_module_name_or_none()

            # If the caller has a module, append the fully-qualified name of
            # that module to this exception message to improve debuggability.
            if frame_caller_module_name:
                exception_message += (
                    f'via third-party module "{frame_caller_module_name}" ')
            # Else, the caller has *NO* module.

            # Raise this exception message. Note that we intentionally avoid
            # suffixing the exception message by a "." character here. Why?
            # Because Python treats "AttributeError" exceptions as special.
            # Notably, Python appears to actually:
            # 1. Parse apart the messages of these exceptions for the
            #    double-quoted attribute name embedded in these messages.
            # 2. Suffix these messages by a "." character followed by a sentence
            #    suggesting an existing attribute with a similar name to that of
            #    the attribute name previously parsed from these messages.
            #
            # For example, given an erroneous lookup of a non-existent dunder
            # attribute "__nomnom_beartype__", Python expands the exception
            # message raised below into:
            #     AttributeError: Forward reference scope "MuhRef" dunder
            #     attribute "__nomnom_beartype__" not found. Did you mean:
            #     '__name_beartype__'?
            raise AttributeError(f'{exception_message}not found')
        # Else, the caller resides inside the "beartype" package and is thus
        # assumed to be trustworthy. Don't let us down, @beartype! Not again!

        # Forward reference proxy to be returned.
        forwardref_subtype = make_forwardref_indexable_subtype(
            self._scope_name, hint_name)

        # Cache this proxy.
        self[hint_name] = forwardref_subtype

        # Return this proxy.
        return forwardref_subtype
