#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **text label utilities** (i.e., low-level callables creating and
returning human-readable strings describing prominent objects or types, intended
to be embedded in human-readable error messages).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.typing.datatyping import BoolTristate
from beartype._util.utilobject import (
    get_object_name,
    get_object_type_name,
)
from collections.abc import Callable

# ....................{ LABELLERS ~ object                 }....................
#FIXME: Unit test us up, please.
def label_object(
    # Mandatory parameters.
    obj: object,

    # Optional parameters.
    is_color: BoolTristate = False,
    is_context: BoolTristate = None,
) -> str:
    '''
    Human-readable label describing the passed arbitrary object.

    Parameters
    ----------
    obj : object
        Object to be labelled.
    is_color : BoolTristate, default: False
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
        Defaults to :data:`False`.
    is_context : BoolTristate, default: None
        Either:

        * :data:`True`, in which case this label is suffixed by additional
          metadata contextually disambiguating the passed object if that object
          is a callable, including:

          * The line number of the first line declaring that callable in its
            underlying source code module file.
          * The absolute filename of that file.

        * :data:`False`, in which case this label is *not* suffixed by such
          metadata.
        * :data:`None`, in which case this label is conditionally suffixed by
          such metadata only if that callable is a lambda function and thus
          ambiguously lacks any semblance of an innate context.

        Defaults to :data:`None`.

    Returns
    -------
    str
        Human-readable label describing this hintable.
    '''

    # Avoid circular import dependencies.
    from beartype._util.text.utiltextrepr import represent_object

    # If this object is a type, return a label describing this type.
    if isinstance(obj, type):
        return label_type(cls=obj, is_color=is_color)
    # Else, this beartypeable is *NOT* a type.
    #
    # If this object is a callable, return a label describing this callable.
    elif callable(obj):
        return label_callable(
            func=obj,
            is_color=is_color,
            is_context=is_context,
        )
    # Else, this object is neither a type or callable.

    # Fallback to a simplistically heuristic concatenating (in order):
    # * The human-readable kind of this object.
    # * The machine-readable representation of this object.
    return f'{label_object_kind(obj)} {represent_object(obj)}'


