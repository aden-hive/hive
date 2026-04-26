#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype :pep:`484` and :pep:`585` **type-checking expression snippets** (i.e.,
triple-quoted pure-Python string constants formatted and concatenated together
to dynamically generate boolean expressions type-checking arbitrary objects
against :pep:`484`- and :pep:`585`-compliant type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.code.datacodename import VAR_NAME_RANDOM_INT
from beartype._data.typing.datatyping import CallableStrFormat

# ....................{ CODE ~ container : (reiterable|seq)}....................
CODE_PEP484585_REITERABLE_OR_SEQUENCE = '''(
{indent_curr}    # True only if this pith is of this container type *AND*...
{indent_curr}    isinstance({pith_curr_assign_expr}, {hint_curr_expr}) and
{indent_curr}    # True only if either this container is empty *OR* this container
{indent_curr}    # is non-empty and the selected item satisfies this hint.
{indent_curr}    (not len({pith_curr_var_name}) or {hint_child_placeholder})
{indent_curr})'''
'''
:pep:`484`- and :pep:`585`-compliant code snippet generically type-checking the
current pith against *any* arbitrary kind of single-argument standard
container type hint.

Caveats
-------
Note that, in the test implemented in the code above:

.. code-block:: python

    (not len({pith_curr_var_name}) or {hint_child_placeholder})

...the call to the :func:`len` builtin *cannot* be optimized away to simply:

.. code-block:: python

    (not {pith_curr_var_name} or {hint_child_placeholder})

See :data:`.CODE_PEP484585_QUASIITERABLE` for further details.
'''


CODE_PEP484585_REITERABLE_PITH_CHILD_EXPR = (
    '''next(iter({pith_curr_var_name}))''')
'''
:pep:`484`- and :pep:`585`-compliant Python expression efficiently yielding the
first item of the current reiterable pith.
'''


CODE_PEP484585_SEQUENCE_PITH_CHILD_EXPR = (
    f'''{{pith_curr_var_name}}[{VAR_NAME_RANDOM_INT} % len({{pith_curr_var_name}})]''')
'''
:pep:`484`- and :pep:`585`-compliant Python expression efficiently yielding the
value of a randomly indexed item of the current sequence pith.
'''

# ....................{ CODE ~ container : collection      }....................
#FIXME: Actually use us up, please.
CODE_PEP484585_COLLECTION = '''(
{indent_curr}    # True only if this pith is of this collection type *AND*...
{indent_curr}    isinstance({pith_curr_assign_expr}, {hint_curr_expr}) and
{indent_curr}    # True only if either this container is empty *OR*...
{indent_curr}    (not len({pith_curr_var_name}) or (
{indent_curr}         # If this collection is a non-empty sequence, localize
{indent_curr}         # a pseudo-random item of this sequence;
{indent_curr}         (isinstance({pith_curr_var_name}, {sequence_abc_expr}) and
{indent_curr}          ({{pith_child_var_name}} := {CODE_PEP484585_SEQUENCE_PITH_CHILD_EXPR}) is {{pith_child_var_name}}) or
{indent_curr}         # Else, this collection *MUST* by elimination be a non-empty,
{indent_curr}         # Reiterable. Localize the first item of this reiterable.
{indent_curr}         ({{pith_child_var_name}} := {CODE_PEP484585_REITERABLE_PITH_CHILD_EXPR}) is {{pith_child_var_name}}
{indent_curr}     # True only if this item satisfies this hint.
{indent_curr}     ) and {hint_child_placeholder}
{indent_curr}    )
{indent_curr})'''
'''
:pep:`484`- and :pep:`585`-compliant code snippet generically type-checking the
current pith against a **collection type hint** (i.e., either a
:pep:`484`-compliant ``typing.Collection[...]`` type hint *or* a
:pep:`585`-compliant ``collections.abc.Collection[...]`` type hint).

Caveats
-------
Note that, in the test implemented in the code above:

.. code-block:: python

    not len({{pith_curr_var_name}}) or ((

...the call to the :func:`len` builtin *cannot* be optimized away to simply:

.. code-block:: python

    not {{pith_curr_var_name}} or ((

See :data:`.CODE_PEP484585_QUASIITERABLE` for further details.
'''

