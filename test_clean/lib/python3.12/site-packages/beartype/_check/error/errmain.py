#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype exception getters** (i.e., high-level callables creating and
returning human-readable exceptions, called by various runtime type-checkers
published by :mod:`beartype` when an arbitrary object violates a type hint).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
#FIXME: [ACCESS] Generalizing the "random_int" concept (i.e., the optional
#"random_int" parameter accepted by the get_func_pith_violation() function) that
#enables O(1) exception handling to containers that do *NOT* provide efficient
#random access like mappings and sets will be highly non-trivial. While there
#exist a number of alternative means of implementing that generalization, the
#most reasonable *BY FAR* is probably to:
#
#* Embed additional assignment expressions in the type-checking tests generated
#  by the make_func_pith_code() function that uniquely store the value of
#  each item, key, or value returned by each access of a non-indexable container
#  iterator into a new unique local variable. Note this unavoidably requires:
#  * Adding a new index to the "hint_curr_meta" tuples internally created by
#    that function -- named, say, "_HINT_META_INDEX_ITERATOR_NAME". The value
#    of the tuple item at this index should either be:
#    * If the currently iterated type hint is a non-indexable container, the
#      name of the new unique local variable assigned to by this assignment
#      expression whose value is obtained from the iterator cached for that
#      container.
#    * Else, "None".
#    Actually... hmm. Perhaps we only need a new local variable
#    "iterator_nonsequence_names" whose value is a cached "FixedList" of
#    sufficiently large size (so, "FIXED_LIST_SIZE_MEDIUM"?). We could then simply
#    iteratively insert the names of the wrapper-specific new unique local
#    variables into this list.
#    Actually... *WAIT.* Is all we need a single counter initialized to, say:
#        iterators_nonsequence_len = 0
#    We then both use that counter to:
#    * Uniquify the names of these wrapper-specific new unique local variables
#      during iteration over type hints.
#    * Trivially generate a code snippet passing a list of these names to the
#      "iterators_nonsequence" parameter of get_func_pith_violation() function
#      after iteration over type hints.
#    Right. That looks like The Way, doesn't it? This would seem to be quite a
#    bit easier than we'd initially thought, which is always nice. Oi!
#  * Python >= 3.8, but that's largely fine. Python 3.6 and 3.7 are
#    increasingly obsolete in 2021.
#* Add a new optional "iterators_nonsequence" parameter to the
#  get_func_pith_violation() function, accepting either:
#  * If the current parameter or return of the parent wrapper function was
#    annotated with one or more non-indexable container type hints, a *LIST* of
#    the *VALUES* of all unique local variables assigned to by assignment
#    expressions in that parent wrapper function. These values were obtained
#    from the iterators cached for those containers. To enable these exception
#    handlers to efficiently treat this list like a FIFO stack (e.g., with the
#    list.pop() method), this list should be sorted in the reverse order that
#    these assignment expressions are defined in.
#* Refactor exception handlers to then preferentially retrieve non-indexable
#  container items in O(1) time from this stack rather than simply iterating
#  over all container items in O(n) brute-force time. Obviously, extreme care
#  must be taken here to ensure that this exception handling algorithm visits
#  containers in the exact same order as visited by our testing algorithm.
#FIXME: *UHH.* I honestly have *NO* idea what any of the above is on about. It's
#likely we overthought the above commentary to extreme overkill. Notably,
#@beartype does (in fact) now deeply type-check both maps and sets. Works great,
#actually. No need for any of the above insanity, either. Let's re-read this
#and, if bollocks, excise all of the above. Overkill, thy name is that "FIXME:".