def label_object_kind(obj: object) -> str:
    '''
    Human-readable label describing the **kind** (i.e., single concise noun
    synopsizing the category of) of the passed object.

    Parameters
    ----------
    obj : object
        Object to describe the kind of.

    Returns
    -------
    str
        Human-readable label describing the kind of this object.
    '''

    # ....................{ IMPORTS                        }....................
    # Avoid circular import dependencies.
    from beartype._util.func.utilfunctest import (
        is_func_async,
        is_func_async_generator,
        is_func_classmethod,
        is_func_coro,
        is_func_codeobjable,
        is_func_property,
        is_func_staticmethod,
        is_func_sync_generator,
    )
    from beartype._util.func.arg.utilfuncargget import (
        get_func_arg_name_first_or_none)

    # ....................{ LOCALS                         }....................
    # String to be returned, defaulting to a sensible placeholder.
    obj_label = 'object'

    # ....................{ TYPE                           }....................
    # If this object is a pure-Python class, return an appropriate string.
    if isinstance(obj, type):
        obj_label = 'class'
    # Else, this object is *NOT* a pure-Python class.
    #
    # ....................{ CODEOBJABLE                    }....................
    # If this object is (or encapsulates) a pure-Python callable...
    elif is_func_codeobjable(obj):
        # Human-readable prefix describing the exotic nature of this callable if
        # this is callable is exotic (e.g., coroutine or generator factory)
        # suffixed by trailing whitespace *OR* the empty string otherwise.
        func_prefix = ''

        # Human-readable suffix describing the general nature of this callable
        # (e.g., function, method) suffixed by trailing whitespace.
        func_suffix = ''

        # If this object is an asynchronous callable factory...
        if is_func_async(obj):
            # If this object is a coroutine factory, use an appropriate prefix.
            if is_func_coro(obj):
                func_prefix = 'coroutine factory '
            # If this object is an asynchronous generator factory, use an
            # appropriate prefix.
            elif is_func_async_generator(obj):
                func_prefix = 'asynchronous generator factory '
            # Else, this object is an unrecognized kind of asynchronous callable
            # factory. In this case, fallback to a generic prefix.
            #
            # Note that this should *NEVER* occur. Since *ALL* asynchronous
            # callable factories are either coroutine or asynchronous generator
            # factories, one of the above conditional branches should have been
            # entered instead. Nonetheless, preparation prevents disasters.
            else:  # pragma: no cover
                func_prefix = 'asynchronous '
        # Else, this object is a synchronous callable.
        #
        # If this object is an synchronous generator factory, use an appropriate
        # prefix.
        elif is_func_sync_generator(obj):
            func_prefix = 'generator factory '
        # Else, this object is a standard synchronous callable. In this case,
        # avoid prefixing this callable by a leading substring.

        # Name of the first parameter accepted by that callable if any *OR*
        # "None" otherwise (i.e., if that callable is argumentless).
        arg_first_name = get_func_arg_name_first_or_none(
            func=obj,
            # If that callable is a C-based bound method descriptor
            # encapsulating a pure-Python instance or class method, instruct
            # this getter to return the name of the first mandatory flexible
            # parameter accepted by that method. In general, this parameter is
            # semantically ignorable and indeed *MUST* be ignored. In this case,
            # however, this name conveys (marginally) meaningful syntax under
            # the safe assumption that author of that callable adheres to PEP 8
            # community standards and is thus sane rather than insane. Notably,
            # this name is then guaranteed to be either:
            # * "self" if that descriptor encapsulates an instance method.
            # * "cls" if that descriptor encapsulates a class method.
            is_omit_boundmethod_arg_first=False,
        )

        # If this is the canonical first "self" parameter typically accepted by
        # instance methods, assume this to be an instance method.
        #
        # Note that this heuristic fails in uncommon edge cases -- but that
        # that's largely irrelevant here. This function is *ONLY* intended to
        # generate human-readable exception and warning messages. Since this is
        # hardly mission-critical, false positives are reluctantly acceptable.
        if arg_first_name == 'self':
            func_suffix = 'method'
        # Else, this is *NOT* the canonical first "self" parameter.
        #
        # If this is the canonical first "cls" parameter typically accepted by
        # class methods, assume this to be a class method.
        elif arg_first_name == 'cls':
            func_suffix = 'class method'
        # Else, this is neither the canonical first "self" nor "cls" parameter.
        # In this case, assume this to be a non-method callable.
        else:
            func_suffix = 'function'

        # Return the concatenation of these substrings.
        # print(f'func_prefix: {func_prefix}; func_suffix: {func_suffix}')
        obj_label = f'{func_prefix}{func_suffix}'
    # Else, this object is *NOT* a pure-Python callable.
    #
    # ....................{ DESCRIPTOR                     }....................
    # If this object is a C-based uncallable class method descriptor, return an
    # appropriate string.
    elif is_func_classmethod(obj):
        obj_label = 'class method descriptor'
    # Else, this object is *NOT* a C-based uncallable class method descriptor.
    #
    # If this object is a C-based uncallable property method descriptor, return
    # an appropriate string.
    elif is_func_property(obj):
        obj_label = 'property method descriptor'
    # Else, this object is *NOT* a C-based uncallable property method
    # descriptor.
    #
    # If this object is a C-based uncallable static method descriptor, return
    # an appropriate string.
    elif is_func_staticmethod(obj):
        obj_label = 'static method descriptor'
    # Else, this object is *NOT* a C-based uncallable static method descriptor.

    # ....................{ RETURN                         }....................
    # Return this label.
    return obj_label


#FIXME: Unit test us up, please.
def label_object_context(obj: object) -> str:
    '''
    Human-readable label describing the **context** (i.e., absolute filename of
    the module or script physically declaring the passed object *and* the
    1-based line number of the first line declaring this object in this file) of
    this object if this object is either a callable or class declared on-disk
    *or* the empty string otherwise (i.e., if this object is neither a callable
    nor class *or* is either a callable or class declared in-memory).

    Parameters
    ----------
    func : object
        Object to label the context of.

    Returns
    -------
    str
        Human-readable label describing the context of this object.
    '''

    # Defer test-specific imports.
    from beartype._util.utilobject import get_object_filename_or_none
    from beartype._util.module.utilmodget import (
        get_object_module_line_number_begin)

    # Absolute filename of the module or script physically declaring this object
    # if this object was defined on-disk *OR* "None" otherwise (i.e., if this
    # object was defined in-memory).
    obj_filename = get_object_filename_or_none(obj)

    # If this object is defined on-disk...
    if obj_filename:
        # Line number of the first line declaring this object in that file.
        obj_lineno = get_object_module_line_number_begin(obj)

        # Return a string describing the context of this object.
        return f'in file "{obj_filename}" line {obj_lineno}'
    # Else, this object was defined in-memory. In this case, avoid attempting to
    # needlessly contextualize this object.

    # Let's hear it for giving up here and going home. Yeah! Go, @beartype!
    return ''