# ....................{ CODE ~ container : quasiiterable   }....................
CODE_PEP484585_QUASIITERABLE = f'''(
{{indent_curr}}    # True only if this pith is of this iterable type *AND*...
{{indent_curr}}    isinstance({{pith_curr_assign_expr}}, {{hint_curr_expr}}) and
{{indent_curr}}    # True only if either this iterable is not a collection *OR*...
{{indent_curr}}    # Iterables that are *NOT* collections are *NOT* safely
{{indent_curr}}    # reiterable at runtime. Silently assume all items of this
{{indent_curr}}    # iterable to deeply satisfy this hint. It is what it is.
{{indent_curr}}    (not isinstance({{pith_curr_var_name}}, {{collection_abc_expr}}) or
{{indent_curr}}     # This iterable is an empty collection *OR*...
{{indent_curr}}     not len({{pith_curr_var_name}}) or ((
{{indent_curr}}        # If this non-empty collection is a sequence, localize a
{{indent_curr}}        # pseudo-random item of this sequence;
{{indent_curr}}        (
{{indent_curr}}            isinstance({{pith_curr_var_name}}, {{sequence_abc_expr}}) and
{{indent_curr}}            ({{pith_child_var_name}} := {CODE_PEP484585_SEQUENCE_PITH_CHILD_EXPR}) is {{pith_child_var_name}}
{{indent_curr}}        # Else, this non-empty collection *MUST* be reiterable. In this
{{indent_curr}}        # case, localize the first item of this reiterable;
{{indent_curr}}        ) or ({{pith_child_var_name}} := {CODE_PEP484585_REITERABLE_PITH_CHILD_EXPR}) is {{pith_child_var_name}}
{{indent_curr}}     # True only if this item satisfies this hint.
{{indent_curr}}     ) and {{hint_child_placeholder}})
{{indent_curr}}    )
{{indent_curr}})'''
'''
:pep:`484`- and :pep:`585`-compliant code snippet generically type-checking the
current pith against an **quasiiterable type hint** (i.e., either a
:pep:`484`-compliant ``typing.Iterable[...]`` type hint *or* a
:pep:`585`-compliant ``collections.abc.Iterable[...]`` type hint matching a
potentially unsafe container that is *not* guaranteed to be safely reiterable).

Caveats
-------
Note that, in the test implemented in the code above:

.. code-block:: python

    not len({{pith_curr_var_name}}) or ((

...the call to the :func:`len` builtin *cannot* be optimized away to simply:

.. code-block:: python

    not {{pith_curr_var_name}} or ((

Why? Because a container being a collection does *not* necessarily imply that
container to sanely implement the ``__bool__()`` dunder method. The canonical
example is the third-party :class:`tensor.Torch` type, a collection whose
``__bool__()`` dunder method raises exceptions for tensors containing one or
more values: e.g.,

    RuntimeError: Boolean value of Tensor with more than one value is ambiguous
'''

# ....................{ CODE ~ generic                     }....................
CODE_PEP484585_GENERIC_PREFIX = '''(
{indent_curr}    # True only if this pith is of this generic type.
{indent_curr}    isinstance({pith_curr_assign_expr}, {hint_curr_expr}) and'''
'''
:pep:`484`- and :pep:`585`-compliant code snippet prefixing all code
type-checking the current pith against each unerased pseudo-superclass
subclassed by a :pep:`484`-compliant **generic** (i.e., PEP-compliant type hint
subclassing a combination of one or more of the :mod:`typing.Generic`
superclass, the :mod:`typing.Protocol` superclass, and/or other :mod:`typing`
non-class objects).

Caveats
-------
The ``{indent_curr}`` format variable is intentionally brace-protected to
efficiently defer its interpolation until the complete PEP-compliant code
snippet type-checking the current pith against *all* subscripted arguments of
this parent type has been generated.
'''


CODE_PEP484585_GENERIC_SUFFIX = '''
{indent_curr})'''
'''
:pep:`484`- and :pep:`585`-compliant code snippet suffixing all code
type-checking the current pith against each unerased pseudo-superclass
subclassed by a :pep:`484`-compliant generic.
'''