#FIXME: [COLOR] The call to the strip_text_ansi() function below is inefficient
#and thus non-ideal. Since efficiency isn't a pressing concern in an exception
#raiser, this is more a matter of design purity than anything. Still, it would
#be preferable to avoid embedding ANSI escape sequences when the user requests
#that rather than forcibly stripping those sequences out after the fact via an
#inefficient regex. To do so, we'll want to:
#* Augment the color_*() family of functions with a mandatory "conf:
#  BeartypeConf" parameter.
#* Pass that parameter to *EVERY* call to one of those functions.
#* Refactor those functions to respect that parameter. The ideal means of
#  doing so would probably be define in the
#  "beartype._util.text.utiltextansi" submodule:
#  * A new "_BeartypeTheme" dataclass mapping from style names to format
#    strings embedding the ANSI escape sequences styling those styles.
#  * A new pair of private "_THEME_MONOCHROME" and "_THEME_PRISMATIC"
#    instances of that dataclass. The values of the "_THEME_MONOCHROME"
#    dictionary should all just be the default format string: e.g.,
#    _THEME_MONOCHROME = _BeartypeTheme(
#        format_error='{text}',
#        ...
#    )
#
#    _THEME_PRISMATIC = _BeartypeTheme(
#        format_error=f'{_STYLE_BOLD}{_COLOUR_RED}{{text}}{_COLOUR_RESET}',
#        ...
#    )
#  * A new "_THEME_DEFAULT" instance of that dataclass conditionally defined
#    as either "_THEME_MONOCHROME" or "_THEME_PRISMATIC" depending on
#    whether stdout is attached to a TTY or not. Alternately, to avoid
#    performing that somewhat expensive logic at module scope (and thus on
#    initial beartype importation), it might be preferable to instead define
#    a new cached private getter resembling:
#
#    @callable_cached
#    def _get_theme_default() -> _BeartypeTheme:
#        return (
#            _THEME_PRISMATIC
#            if is_stdout_terminal() else
#            _THEME_MONOCHROME
#        )

# ....................{ IMPORTS                            }....................
from beartype.meta import URL_ISSUES
from beartype.roar._roarexc import (
    _BeartypeCallHintPepRaiseDesynchronizationException,
    _BeartypeCallHintPepRaiseException,
)
from beartype.typing import Optional
from beartype._check.convert.convmain import sanify_hint_any
from beartype._check.error.errcause import ViolationCause
from beartype._check.metadata.metacheck import BeartypeCheckMeta
from beartype._conf.confmain import BeartypeConf
from beartype._conf.confcommon import BEARTYPE_CONF_DEFAULT
from beartype._conf.confenum import BeartypeViolationVerbosity
from beartype._data.func.datafuncarg import ARG_NAME_RETURN
from beartype._data.typing.datatypingport import Hint
from beartype._data.typing.datatyping import (
    TypeException,
    TypeStack,
)
from beartype._util.text.utiltextansi import (
    color_hint,
    strip_str_ansi,
)
from beartype._util.text.utiltextmunge import (
    suffix_str_unless_suffixed,
    uppercase_str_char_first,
)
from beartype._util.text.utiltextprefix import (
    prefix_callable_return_value,
    prefix_callable_arg_value,
    prefix_pith_value,
)
from beartype._util.text.utiltextrepr import represent_object
from beartype._data.kind.datakindiota import SENTINEL
from collections.abc import Callable as CallableABC

# ....................{ GETTERS                            }....................
def get_func_pith_violation(
    # Mandatory parameters.
    check_meta: BeartypeCheckMeta,
    pith_name: str,
    pith_value: object,

    # Optional keyword parameters.
    **kwargs
) -> Exception:
    '''
    Human-readable exception detailing the failure of the parameter with the
    passed name *or* return if this name is the magic string ``return`` of the
    passed decorated function fails to satisfy the type hint annotating this
    parameter or return.

    Parameters
    ----------
    check_meta : BeartypeCheckMeta
        **Beartype type-check call metadata** (i.e., object encapsulating *all*
        metadata required by the current call to the wrapper function
        type-checking a :func:`beartype.beartype`-decorated callable).
    pith_name : str
        Either:

        * If the object failing to satisfy this hint is a passed parameter, the
          name of this parameter.
        * Else, the magic string ``"return"`` implying this object to be the
          value returned from this callable.
    pith_value : object
        Passed parameter or returned value violating this hint.

    All remaining keyword parameters are passed as is to the
    :func:`.get_hint_object_violation` getter.

    Returns
    -------
    Exception
        Human-readable exception detailing the failure of this parameter or
        return to satisfy the type hint annotating this parameter or return.
        This is guaranteed to be an instance of either:

        * If this is a parameter, :attr:`.BeartypeConf.violation_param_type`.
        * If this is a return, :attr:`.BeartypeConf.violation_return_type`.

    Raises
    ------
    All exceptions raised by the lower-level :func:`.get_hint_object_violation`
    getter as well as:

    _BeartypeCallHintPepRaiseException
        If the parameter or return with the passed name is unannotated.

    See Also
    --------
    :func:`.get_hint_object_violation`
        Further details.
    '''
    assert isinstance(check_meta, BeartypeCheckMeta), (
        f'{repr(check_meta)} not type-checking call metadata.')
    assert isinstance(pith_name, str), f'{repr(pith_name)} not string.'

    # Hint annotating this parameter or return if this parameter or return is
    # annotated *OR* the placeholder sentinel otherwise (i.e., if this parameter
    # or return is unannotated).
    hint = check_meta.func_annotations.get(pith_name, SENTINEL)

    # If this parameter or return is unannotated, raise an exception.
    #
    # Note that this should *NEVER* occur, as the caller guarantees this
    # parameter or return to be annotated. However, since malicious callers
    # *COULD* deface the "__annotations__" dunder dictionary without our
    # knowledge or permission, precautions are warranted.
    if hint is SENTINEL:
        raise _BeartypeCallHintPepRaiseException(
            f'{repr(check_meta.func)} parameter "{pith_name}" unannotated '
            f'(or originally annotated but since deleted) in '
            f'"__annotations__" dunder dictionary:\n'
            f'{repr(check_meta.func_annotations)}'
        )
    # Else, this parameter or return is annotated.

    # Defer to this lower-level violation factory.
    return get_hint_object_violation(
        cls_stack=check_meta.cls_stack,
        conf=check_meta.conf,
        func=check_meta.func,
        hint=hint,  # type: ignore[arg-type]
        obj=pith_value,
        pith_name=pith_name,
        **kwargs
    )