# ....................{ LABELLERS ~ callable               }....................
#FIXME: Unit test up the "is_context" parameter, which is currently untested.
def label_callable(
    # Mandatory parameters.
    func: Callable,

    # Optional parameters.
    is_color: BoolTristate = False,
    is_context: BoolTristate = None,
) -> str:
    '''
    Human-readable label describing the passed **callable** (e.g., function,
    method, property).

    Parameters
    ----------
    func : Callable
        Callable to be labelled.
    is_color : BoolTristate, default: False
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
        Defaults to :data:`False`.
    is_context : BoolTristate, default: None
        Either:

        * :data:`True`, in which case this label is suffixed by additional
          metadata contextually disambiguating that callable, including:

          * The line number of the first line declaring that callable in its
            underlying source code module file.
          * The absolute filename of that file.

        * :data:`False`, in which case this label is *not* suffixed by such
          metadata.
        * :data:`None`, in which case this label is conditionally suffixed by
          such metadata only if that callable is a lambda function and thus
          ambiguously lacks any semblance of an innate context.

        Defaults to :data:`None`.

    Returns
    -------
    str
        Human-readable label describing this callable.
    '''
    assert callable(func), f'{repr(func)} uncallable.'
    assert isinstance(is_context, bool) or is_context is None, (  # <-- "NoneTypeOr" is unavailable here
        f'{repr(is_context)} not tri-state boolean.')

    # Avoid circular import dependencies.
    from beartype._util.func.arg.utilfuncarglen import (
        get_func_args_flexible_len)
    from beartype._util.func.utilfunccodeobj import get_func_codeobj
    from beartype._util.func.utilfunctest import is_func_lambda
    from beartype._util.text.utiltextansi import color_attr_name

    # Substring prefixing the string to be returned, typically identifying the
    # specialized type of that callable if that callable has a specialized type.
    func_label_prefix = ''

    # Fully-qualified name of that callable, coloured if requested.
    func_label = color_attr_name(
        text=f' {get_object_name(func)}()', is_color=is_color)

    # Substring suffixing the string to be returned, typically contextualizing
    # that callable with respect to its on-disk code module file.
    func_label_suffix = ''

    #FIXME: *HMM.* This branch should almost certainly be folded into the
    #existing label_object_kind() function, which would then dramatically
    #simplify this logic here. Let's do this, yo!
    # If the passed callable is a pure-Python lambda function, that callable
    # has *NO* unique fully-qualified name. In this case, return a string
    # uniquely identifying this lambda from various code object metadata.
    if is_func_lambda(func):
        # Code object underlying this lambda.
        func_codeobj = get_func_codeobj(func)

        # Substring preceding the string to be returned.
        func_label_prefix = (
            f'lambda function accepting '
            f'{get_func_args_flexible_len(func_codeobj)} argument(s)'
        )

        # If the caller failed to request an explicit contextualization, default
        # to contextualizing this lambda function.
        if is_context is None:
            is_context = True
        # Else, the caller requested an explicit contextualization. In this
        # case, preserve that contextualization as is.
    # Else, the passed callable is *NOT* a pure-Python lambda function and thus
    # has a unique fully-qualified name. In this case, prefix this label with a
    # substring describing the kind of that callable.
    else:
        func_label_prefix = label_object_kind(func)

    # If contextualizing that callable, just do it already. Go, @beartype! Go!
    if is_context:
        func_label_suffix = f' {label_object_context(func)}'
    # Else, we are *NOT* contextualizing that callable.

    # Return that prefix followed by the fully-qualified name of that callable.
    return f'{func_label_prefix}{func_label}{func_label_suffix}'

# ....................{ LABELLERS ~ exception              }....................
def label_exception(exception: Exception) -> str:
    '''
    Human-readable label describing the passed exception.

    Caveats
    -------
    **The label returned by this function does not describe the traceback
    originating this exception.** To do so, consider calling the standard
    :func:`traceback.format_exc` function instead.

    Parameters
    ----------
    exception : Exception
        Exception to be labelled.

    Returns
    -------
    str
        Human-readable label describing this exception.
    '''
    assert isinstance(exception, Exception), (
        f'{repr(exception)} not exception.')

    # Return the fully-qualified name of the class of this exception followed by
    # this exception's message.
    return f'{get_object_type_name(exception)}: {str(exception)}'

# ....................{ LABELLERS ~ pith                   }....................
def label_pith_value(
    # Mandatory parameters.
    pith: object,

    # Optional parameters.
    is_color: BoolTristate = False,
) -> str:
    '''
    Human-readable label describing the passed value of the **current pith**
    (i.e., arbitrary object violating the current type check) *not* suffixed by
    delimiting whitespace.

    Parameters
    ----------
    pith : object
        Arbitrary object violating the current type check.
    is_color : BoolTristate
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
        Defaults to :data:`False`.

    Returns
    -------
    str
        Human-readable label describing this pith value.
    '''

    # Avoid circular import dependencies.
    from beartype._util.text.utiltextansi import color_pith
    from beartype._util.text.utiltextrepr import represent_object

    # Glory be to the one liner that you are about to read.
    return color_pith(text=represent_object(pith), is_color=is_color)