CODE_PEP484585_GENERIC_CHILD = '''
{{indent_curr}}    # True only if this pith deeply satisfies this unerased
{{indent_curr}}    # pseudo-superclass of this generic.
{{indent_curr}}    {hint_child_placeholder} and'''
'''
:pep:`484`- and :pep:`585`-compliant code snippet type-checking the current pith
against the current unerased pseudo-superclass subclassed by a
:pep:`484`-compliant generic.

Caveats
-------
The caller is required to manually slice the trailing suffix ``" and"`` after
applying this snippet to the last unerased pseudo-superclass of such a generic.
While there exist alternate and more readable means of accomplishing this, this
approach is the optimally efficient.

The ``{indent_curr}`` format variable is intentionally brace-protected to
efficiently defer its interpolation until the complete PEP-compliant code
snippet type-checking the current pith against *all* subscripted arguments of
this parent type has been generated.
'''

# ....................{ CODE ~ mapping                     }....................
CODE_PEP484585_MAPPING = '''(
{indent_curr}    # True only if this pith is of this mapping type *AND*...
{indent_curr}    isinstance({pith_curr_assign_expr}, {hint_curr_expr}) and
{indent_curr}    # True only if either this mapping is empty *OR* this mapping
{indent_curr}    # is non-empty and...
{indent_curr}    (not len({pith_curr_var_name}) or ({func_curr_code_key_value}))
{indent_curr})'''
'''
:pep:`484`- and :pep:`585`-compliant code snippet type-checking the current pith
against a parent **standard mapping type** (i.e., type hint subscripted by
exactly two child type hints constraining *all* key-value pairs of this pith,
which necessarily satisfies the :class:`collections.abc.Mapping` protocol with
guaranteed :math:`O(1)` indexation of at least the first pair).

Caveats
-------
**This snippet cannot contain ternary conditionals.** See
:data:`.CODE_PEP484585_SEQUENCE_ARGS_1` for further commentary.

There exist numerous means of accessing the first key-value pair of a
dictionary. The approach taken here is well-known to be the fastest, as
documented at this `StackOverflow answer`_.

Lastly, note that, in the test implemented in the code above:

.. code-block:: python

    (not len({pith_curr_var_name}) or ({func_curr_code_key_value}))

...the call to the :func:`len` builtin *cannot* be optimized away to simply:

.. code-block:: python

    (not {pith_curr_var_name} or ({func_curr_code_key_value}))

See :data:`.CODE_PEP484585_QUASIITERABLE` for further details.

.. _StackOverflow answer:
   https://stackoverflow.com/a/70490285/2809027
'''


CODE_PEP484585_MAPPING_KEY_ONLY_PITH_CHILD_EXPR = (
    '''next(iter({pith_curr_var_name}))''')
'''
:pep:`484`- and :pep:`585`-compliant Python expression efficiently yielding the
first key of the current mapping pith.
'''


CODE_PEP484585_MAPPING_VALUE_ONLY_PITH_CHILD_EXPR = (
    '''next(iter({pith_curr_var_name}.values()))''')
'''
:pep:`484`- and :pep:`585`-compliant Python expression efficiently yielding the
first value of the current mapping pith when type-checking *only* the values of
this mapping (i.e., when the keys of this mapping are ignorable).
'''


CODE_PEP484585_MAPPING_KEY_VALUE_PITH_CHILD_EXPR = (
    '''{pith_curr_var_name}[{pith_key_var_name}]''')
'''
:pep:`484`- and :pep:`585`-compliant Python expression efficiently yielding the
first value of the current mapping pith when type-checking both the keys *and*
values of this mapping (i.e., when the keys of this mapping are unignorable).
'''


CODE_PEP484585_MAPPING_KEY_ONLY = '''
{indent_curr}        # True only if this key satisfies this hint.
{indent_curr}        {hint_key_placeholder}'''
'''
:pep:`484`- and :pep:`585`-compliant code snippet type-checking *only* the first
key of the current pith against *only* the key child type hint subscripting a
parent standard mapping type.

This snippet intentionally avoids type-checking values and is thus suitable for
type-checking mappings with ignorable value child type hints (e.g.,
``dict[str, object]``).
'''


CODE_PEP484585_MAPPING_VALUE_ONLY = '''
{indent_curr}        # True only if this value satisfies this hint.
{indent_curr}        {hint_value_placeholder}'''
'''
:pep:`484`- and :pep:`585`-compliant code snippet type-checking *only* the first
value of the current pith against *only* the value child type hint subscripting
a parent standard mapping type.

This snippet intentionally avoids type-checking keys and is thus suitable for
type-checking mappings with ignorable key child type hints (e.g.,
``dict[object, str]``).
'''