def get_hint_object_violation(
    # Mandatory parameters.
    obj: object,
    hint: Hint,
    conf: BeartypeConf,

    # Optional parameters.
    func: Optional[CallableABC] = None,
    cls_stack: TypeStack = None,
    exception_prefix: Optional[str] = None,
    pith_name: Optional[str] = None,
    random_int: Optional[int] = None,
) -> Exception:
    '''
    Human-readable exception detailing the failure of the passed object to
    satisfy the passed type hint under the passed beartype configuration.

    This function intentionally returns rather than raises this exception. Why?
    Because the ignorable stack frame encapsulating the call of the parent
    type-checking wrapper function generated by the :mod:`beartype.beartype`
    decorator complicates inspection of type-checking violations in tracebacks
    (especially from :mod:`pytest`, which unhelpfully recapitulates the full
    definition of this function including this docstring in those tracebacks).
    Instead, that wrapper function raises this exception directly from itself.

    Design
    ------
    The :mod:`beartype` package actually implements two parallel PEP-compliant
    runtime type-checkers, each complementing the other by providing
    functionality unsuited for the other. These are:

    * The :mod:`beartype._check.code` submodule, dynamically generating
      optimized PEP-compliant runtime type-checking code embedded in the body
      of the wrapper function wrapping the decorated callable. For both
      efficiency and maintainability, that code only tests whether or not a
      parameter passed to that callable or value returned from that callable
      satisfies a PEP-compliant annotation on that callable; that code does
      *not* raise human-readable exceptions in the event that value fails to
      satisfy that annotation. Instead, that code defers to...
    * This function, performing unoptimized PEP-compliant runtime type-checking
      generically applicable to all wrapper functions. The aforementioned
      code calls this function only in the event that value fails to satisfy
      that annotation, in which case this function then returns a human-readable
      exception after discovering the underlying cause of this type failure by
      recursively traversing that value and annotation. While efficiency is the
      foremost focus of this package, efficiency is irrelevant during exception
      handling -- which typically only occurs under infrequent edge cases.
      Likewise, while raising this exception *would* technically be feasible
      from the aforementioned code, doing so proved sufficiently non-trivial,
      fragile, and ultimately unmaintainable to warrant offloading to this
      function universally callable from all wrapper functions.

    Parameters
    ----------
    obj : object
        Arbitrary object to be type-checked against this type hint.
    hint : Hint
        Type hint against which to type-check this object.
    conf : BeartypeConf
        **Beartype configuration** (i.e., self-caching dataclass encapsulating
        all flags, options, settings, and other metadata configuring the
        validation of this object against this type hint).
    func : Optional[CallableABC]
        Either:

        * If this violation originates from a decorated callable, that
          callable.
        * Else, :data:`None`.

        Defaults to :data:`None`.
    cls_stack : TypeStack, optional
        **Type stack** (i.e., either a tuple of the one or more
        :func:`beartype.beartype`-decorated classes lexically containing the
        class variable or method annotated by this hint *or* :data:`None`).
        Defaults to :data:`None`.
    exception_prefix : Optional[str]
        Either:

        * If the caller prefers specifying an explicit human-readable label
          prefixing the representation of this object in the exception message,
          that labal.
        * Else, :data:`None`. In this case, this getter automatically
          synthesizes this label from the other passed parameters that are
          required to be non-:data:`None`. If any such parameter is
          :data:`None`, an exception is raised. These parameters include:

          * The passed ``func`` parameter, required to be non-:data:`None`.
          * The passed ``pith_name`` parameter, required to be non-:data:`None`.
    pith_name : Optional[str]
        Either:

        * If this hint annotates a parameter of some callable, the name of that
          parameter.
        * If this hint annotates the return of some callable, ``"return"``.
        * Else, :data:`None`.

        Defaults to :data:`None`.
    random_int: Optional[int], optional
        **Pseudo-random integer** (i.e., unsigned 32-bit integer
        pseudo-randomly generated by the parent :func:`beartype.beartype`
        wrapper function in type-checking randomly indexed container items by
        the current call to that function) if that function generated such an
        integer *or* :data:`None` otherwise (i.e., if that function generated
        *no* such integer). Note that this parameter critically governs whether
        this exception handler runs in constant or linear time. Specifically, if
        this parameter is:

        * An integer, this handler runs in **constant time.** Since there exists
          a one-to-one relation between this integer and the random container
          item(s) type-checked by the parent :func:`beartype.beartype` wrapper
          function, receiving this integer enables this handler to efficiently
          re-type-check the same random container item(s) type-checked by the
          parent in constant time rather type-checking all container items in
          linear time.
        * :data:`None`, this handler runs in **linear time.**

        Defaults to :data:`None`, implying this exception handler runs in linear
        time by default.

    Returns
    -------
    Exception
        Human-readable exception detailing the failure of this object to satisfy
        the type hint. This is guaranteed to be an instance of either:

        * If this is a parameter, :attr:`.BeartypeConf.violation_param_type`.
        * If this is a return, :attr:`.BeartypeConf.violation_return_type`.
        * Else, :attr:`.BeartypeConf.violation_door_type`.

    Raises
    ------
    BeartypeDecorHintPepException
        If the type hint annotating this object is *not* PEP-compliant.
    _BeartypeCallHintPepRaiseException
        If all three of the ``exception_prefix``,``func``, and ``pith_name``
        parameters are :data:`None`.
    _BeartypeCallHintPepRaiseDesynchronizationException
        If this pith actually satisfies this hint, implying either:

        * The parent wrapper function generated by the :mod:`beartype.beartype`
          decorator type-checking this pith triggered a false negative by
          erroneously misdetecting this pith as failing this type check.
        * This child helper function re-type-checking this pith triggered a
          false positive by erroneously misdetecting this pith as satisfying
          this type check when in fact this pith fails to do so.
    '''
    # print('''get_hint_object_violation(
    #     func={!r},
    #     hint={!r},
    #     conf={!r},
    #     pith_name={!r},
    #     obj={!r},
    # )'''.format(func, hint, conf, pith_name, obj))

    # ....................{ LOCALS                         }....................
    # Type of violation to be raised.
    exception_cls: TypeException = None  # type: ignore[assignment]

    # If the caller passed *NO* parameter name, the passed object is neither a
    # parameter nor return of a decorated callable. By elimination, this object
    # *MUST* have been directly passed to the beartype.door.die_if_unbearable()
    # type-checker. In this case...
    if pith_name is None:
        # If the caller also passed *NO* exception prefix, raise an exception.
        if exception_prefix is None:
            raise _BeartypeCallHintPepRaiseException(
                'get_hint_object_violation() passed neither '
                '"exception_prefix" nor "pith_name" parameters.'
            )
        # Else, the caller passed an exception prefix.

        # Default the exception class appropriately.
        exception_cls = conf.violation_door_type

        # Suffix this exception prefix with an additional noun for disambiguity.
        exception_prefix = (
            f'{exception_prefix}value '
            f'{prefix_pith_value(pith=obj, is_color=conf.is_color)}'
        )
    # Else, the caller passed a parameter name. In this case...
    else:
        # If the caller also passed an exception prefix, raise an exception.
        if exception_prefix is not None:
            raise _BeartypeCallHintPepRaiseException(
                'get_hint_object_violation() passed both '
                '"exception_prefix" and "pith_name" parameters.'
            )
        # Else, the caller passed *NO* exception prefix.

        # If the name of this parameter is the magic string implying the passed
        # object to be a return value...
        if pith_name == ARG_NAME_RETURN:
            # Default these exception locals appropriately
            exception_cls = conf.violation_return_type
            exception_prefix = prefix_callable_return_value(
                func=func,  # type: ignore[arg-type]
                return_value=obj,
                is_color=conf.is_color,
            )
        # Else, the passed object is a parameter. In this case...
        else:
            # Default these exception locals appropriately
            exception_cls = conf.violation_param_type
            exception_prefix = prefix_callable_arg_value(
                func=func,  # type: ignore[arg-type]
                arg_name=pith_name,
                arg_value=obj,
                is_color=conf.is_color,
            )

    # Uppercase the first character of this violation prefix for readability.
    exception_prefix = uppercase_str_char_first(exception_prefix)

    # Metadata encapsulating the sanification of this child hint.
    hint_sane = sanify_hint_any(
        hint=hint,
        cls_stack=cls_stack,
        conf=conf,
        pith_name=pith_name,
        exception_prefix=exception_prefix,
    )

    # ....................{ CAUSE                          }....................
    # Cause describing the failure of this pith to satisfy this hint.
    violation_cause = ViolationCause(
        cause_indent='',
        cls_stack=cls_stack,
        conf=conf,
        exception_prefix=exception_prefix,
        func=func,
        hint_sane=hint_sane,
        pith=obj,
        pith_name=pith_name,
        random_int=random_int,
    ).find_cause()

    # If this pith satisfies this hint, *SOMETHING HAS GONE TERRIBLY AWRY.*
    #
    # In theory, this should never happen, as the parent wrapper function
    # performing type checking should *ONLY* call this child helper function
    # when this pith does *NOT* satisfy this hint. In this case, raise an
    # exception encouraging the end user to submit an upstream issue with us.
    if not violation_cause.cause_str_or_none:
        pith_value_repr = represent_object(
            obj=obj, max_len=_CAUSE_TRIM_OBJECT_REPR_MAX_LEN)
        raise _BeartypeCallHintPepRaiseDesynchronizationException(
            f'{exception_prefix}violates type hint {repr(hint)}, '
            f'but violation factory get_hint_object_violation() '
            f'erroneously suggests this object satisfies this hint. '
            f'Please report this desynchronization failure to '
            f'the beartype issue tracker ({URL_ISSUES}) with '
            f'the accompanying exception traceback and '
            f'the representation of this object:\n'
            f'    {pith_value_repr}\n'
            f'The bear groans in disappointment. If you feel similarly, '
            f'know that you are not alone.'
        )
    # Else, this pith violates this hint as expected and as required for sanity.

    # This failure suffixed by a period if *NOT* yet suffixed by a period.
    violation_cause_suffixed = suffix_str_unless_suffixed(
        text=violation_cause.cause_str_or_none, suffix='.')

    # List of the one or more culprits responsible for this violation,
    # initialized to the passed parameter or returned value violating this hint.
    violation_culprits = [obj,]

    # If the actual object directly responsible for this violation is *NOT* the
    # passed parameter or returned value indirectly violating this hint, then
    # the latter is almost certainly a container transitively containing the
    # former as an item. In this case, add this item to this list as well.
    if obj is not violation_cause.pith:
        violation_culprits.append(violation_cause.pith)
    # Else, the actual object directly responsible for this violation is the
    # passed parameter or returned value indirectly violating this hint. In this
    # case, avoid adding duplicate items to this list.

    # ....................{ VERBOSITY                      }....................
    # Violation verbosity, localized for negligible efficiency. *vomits*
    violation_verbosity = conf.violation_verbosity

    # Machine-readable representation of this hint embellished with colour.
    hint_repr = f'{color_hint(text=repr(hint), is_color=conf.is_color)}'

    # Dictionary mapping from each possibly violation verbosity to a
    # corresponding substring prepending this exception message.
    VIOLATION_VERBOSITY_TO_PREFIX = {
        BeartypeViolationVerbosity.MINIMAL: (
            f'{exception_prefix}expected to be of type {hint_repr}'),
        BeartypeViolationVerbosity.DEFAULT: (
            f'{exception_prefix}violates type hint {hint_repr}'),
    }
    VIOLATION_VERBOSITY_TO_PREFIX[BeartypeViolationVerbosity.MAXIMAL] = (  # <-- alias!
        VIOLATION_VERBOSITY_TO_PREFIX[BeartypeViolationVerbosity.DEFAULT])

    # Dictionary mapping from each possibly violation verbosity to a
    # corresponding substring embedded in the middle of this exception message.
    VIOLATION_VERBOSITY_TO_INFIX = {
        BeartypeViolationVerbosity.MINIMAL: '',
        BeartypeViolationVerbosity.DEFAULT: '',
        BeartypeViolationVerbosity.MAXIMAL: (
            # If this configuration is the default configuration, avoid
            # needlessly representing this default configuration.
            ''
            if conf == BEARTYPE_CONF_DEFAULT else
            # Else, this configuration is *NOT* the default configuration. In
            # this case, append the machine-readable representation of this
            # non-default configuration to this exception message for
            # disambiguity and clarity.
            f' under non-default configuration {repr(conf)}'
        ),
    }

    # Dictionary mapping from each possibly violation verbosity to a
    # corresponding substring appending this exception message.
    VIOLATION_VERBOSITY_TO_SUFFIX = {
        BeartypeViolationVerbosity.MINIMAL: '.',
        BeartypeViolationVerbosity.DEFAULT: f', as {violation_cause_suffixed}',
    }
    VIOLATION_VERBOSITY_TO_SUFFIX[BeartypeViolationVerbosity.MAXIMAL] = (  # <-- alias!
        VIOLATION_VERBOSITY_TO_SUFFIX[BeartypeViolationVerbosity.DEFAULT])

    # ....................{ EXCEPTION                      }....................
    # Human-readable violation message to be raised.
    exception_message = (
        f'{VIOLATION_VERBOSITY_TO_PREFIX[violation_verbosity]}'
        f'{VIOLATION_VERBOSITY_TO_INFIX[violation_verbosity]}'
        f'{VIOLATION_VERBOSITY_TO_SUFFIX[violation_verbosity]}'
    )

    #FIXME: In theory, this should no longer be needed. Consider:
    #* Refactoring all instances of "is_color=True" throughout this subpackage
    #  to instead read "is_color=cause.conf.is_color".
    #* Refactoring all calls to the represent_pith() function throughout this
    #  subpackage to additionally pass a new optional
    #  "is_color=cause.conf.is_color" parameter.
    #* Refactoring this call away.
    #* Validating with unit tests that violation messages contain *NO* ANSI when
    #  configured such that "BeartypeConf(is_color=False)".
    # Strip all ANSI escape sequences from this message if requested by this
    # external user-defined configuration.
    exception_message = strip_str_ansi(
        text=exception_message, is_color=conf.is_color)

    # Exception of the desired class embedding this cause. By default, attempt
    # to pass @beartype-specific parameters to this exception subclass.
    try:
        exception = exception_cls(  # type: ignore[call-arg]
            message=exception_message,  # pyright: ignore
            culprits=tuple(violation_culprits),  # pyright: ignore
        )
    # If this exception subclass fails to support @beartype-specific parameters,
    # fallback to the standard exception idiom of a positionally passed message.
    except TypeError:
        exception = exception_cls(exception_message)

    # Return this exception to the @beartype-generated type-checking wrapper
    # (which directly calls this function), which will then squelch the
    # ignorable stack frame encapsulating that call to this function by raising
    # this exception directly from that wrapper.
    return exception

# ....................{ PRIVATE ~ constants                }....................
# Assuming a line length of 80 characters, this magic number truncates
# arbitrary object representations to 100 lines (i.e., 8000/80), which seems
# more than reasonable and (possibly) not overly excessive.
_CAUSE_TRIM_OBJECT_REPR_MAX_LEN = 8000
'''
Maximum length of arbitrary object representations suffixing human-readable
strings returned by the :func:`_find_cause` getter function, intended to
be sufficiently long to assist in identifying type-check failures but not so
excessively long as to prevent human-readability.
'''