# ....................{ LABELLERS ~ type                   }....................
def label_type(
    # Mandatory parameters.
    cls: type,

    # Optional parameters.
    is_color: BoolTristate = False,
) -> str:
    '''
    Human-readable label describing the passed class.

    Parameters
    ----------
    cls : type
        Class to be labelled.
    is_color : BoolTristate, optional
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
        Defaults to :data:`False`.

    Returns
    -------
    str
        Human-readable label describing this class.
    '''
    assert isinstance(cls, type), f'{repr(cls)} not class.'

    # Avoid circular import dependencies.
    from beartype._util.cls.utilclstest import is_type_builtin
    from beartype._util.hint.pep.proposal.pep544 import (
        is_hint_pep544_protocol)
    from beartype._util.hint.pep.proposal.pep484585.generic.pep484585gentest import (
        is_hint_pep484585_generic_subbed)
    from beartype._util.text.utiltextansi import color_type

    # Label to be returned.
    classname: str = None  # type: ignore[assignment]

    # If this type is a PEP 484- or 585-compliant subscripted generic, the best
    # label is simply the machine-readable representation of this generic (e.g.,
    # the string "MuhGeneric[str]" given the generic type declaration "class
    # MuhGeneric[T](typing.Generic[T]):"). Alternative labels defined below fail
    # to include the child hint subscripting this subscripted generic.
    if is_hint_pep484585_generic_subbed(cls):  # pyright: ignore
        classname = repr(cls)
    # Else, this type is *NOT* a PEP 484- or 585-compliant subscripted generic.
    # In this case...
    else:
        # Fully-qualified name of this type.
        classname = get_object_type_name(cls)
        # print(f'cls {cls} classname: {classname}')

        # If this name contains *NO* periods, this class is actually a builtin
        # type (e.g., "list"). Since builtin types are well-known and thus
        # self-explanatory, this name requires no additional labelling. In this
        # case, return this name as is.
        if '.' not in classname:
            pass
        # Else, this name contains one or more periods but could still be a
        # builtin indirectly accessed via the standard "builtins" module.
        #
        # If this name is that of a builtin type uselessly prefixed by the name
        # of the module declaring all builtin types (e.g., "builtins.list"),
        # reduce this name to the unqualified basename of this type (e.g.,
        # "list").
        elif is_type_builtin(cls):
            classname = cls.__name__
        # Else, this is a non-builtin class. Non-builtin classes are *NOT*
        # well-known and thus benefit from additional labelling.
        #
        # If this class is a PEP 544-compliant protocol supporting structural
        # subtyping, label this protocol.
        elif is_hint_pep544_protocol(cls):
            # print(f'cls {cls} is protocol!')
            classname = f'<protocol "{classname}">'
        # Else if this class is a standard abstract base class (ABC) defined by
        # a standard submodule also known to support structural subtyping (e.g.,
        # "collections.abc.Hashable", "contextlib.AbstractContextManager"),
        # label this ABC as a protocol.
        #
        # Note that user-defined ABCs do *NOT* generally support structural
        # subtyping. Doing so requires esoteric knowledge of undocumented and
        # mostly private "abc.ABCMeta" metaclass internals unlikely to be
        # implemented by third-party developers. Thanks to the lack of both
        # publicity and standardization, there exists *NO* general-purpose means
        # of detecting whether an arbitrary class supports structural subtyping.
        elif (
            classname.startswith('collections.abc.') or
            classname.startswith('contextlib.')
        ):
            classname = f'<protocol ABC "{classname}">'
        # Else, this is a standard class. In this case, label this class as such.
        else:
            classname = f'<class "{classname}">'

    # Return this labelled classname, possibly coloured.
    return color_type(text=classname, is_color=is_color)


#FIXME: Silly, honestly. Is this still called anywhere? Simplify to trivial
#calls to the vastly superior label_type() function defined above, please.
def label_object_type(obj: object) -> str:
    '''
    Human-readable label describing the class of the passed object.

    Parameters
    ----------
    obj : object
        Object whose class is to be labelled.

    Returns
    -------
    str
        Human-readable label describing the class of this object.
    '''

    # Tell me why, why, why I curse the sky! ...no, srsly.
    return label_type(type(obj))