CODE_PEP484585_MAPPING_KEY_VALUE = f'''
{{indent_curr}}        # Localize the first key of this mapping.
{{indent_curr}}        ({{pith_key_var_name}} := {CODE_PEP484585_MAPPING_KEY_ONLY_PITH_CHILD_EXPR}) is {{pith_key_var_name}} and
{{indent_curr}}        # True only if this key satisfies this hint.
{{indent_curr}}        {{hint_key_placeholder}} and
{{indent_curr}}        # True only if this value satisfies this hint.
{{indent_curr}}        {{hint_value_placeholder}}'''
'''
:pep:`484`- and :pep:`585`-compliant code snippet type-checking *only* the first
key-value pair of the current pith against *only* the key and value child type
hints subscripting a parent standard mapping type.

This snippet intentionally type-checks both keys and values is thus unsuitable
for type-checking mappings with ignorable key or value child type hints (e.g.,
``dict[object, str]``, ``dict[str, object]``).
'''

# ....................{ CODE ~ tuple                       }....................
CODE_PEP484585_TUPLE_FIXED_PREFIX = '''(
{indent_curr}    # True only if this pith is a tuple.
{indent_curr}    isinstance({pith_curr_assign_expr}, tuple) and'''
'''
:pep:`484`- and :pep:`585`-compliant code snippet prefixing all code
type-checking the current pith against each subscripted child hint of an
itemized :class:`typing.Tuple` type of the form ``typing.Tuple[{typename1},
{typename2}, ..., {typenameN}]``.
'''


CODE_PEP484585_TUPLE_FIXED_SUFFIX = '''
{indent_curr})'''
'''
:pep:`484`- and :pep:`585`-compliant code snippet suffixing all code
type-checking the current pith against each subscripted child hint of an
itemized :class:`typing.Tuple` type of the form ``typing.Tuple[{typename1},
{typename2}, ..., {typenameN}]``.
'''


CODE_PEP484585_TUPLE_FIXED_EMPTY = '''
{{indent_curr}}    # True only if this tuple is empty.
{{indent_curr}}    not {pith_curr_var_name} and'''
'''
:pep:`484`- and :pep:`585`-compliant code snippet prefixing all code
type-checking the current pith to be empty against an itemized
:class:`typing.Tuple` type of the non-standard form ``typing.Tuple[()]``.

See Also
--------
:data:`CODE_PEP484585_TUPLE_FIXED_NONEMPTY_CHILD`
    Further details.
'''


CODE_PEP484585_TUPLE_FIXED_LEN = '''
{{indent_curr}}    # True only if this tuple is of the expected length.
{{indent_curr}}    len({pith_curr_var_name}) == {hint_childs_len} and'''
'''
:pep:`484`- and :pep:`585`-compliant code snippet prefixing all code
type-checking the current pith to be of the expected length against an itemized
:class:`typing.Tuple` type of the non-standard form ``typing.Tuple[()]``.

See Also
--------
:data:`CODE_PEP484585_TUPLE_FIXED_NONEMPTY_CHILD`
    Further details.
'''


CODE_PEP484585_TUPLE_FIXED_NONEMPTY_CHILD = '''
{{indent_curr}}    # True only if this item of this non-empty tuple deeply
{{indent_curr}}    # satisfies this child hint.
{{indent_curr}}    {hint_child_placeholder} and'''
'''
:pep:`484`- and :pep:`585`-compliant code snippet type-checking the current pith
against the current child hint subscripting an itemized :class:`typing.Tuple`
type of the form ``typing.Tuple[{typename1}, {typename2}, ..., {typenameN}]``.

Caveats
-------
The caller is required to manually slice the trailing suffix ``" and"`` after
applying this snippet to the last subscripted child hint of an itemized
:class:`typing.Tuple` type. While there exist alternate and more readable means
of accomplishing this, this approach is the optimally efficient.

The ``{indent_curr}`` format variable is intentionally brace-protected to
efficiently defer its interpolation until the complete PEP-compliant code
snippet type-checking the current pith against *all* subscripted arguments of
this parent type has been generated.
'''


CODE_PEP484585_TUPLE_FIXED_NONEMPTY_PITH_CHILD_EXPR = (
    '''{pith_curr_var_name}[{pith_child_index}]''')
'''
:pep:`484`- and :pep:`585`-compliant Python expression yielding the value of the
currently indexed item of the current pith (which, by definition, *must* be a
tuple).
'''

# ....................{ CODE ~ subclass                    }....................
CODE_PEP484585_SUBCLASS = '''(
{indent_curr}    # True only if this pith is a class *AND*...
{indent_curr}    isinstance({pith_curr_assign_expr}, type) and
{indent_curr}    # True only if this class subclasses this superclass.
{indent_curr}    issubclass({pith_curr_var_name}, {hint_curr_expr})
{indent_curr})'''
'''
:pep:`484`- and :pep:`585`-compliant code snippet type-checking the current pith
to be a subclass of the subscripted child hint of a :pep:`484`- or
:pep:`585`-compliant **subclass type hint** (e.g., ``typing.Type[...]``,
``type[...]``).
'''

# ....................{ FORMATTERS                         }....................
# str.format() methods, globalized to avoid inefficient dot lookups elsewhere.
# This is an absurd micro-optimization. *fight me, github developer community*
CODE_PEP484585_REITERABLE_OR_SEQUENCE_format: CallableStrFormat = (
    CODE_PEP484585_REITERABLE_OR_SEQUENCE.format)
CODE_PEP484585_REITERABLE_PITH_CHILD_EXPR_format: CallableStrFormat = (
    CODE_PEP484585_REITERABLE_PITH_CHILD_EXPR.format)
CODE_PEP484585_SEQUENCE_PITH_CHILD_EXPR_format: CallableStrFormat = (
    CODE_PEP484585_SEQUENCE_PITH_CHILD_EXPR.format)
CODE_PEP484585_COLLECTION_format: CallableStrFormat = (
    CODE_PEP484585_COLLECTION.format)
CODE_PEP484585_QUASIITERABLE_format: CallableStrFormat = (
    CODE_PEP484585_QUASIITERABLE.format)
CODE_PEP484585_GENERIC_CHILD_format: CallableStrFormat = (
    CODE_PEP484585_GENERIC_CHILD.format)
CODE_PEP484585_MAPPING_format: CallableStrFormat = (
    CODE_PEP484585_MAPPING.format)
CODE_PEP484585_MAPPING_KEY_ONLY_format: CallableStrFormat = (
    CODE_PEP484585_MAPPING_KEY_ONLY.format)
CODE_PEP484585_MAPPING_KEY_VALUE_format: CallableStrFormat = (
    CODE_PEP484585_MAPPING_KEY_VALUE.format)
CODE_PEP484585_MAPPING_VALUE_ONLY_format: CallableStrFormat = (
    CODE_PEP484585_MAPPING_VALUE_ONLY.format)
CODE_PEP484585_MAPPING_KEY_ONLY_PITH_CHILD_EXPR_format: CallableStrFormat = (
    CODE_PEP484585_MAPPING_KEY_ONLY_PITH_CHILD_EXPR.format)
CODE_PEP484585_MAPPING_VALUE_ONLY_PITH_CHILD_EXPR_format: CallableStrFormat = (
    CODE_PEP484585_MAPPING_VALUE_ONLY_PITH_CHILD_EXPR.format)
CODE_PEP484585_MAPPING_KEY_VALUE_PITH_CHILD_EXPR_format: CallableStrFormat = (
    CODE_PEP484585_MAPPING_KEY_VALUE_PITH_CHILD_EXPR.format)
CODE_PEP484585_SUBCLASS_format: CallableStrFormat = (
    CODE_PEP484585_SUBCLASS.format)
CODE_PEP484585_TUPLE_FIXED_EMPTY_format: CallableStrFormat = (
    CODE_PEP484585_TUPLE_FIXED_EMPTY.format)
CODE_PEP484585_TUPLE_FIXED_LEN_format: CallableStrFormat = (
    CODE_PEP484585_TUPLE_FIXED_LEN.format)
CODE_PEP484585_TUPLE_FIXED_NONEMPTY_CHILD_format: CallableStrFormat = (
    CODE_PEP484585_TUPLE_FIXED_NONEMPTY_CHILD.format)
CODE_PEP484585_TUPLE_FIXED_NONEMPTY_PITH_CHILD_EXPR_format: CallableStrFormat = (
    CODE_PEP484585_TUPLE_FIXED_NONEMPTY_PITH_CHILD_EXPR.format)
