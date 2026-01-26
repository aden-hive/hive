#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **type-checking code factories** (i.e., low-level callables dynamically
generating pure-Python code snippets type-checking arbitrary objects against
PEP-compliant type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
# All "FIXME:" comments for this submodule reside in this package's "__init__"
# submodule to improve maintainability and readability here.

#FIXME: Indentation appears to have gone awry, sadly:
#    (line 0027)     # If this parameter was passed...
#    (line 0028)     if __beartype_pith_0 is not __beartype_get_violation:
#    (line 0029)         # Type-check this parameter or return against this type hint.
#    (line 0030)         if not (
#    (line 0031)         # True only if this pith is of this iterable type *AND*...
#    (line 0032)         isinstance(__beartype_pith_0, __beartype_object_108584612876976) and
#
#It's not just indentation, though. This code is less efficient than it could
#be. We can strike down two birds with one stone by simply aggregating the above
#two "if" conditionals to instead resemble:
#    (line 0027)     # If this parameter was passed, type-check this parameter or return against this type hint...
#    (line 0028)     if __beartype_pith_0 is not __beartype_get_violation and not (
#    (line 0029)         # True only if this pith is of this iterable type *AND*...
#    (line 0030)         isinstance(__beartype_pith_0, __beartype_object_108584612876976) and
#
#That said, the current approach technically does work and compile. Let's
#revisit this once the code settles down a little, please.

# ....................{ IMPORTS                            }....................
from beartype.roar import (
    BeartypeDecorHintPep593Exception,
    BeartypeDecorHintPepException,
    BeartypeDecorHintPepUnsupportedException,
)
from beartype.typing import Optional
from beartype._data.code.datacodename import (
    ARG_NAME_GETRANDBITS,
    VAR_NAME_PITH_ROOT,
)
from beartype._check.metadata.hint.hintsmeta import HintsMeta
from beartype._check.metadata.hint.hintsane import HINT_SANE_IGNORABLE
from beartype._check.code.codemagic import (
    EXCEPTION_PREFIX_FUNC_WRAPPER_LOCAL,
    EXCEPTION_PREFIX_HINT,
)
from beartype._check.code.codescope import express_func_scope_type_ref
from beartype._check.code._pep.codepep484604 import (
    make_hint_pep484604_check_expr)
from beartype._check.code._pep.pep484585.codepep484585container import (
    make_hint_pep484585_container_check_expr)
from beartype._check.code._pep.pep484585.codepep484585generic import (
    make_hint_pep484585_generic_unsubbed_check_expr)
from beartype._check.code.snip.codesnipcls import PITH_INDEX_TO_VAR_NAME
from beartype._check.code.snip.codesnipstr import (
    CODE_PEP484_INSTANCE_format,
    CODE_PEP572_PITH_ASSIGN_EXPR_format,
)
from beartype._check.metadata.hint.hintsane import HintSane
from beartype._conf.confmain import BeartypeConf
from beartype._data.code.datacodelen import (
    LINE_RSTRIP_INDEX_AND,
    LINE_RSTRIP_INDEX_OR,
)
from beartype._data.code.pep.datacodepep484585 import (
    CODE_PEP484585_MAPPING_format,
    CODE_PEP484585_MAPPING_KEY_ONLY_format,
    CODE_PEP484585_MAPPING_KEY_VALUE_format,
    CODE_PEP484585_MAPPING_VALUE_ONLY_format,
    CODE_PEP484585_MAPPING_KEY_ONLY_PITH_CHILD_EXPR_format,
    CODE_PEP484585_MAPPING_VALUE_ONLY_PITH_CHILD_EXPR_format,
    CODE_PEP484585_MAPPING_KEY_VALUE_PITH_CHILD_EXPR_format,
    CODE_PEP484585_SUBCLASS_format,
    CODE_PEP484585_TUPLE_FIXED_EMPTY_format,
    CODE_PEP484585_TUPLE_FIXED_LEN_format,
    CODE_PEP484585_TUPLE_FIXED_NONEMPTY_CHILD_format,
    CODE_PEP484585_TUPLE_FIXED_NONEMPTY_PITH_CHILD_EXPR_format,
    CODE_PEP484585_TUPLE_FIXED_PREFIX,
    CODE_PEP484585_TUPLE_FIXED_SUFFIX,
)
from beartype._data.code.pep.datacodepep586 import (
    CODE_PEP586_LITERAL_format,
    CODE_PEP586_PREFIX_format,
    CODE_PEP586_SUFFIX,
)
from beartype._data.code.pep.datacodepep593 import (
    CODE_PEP593_VALIDATOR_IS_format,
    CODE_PEP593_VALIDATOR_METAHINT_format,
    CODE_PEP593_VALIDATOR_PREFIX,
    CODE_PEP593_VALIDATOR_SUFFIX_format,
)
from beartype._data.error.dataerrmagic import (
    EXCEPTION_PLACEHOLDER as EXCEPTION_PREFIX)
from beartype._data.typing.datatypingport import Hint
from beartype._data.typing.datatyping import (
    CodeGenerated,
    TypeStack,
)
from beartype._data.hint.sign.datahintsigncls import HintSign
from beartype._data.hint.sign.datahintsigns import (
    HintSignAnnotated,
    HintSignCounter,
    HintSignForwardRef,
    HintSignPep484585GenericUnsubbed,
    HintSignLiteral,
    HintSignPep484585TupleFixed,
    HintSignType,
    # HintSignTypedDict,
    HintSignUnion,
)
from beartype._data.hint.sign.datahintsignset import (
    HINT_SIGNS_CONTAINER_ARGS_1,
    HINT_SIGNS_MAPPING,
    HINT_SIGNS_ORIGIN_ISINSTANCEABLE,
    HINT_SIGNS_SUPPORTED_DEEP,
    HINT_SIGNS_UNION,
)
from beartype._util.cache.utilcachecall import callable_cached
from beartype._util.cache.pool.utilcachepoolinstance import (
    acquire_instance,
    release_instance,
)
from beartype._util.cls.pep.clspep3119 import (
    die_unless_object_issubclassable,
    is_object_issubclassable,
)
from beartype._util.func.utilfuncscope import add_func_scope_attr
from beartype._util.hint.pep.proposal.pep484585.pep484585 import (
    get_hint_pep484585_arg,
    get_hint_pep484585_args,
)
from beartype._util.hint.pep.proposal.pep484585646 import (
    is_hint_pep484585646_tuple_empty)
from beartype._util.hint.pep.proposal.pep586 import get_hint_pep586_literals
from beartype._util.hint.pep.proposal.pep593 import (
    get_hint_pep593_metadata,
    get_hint_pep593_metahint,
)
from beartype._util.hint.pep.utilpepget import (
    get_hint_pep_args,
    get_hint_pep_origin_type_isinstanceable,
)
from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign_or_none
from beartype._util.hint.pep.utilpeptest import (
    die_if_hint_pep_unsupported,
    is_hint_pep,
)
from beartype._util.hint.utilhinttest import die_as_hint_unsupported
from beartype._util.kind.maplike.utilmapset import update_mapping
from beartype._util.text.utiltextmunge import replace_str_substrs
from beartype._util.text.utiltextrepr import represent_object
from random import getrandbits

# ....................{ MAKERS                             }....................
@callable_cached
def make_check_expr(
    # ..................{ ARGS ~ mandatory                   }..................
    hint_sane: HintSane,
    conf: BeartypeConf,

    # ..................{ ARGS ~ optional                    }..................
    cls_stack: TypeStack = None,
) -> CodeGenerated:
    '''
    **Type-checking expression factory** (i.e., low-level callable dynamically
    generating a pure-Python boolean expression type-checking an arbitrary
    object against the passed PEP-compliant type hint).

    This code factory performs a breadth-first search (BFS) over the abstract
    graph of nested type hints reachable from the subscripted arguments of the
    passed root type hint. For each such (possibly nested) hint, this factory
    embeds one or more boolean subexpressions validating a (possibly nested
    sub)object of an arbitrary object against that hint into the full boolean
    expression created and returned by this factory. In short, this factory is
    the beating heart of :mod:`beartype`. We applaud you for your perseverance.
    You finally found the essence of the Great Bear. You did it!! Now, we clap.

    This code factory is memoized for efficiency.

    Caveats
    -------
    **This factory intentionally accepts no** ``exception_prefix``
    **parameter.** Why? Since that parameter is typically specific to the
    context-sensitive use case of the caller, accepting that parameter would
    prevent this factory from memoizing the passed hint with the returned code,
    which would rather defeat the point. Instead, this factory only:

    * Returns generic non-working code containing the placeholder
      :data:`VAR_NAME_PITH_ROOT` substring that the caller is required to
      globally replace by either the name of the current parameter *or*
      ``return`` for return values (e.g., by calling the builtin
      :meth:`str.replace` method) to generate the desired non-generic working
      code type-checking that parameter or return value.
    * Raises generic non-human-readable exceptions containing the placeholder
      :attr:`beartype._util.error.utilerrraise.EXCEPTION_PLACEHOLDER` substring
      that the caller is required to explicitly catch and raise non-generic
      human-readable exceptions from by calling the
      :func:`beartype._util.error.utilerrraise.reraise_exception_placeholder`
      function.

    Parameters
    ----------
    hint_sane : HintSane
        **Sanified type hint metadata** (i.e., :data:`.HintSane` object)
        encapsulating the hint to be type-checked.
    conf : BeartypeConf
        **Beartype configuration** (i.e., self-caching dataclass encapsulating
        all settings configuring type-checking for the passed object).
    cls_stack : TypeStack, optional
        **Type stack** (i.e., either a tuple of the one or more
        :func:`beartype.beartype`-decorated classes lexically containing the
        class variable or method annotated by this hint *or* :data:`None`).
        Defaults to :data:`None`.

    Returns
    -------
    CodeGenerated
        Tuple containing the Python code snippet dynamically generated by this
        code generator and metadata describing that code. See also the
        :attr:`beartype._data.typing.datatyping.CodeGenerated` type hint.

    Raises
    ------
    BeartypeDecorHintPepException
        If this object is *not* a PEP-compliant type hint.
    BeartypeDecorHintPepUnsupportedException
        If this object is a PEP-compliant type hint currently unsupported by
        the :func:`beartype.beartype` decorator.
    BeartypeDecorHintPep484Exception
        If one or more PEP-compliant type hints visitable from this object are
        nested :attr:`typing.NoReturn` child hints, since
        :attr:`typing.NoReturn` is valid *only* as a non-nested return hint.
    BeartypeDecorHintPep593Exception
        If one or more PEP-compliant type hints visitable from this object
        subscript the :pep:`593`-compliant :class:`typing.Annotated` class such
        that:

        * The second argument subscripting that class is an instance of the
          :class:`beartype.vale.Is` class.
        * One or more further arguments subscripting that class are *not*
          instances of the :class:`beartype.vale.Is` class.

    Warns
    -----
    BeartypeDecorHintPep585DeprecationWarning
        If one or more :pep:`484`-compliant type hints visitable from this
        object have been deprecated by :pep:`585`.
    '''

    # ..................{ LOCALS ~ hint : current            }..................
    # Currently visited hint.
    hint_curr: Hint = None  # pyright: ignore

    # Metadata encapsulating the currently visited hint.
    hint_curr_sane: HintSane = None  # type: ignore[assignment]

    # Current unsubscripted typing attribute associated with this hint (e.g.,
    # "Union" if "hint_curr == Union[int, str]").
    hint_curr_sign: HintSign = None  # type: ignore[assignment]

    # ..................{ LOCALS ~ hint : child              }..................
    # Currently iterated child hint subscripting the currently visited hint.
    hint_child: object = None

    # Current unsubscripted typing attribute associated with this child hint
    # (e.g., "Union" if "hint_child == Union[int, str]").
    hint_child_sign: Optional[HintSign] = None

    # Currently iterated child hint subscripting the currently visited hint *OR*
    # sanified child hint metadata** (i.e., "HintSane" object describing
    # that child hint).
    hint_child_sane: HintSane = None  # type: ignore[assignment]

    # ..................{ LOCALS ~ hint : childs             }..................
    # Current tuple of all child hints subscripting the currently visited hint
    # (e.g., "(int, str)" if "hint_curr == Union[int, str]").
    hint_childs: tuple = None  # type: ignore[assignment]

    # Number of child hints subscripting the currently visited hint.
    hint_childs_len: int = None  # type: ignore[assignment]

    # ..................{ LOCALS ~ hint : metadata           }..................
    # Fixed list of all metadata describing all visitable hints currently
    # discovered by the breadth-first search (BFS) below. This list acts as a
    # standard First In First Out (FILO) queue, enabling this BFS to be
    # implemented as an efficient imperative algorithm rather than an
    # inefficient (and dangerous, due to both unavoidable stack exhaustion and
    # avoidable infinite recursion) recursive algorithm.
    #
    # Note that this list is guaranteed by the previously called
    # _die_if_hint_repr_exceeds_child_limit() function to be larger than the
    # number of hints transitively visitable from this root hint. Ergo, *ALL*
    # indexation into this list performed by this BFS is guaranteed to be safe.
    # Ergo, avoid explicitly testing below that the "hints_meta.index_last"
    # integer maintained by this BFS is strictly less than
    # "FIXED_LIST_SIZE_MEDIUM", as this constraint is already guaranteed to be
    # the case.
    hints_meta = acquire_instance(HintsMeta)

    # Initialize this fixed list.
    hints_meta.reinit(cls_stack=cls_stack, conf=conf)

    # 0-based index of metadata describing the currently visited hint in this
    # fixed list.
    hints_meta_index_curr = 0

    # ..................{ LOCALS ~ pep : 484                 }..................
    # Set of the unqualified classnames referred to by all relative forward
    # references visitable from this root hint if any *OR* "None" otherwise
    # (i.e., if no such forward references are visitable).
    hint_refs_type_basename: Optional[set] = None

    # ..................{ LOCALS ~ func : code               }..................
    # Python code snippet type-checking the root pith against the root hint:
    # * Localized separately from the "func_wrapper_code" snippet to enable this
    #   function to validate this code to be valid *BEFORE* returning this code.
    # * Initialized to a placeholder string to be globally replaced in the
    #   Python code snippet to be returned (i.e., "func_wrapper_code") by a
    #   Python code snippet type-checking the root pith expression (i.e.,
    #   "VAR_NAME_PITH_ROOT") against the root hint (i.e., "hint_root").
    func_root_code = hints_meta.enqueue_hint_child_sane(
        hint_sane=hint_sane, pith_expr=VAR_NAME_PITH_ROOT)

    # Python code snippet to be returned, seeded with a placeholder to be
    # replaced on the first iteration of the breadth-first search performed
    # below with a snippet type-checking the root pith against the root hint.
    #
    # Note that, shockingly, brute-force string concatenation has been
    # personally profiled by @leycec to be substantially faster than *ALL*
    # alternatives under CPython up to a large number of iterations (e.g.,
    # 100,000). This includes these popular alternatives, *ALL* of which are
    # orders of magnitude slower than brute-force string concatenation:
    # * deque.append().
    # * list.append().
    func_wrapper_code = func_root_code

    # ..................{ SEARCH                             }..................
    # While the 0-based index of metadata describing the next visited hint in
    # the "hints_meta" list does *NOT* exceed that describing the last
    # visitable hint in this list, there remains at least one hint to be
    # visited in the breadth-first search performed by this iteration.
    while hints_meta_index_curr <= hints_meta.index_last:
        # Update instance variables of this queue to reflect that this hint is
        # now the currently visited hint.
        hints_meta.set_index_current(hints_meta_index_curr)

        # Localize metadata for both efficiency and f-string purposes.
        hint_curr_sane = hints_meta.hint_curr_meta.hint_sane
        hint_curr = hint_curr_sane.hint
        # print(f'Visiting type hint {repr(hint_curr_sane)}...')

        # ................{ PEP                                }................
        # If this hint is PEP-compliant...
        if is_hint_pep(hint_curr):
            #FIXME: Refactor to call warn_if_hint_pep_unsupported() instead.
            #Actually...wait. This is probably still a valid test here. We'll
            #need to instead augment the is_hint_ignorable() function to
            #additionally test whether the passed hint is unsupported, in which
            #case that function should return false as well as emit a non-fatal
            #warning ala the new warn_if_hint_pep_unsupported() function --
            #which should probably simply be removed now. *sigh*
            #FIXME: Actually, in that case, we can simply reduce the following
            #two calls to simply:
            #    die_if_hint_pep_ignorable(
            #        hint=hint_curr, exception_prefix=hint_curr_exception_prefix)
            #
            #Of course, this implies we want to refactor the
            #die_if_hint_pep_unsupported() function into
            #die_if_hint_pep_ignorable()... probably.

            # If this hint is currently unsupported, raise an exception.
            #
            # Note the human-readable label prefixing the representations of
            # child PEP-compliant type hints is unconditionally passed. Since
            # the root hint has already been validated to be supported by
            # the above call to the same function, this call is guaranteed to
            # *NEVER* raise an exception for that hint.
            die_if_hint_pep_unsupported(
                hint=hint_curr, exception_prefix=EXCEPTION_PREFIX)
            # Else, this hint is supported.

            # Assert that this hint is unignorable. Iteration below generating
            # code for child hints of the current parent hint is *REQUIRED* to
            # explicitly ignore ignorable child hints. Since the caller has
            # explicitly ignored ignorable root hints, these two guarantees
            # together ensure that all hints visited by this breadth-first
            # search *SHOULD* be unignorable. Naturally, we validate that here.
            assert hint_curr is not HINT_SANE_IGNORABLE, (
                f'{EXCEPTION_PREFIX}ignorable type hint '
                f'{repr(hint_curr)} not ignored.'
            )

            # Sign uniquely identifying this hint, localized for usability.
            hint_curr_sign = hints_meta.hint_curr_meta.hint_sign  # type: ignore[assignment]
            # print(f'Visiting PEP type hint {repr(hint_curr)} sign {repr(hint_curr_sign)}...')

            #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
            # NOTE: Whenever adding support for (i.e., when generating code
            # type-checking) a new "typing" attribute below, similar support
            # for that attribute *MUST* also be added to the parallel:
            # * "beartype._check.error" subpackage, which raises exceptions on
            #   the current pith failing this check.
            # * "beartype._data.hint.sign.datahintsignset.HINT_SIGNS_SUPPORTED_DEEP"
            #   frozen set of all signs for which this function generates deeply
            #   type-checking code.
            #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

            #FIXME: Python 3.10 provides proper syntactic support for "case"
            #statements, which should allow us to dramatically optimize this
            #"if" logic into equivalent "case" logic *AFTER* we drop support
            #for Python 3.9. Of course, that will be basically never, so we'll
            #have to preserve this for basically forever. What you gonna do?
            #FIXME: Actually, we should probably just leverage a hypothetical
            #"beartype.vale.IsInline[...]" validator to coerce this slow O(n)
            #procedural logic into fast O(1) object-oriented logic. Of course,
            #object-oriented logic is itself slow -- so we only do this if we
            #can sufficiently memoize that logic. Consideration!

            # Switch on (as in, pretend Python provides a "case" statement) the
            # sign identifying this hint to decide which type of code to
            # generate to type-check the current pith against the current hint.
            #
            # This decision is intentionally implemented as a linear series of
            # tests ordered in descending likelihood for efficiency. While
            # alternative implementations (that are more readily readable and
            # maintainable) do exist, these alternatives all appear to be
            # substantially less efficient.
            #
            # Consider the standard alternative of sequestering the body of
            # each test implemented below into either:
            # * A discrete private function called by this function. This
            #   approach requires maintaining a global private dictionary
            #   mapping from each support unsubscripted typing attribute to
            #   the function generating code for that attribute: e.g.,
            #      def pep_code_check_union(...): ...
            #      _HINT_TYPING_ATTR_ARGLESS_TO_CODER = {
            #          typing.Union: pep_code_check_union,
            #      }
            #   Each iteration of this loop then looks up the function
            #   generating code for the current attribute from this dictionary
            #   and calls that function to do so. Function calls come with
            #   substantial overhead in Python, impacting performance more
            #   than the comparable linear series of tests implemented below.
            #   Additionally, these functions *MUST* mutate local variables of
            #   this function by some arcane means -- either:
            #   * Passing these locals to each such function, returning these
            #     locals from each such function, and assigning these return
            #     values to these locals in this function after each such call.
            #   * Passing a single composite fixed list of these locals to each
            #     such function, which then mutates these locals in-place,
            #     which then necessitates this function permanently store these
            #     locals in such a list rather than as local variables.
            # * A discrete closure of this function, which adequately resolves
            #   the aforementioned locality issue via the "nonlocal" keyword at
            #   a substantial up-front performance cost of redeclaring these
            #   closures on each invocation of this function.
            #
            # ..............{ SHALLOW                            }..............
            # Perform shallow type-checking logic (i.e., logic that does *NOT*
            # recurse and thus "bottoms out" at this hint) *BEFORE* deep
            # type-checking logic. The latter needs additional setup (e.g.,
            # generation of assignment expressions) *NOT* needed by the former,
            # whose requirements are more understandably minimalist.
            #
            # Note that:
            # * Shallow type-checking code should access this pith via
            #   "pith_curr_expr". Since this code does *NOT* recurse,
            #   "pith_curr_expr" accesses this pith optimally efficiently.
            # * Deep type-checking code should access this pith via
            #   "pith_assign_expr". Since that code *DOES* recurse, only
            #   "pith_assign_expr" accesses this pith optimally efficiently;
            #   "pith_curr_expr" accesses this pith extremely inefficiently.
            # * Ignorable type-checking code (i.e., code ignoring this hint but
            #   otherwise unsuitable for implementation as a reducer called by
            #   the "beartype._check.convert._reduce.redmain" submodule, typically
            #   due to useful side effects intentionally interacting with this
            #   BFS) should follow the design pattern established by the
            #   "HintSignPep695TypeAliasSubscripted" branch below.
            #
            # ..............{ ORIGIN                             }..............
            # If this hint both...
            if (
                # Originates from an origin type and may thus be shallowly
                # type-checked against that type *AND is either...
                hint_curr_sign in HINT_SIGNS_ORIGIN_ISINSTANCEABLE and (
                    # Unsubscripted *OR*...
                    not get_hint_pep_args(hint_curr) or
                    # Currently unsupported with deep type-checking...
                    hint_curr_sign not in HINT_SIGNS_SUPPORTED_DEEP
                )
            ):
            # Then generate trivial code shallowly type-checking the current
            # pith as an instance of the origin type originating this sign
            # (e.g., "list" for the hint "typing.List[int]").
                # print(f'Shallow checking unsubscripted hint {repr(hint_curr)}...')

                # Code type-checking the current pith against this origin type.
                hints_meta.func_curr_code = CODE_PEP484_INSTANCE_format(
                    pith_curr_expr=hints_meta.pith_curr_expr,
                    # Python expression evaluating to this origin type.
                    hint_curr_expr=hints_meta.add_func_scope_type_or_types(
                        # Origin type of this hint if any *OR* raise an
                        # exception -- which should *NEVER* happen, as this hint
                        # was validated above to be supported.
                        get_hint_pep_origin_type_isinstanceable(hint_curr)),
                )
            # Else, this hint is either subscripted, not shallowly
            # type-checkable, *OR* deeply type-checkable.
            #
            # ..............{ FORWARDREF                         }..............
            # If this hint is a forward reference...
            elif hint_curr_sign is HintSignForwardRef:
                # Render this forward reference accessible to the body of this
                # wrapper function by populating:
                # * A Python expression evaluating to a new forward reference
                #   proxy encapsulating the class referred to by this forward
                #   reference.
                # * A set of the unqualified classnames referred to by *ALL*
                #   relative forward references visited by this BFS, including
                #   this reference if relative. If this set was previously
                #   uninstantiated (i.e., "None"), this assignment initializes
                #   this local to the new set instantiated by this call; else,
                #   this assignment preserves this local set as is.
                (
                    hints_meta.hint_curr_expr,
                    hint_refs_type_basename,
                ) = express_func_scope_type_ref(
                    forwardref=hint_curr,  # type: ignore[arg-type]
                    refs_type_basename=hint_refs_type_basename,
                    func_scope=hints_meta.func_wrapper_scope,
                    exception_prefix=EXCEPTION_PREFIX,
                )

                #FIXME: *REDUNDANT.* Shallow type-checking code defined below
                #already performs this exact same logic. Excise us up, please.
                # # Code type-checking the current pith against this class.
                # hints_meta.func_curr_code = CODE_PEP484_INSTANCE_format(
                #     pith_curr_expr=hints_meta.pith_curr_expr,
                #     hint_curr_expr=hints_meta.hint_curr_expr,
                # )
            # Else, this hint is *NOT* a forward reference.
            #
            # Since this hint is *NOT* shallowly type-checkable, this hint
            # *MUST* be deeply type-checkable. So, we do so now.
            #
            # ..............{ DEEP                               }..............
            # Perform deep type-checking logic (i.e., logic that is guaranteed
            # to recurse and thus *NOT* "bottom out" at this hint).
            else:
                # Tuple of all child hints subscripting this hint if any *OR*
                # the empty tuple otherwise (e.g., if this hint is its own
                # unsubscripted "typing" attribute).
                #
                # Note that the "__args__" dunder attribute is *NOT* guaranteed
                # to exist for arbitrary PEP-compliant type hints. Ergo, we
                # obtain this attribute via a higher-level utility getter.
                hint_childs = get_hint_pep_args(hint_curr)

                # Number of these child hints.
                hint_childs_len = len(hint_childs)

                # ............{ DEEP ~ expression                  }............
                # If the expression yielding the current pith is neither...
                #
                # Note that we explicitly test against piths rather than
                # seemingly equivalent metadata to account for edge cases.
                # Notably, child hints of unions (and possibly other "typing"
                # objects) do *NOT* narrow the current pith and are *NOT* the
                # root hint. Ergo, a seemingly equivalent test like
                # "hints_meta_index_curr != 0" would generate false positives
                # and thus unnecessarily inefficient code.
                if not (
                    # The root pith *NOR*...
                    #
                    # Note that this is merely a negligible optimization for the
                    # common case in which the current pith is the root pith
                    # (i.e., this is the first iteration of the outermost loop).
                    # The subsequent call to the str.isidentifier() method is
                    # *MUCH* more expensive than this object identity test.
                    hints_meta.pith_curr_expr is VAR_NAME_PITH_ROOT or
                    # A simple Python identifier *NOR*...
                    hints_meta.pith_curr_expr.isidentifier() or
                    # A complex Python expression already containing the
                    # assignment expression-specific walrus operator ":=". Since
                    # this implies this expression to already be an assignment
                    # expression, needlessly reassigning the local variable to
                    # which this assignment expression was previously assigned
                    # as yet another redundant local variable only harms
                    # efficiency for *NO* tangible gain (e.g., expanding the
                    # efficient assignment expression "__beartype_pith_1 :=
                    # next(iter(__beartype_pith_0))" to the inefficient
                    # assignment expression "__beartype_pith_2 :=
                    # __beartype_pith_1 := next(iter(__beartype_pith_0))").
                    #
                    # Note that this edge case is induced by method calls
                    # performed below of the form:
                    #    hints_meta.enqueue_hint_child_sane(
                    #        ..., pith_expr=pith_curr_assign_expr, ...)
                    #
                    # As of this writing, the only such edge cases are:
                    # * PEP 484- or 604-compliant unions containing *ONLY* two
                    #   or more PEP-compliant type hints (e.g., "list[str] |
                    #   set[bytes]").
                    # * PEP 695-compliant subscripted type aliases.
                    ':=' in hints_meta.pith_curr_expr
                ):
                    # Then the current pith is ideally assigned to a unique
                    # local variable via an assignment expression.
                    # print(f'Incrementing hint {hint_curr} pith expression {pith_curr_expr}...')
                    # print(f'...index {pith_curr_var_name_index} by one.')

                    # Increment the integer suffixing the name of this variable
                    # *BEFORE* defining this variable.
                    hints_meta.pith_curr_var_name_index += 1

                    # Name of this local variable.
                    hints_meta.pith_curr_var_name = PITH_INDEX_TO_VAR_NAME[
                        hints_meta.pith_curr_var_name_index]

                    # Assignment expression assigning this full expression to
                    # this local variable.
                    hints_meta.pith_curr_assign_expr = (
                        CODE_PEP572_PITH_ASSIGN_EXPR_format(
                            pith_curr_var_name=hints_meta.pith_curr_var_name,
                            pith_curr_expr=hints_meta.pith_curr_expr,
                        ))
                # Else, the current pith is *NOT* safely assignable to a unique
                # local variable via an assignment expression. Since the
                # expression yielding the current pith is a simple Python
                # identifier, there is *NO* benefit to assigning that to another
                # local variable via another assignment expression, which would
                # just be an alias of the existing local variable assigned via
                # the existing assignment expression. Moreover, whereas chained
                # assignments are syntactically valid, chained assignment
                # expressions are syntactically invalid unless explicitly
                # protected by parens: e.g.,
                #     >>> a = b =    'Mother*Teacher*Destroyer'  # <-- fine
                #     >>> (a :=      "Mother's Abomination")     # <-- fine
                #     >>> (a :=
                #     ... (b := "Mother's Illumination"))        # <-- fine
                #     >>> (a := b := "Mother's Illumination")    # <-- not fine
                #     SyntaxError: invalid syntax
                #
                # In this case...
                else:
                    # print(f'Preserving hint {hint_curr} pith expression {pith_curr_expr}...')
                    # print(f'...index {pith_curr_var_name_index}.')

                    # Preserve the Python code snippet evaluating to the value
                    # of the current pith as is.
                    hints_meta.pith_curr_assign_expr = hints_meta.pith_curr_expr

                # ............{ UNION                              }............
                # If this hint is a union (e.g., "typing.Union[bool, str]",
                # typing.Optional[float]")...
                if hint_curr_sign in HINT_SIGNS_UNION:
                    # Python code snippet type-checking the current pith against
                    # this union if this union is unignorable *OR* "None".
                    make_hint_pep484604_check_expr(hints_meta)
                # Else, this hint is *NOT* a union.
                #
                # ..........{ CONTAINERS                           }............
                # If this hint is either:
                # * A single-argument container like list[int] or set[str].
                # * A similar hint semantically resembling a single-argument
                #   container subscripted by one argument and one or more
                #   ignorable arguments like tuple[str, ...].
                #
                # Then this hint is effectively (for all intents and purposes) a
                # standard single-argument container. In this case, generate a
                # Python code snippet type-checking the current pith against
                # this container hint.
                elif hint_curr_sign in HINT_SIGNS_CONTAINER_ARGS_1:
                    make_hint_pep484585_container_check_expr(hints_meta)
                # Else, this hint is *NOT* a standard single-argument container.
                #
                # ............{ SEQUENCES ~ tuple : fixed          }............
                # If this hint is a fixed-length tuple (e.g., "tuple[int,
                # str]")...
                #
                # Note that if this hint is a:
                # * PEP 484-compliant "typing.Tuple"-based hint, this hint is
                #   guaranteed to contain one or more child hints. Moreover, if
                #   this hint contains exactly one child hint that is the empty
                #   tuple, this hint is the empty fixed-length form
                #   "typing.Tuple[()]".
                # * PEP 585-compliant "tuple"-based hint, this hint is *NOT*
                #   guaranteed to contain one or more child hints. If this hint
                #   contains *NO* child hints, this hint is equivalent to the
                #   empty fixed-length PEP 484-compliant form
                #   "typing.Tuple[()]". Yes, PEP 585 even managed to violate
                #   PEP 484-compliance. UUUURGH!
                #
                # While tuples are sequences, the "typing.Tuple" singleton that
                # types tuples violates the syntactic norms established for
                # other standard sequences by concurrently supporting two
                # different syntaxes with equally different semantics:
                # * "typing.Tuple[{typename}, ...]", typing a tuple whose items
                #   all satisfy the "{typename}" child hint. Note that the
                #   "..." substring here is a literal ellipses.
                # * "typing.Tuple[{typename1}, {typename2}, ..., {typenameN}]",
                #   typing a tuple whose:
                #   * First item satisfies the "{typename1}" child hint.
                #   * Second item satisfies the "{typename2}" child hint.
                #   * Last item satisfies the "{typenameN}" child hint.
                #   Note that the "..." substring here is *NOT* a literal
                #   ellipses.
                #
                # This is what happens when unreadable APIs are promoted.
                elif hint_curr_sign is HintSignPep484585TupleFixed:
                    # Initialize the code type-checking this pith against this
                    # tuple to the substring prefixing all such code.
                    hints_meta.func_curr_code = CODE_PEP484585_TUPLE_FIXED_PREFIX

                    # If this hint is the empty fixed-length tuple, generate
                    # and append code type-checking the current pith to be the
                    # empty tuple. This edge case constitutes a code smell.
                    if is_hint_pep484585646_tuple_empty(hint_curr):
                        hints_meta.func_curr_code += (
                            CODE_PEP484585_TUPLE_FIXED_EMPTY_format(
                                pith_curr_var_name=hints_meta.pith_curr_var_name))
                    # Else, that ridiculous edge case does *NOT* apply. In this
                    # case...
                    else:
                        # Append code type-checking the length of this pith.
                        hints_meta.func_curr_code += (
                            CODE_PEP484585_TUPLE_FIXED_LEN_format(
                                pith_curr_var_name=hints_meta.pith_curr_var_name,
                                hint_childs_len=hint_childs_len,
                            ))

                        #FIXME: Optimize by refactoring into a "while" loop.
                        # For each possibly ignorable insane child hint of this
                        # parent tuple...
                        for hint_child_index, hint_child in enumerate(
                            hint_childs):
                            # Unignorable sane child hint sanified from this
                            # possibly ignorable insane child hint *OR* "None"
                            # otherwise (i.e., if this child hint is ignorable).
                            hint_child_sane = hints_meta.sanify_hint_child(
                                hint_child)  # type: ignore[arg-type]
                            # print(f'Sanified fixed tuple {hints_meta.hint_curr_meta}...')
                            # print(f'...child hint {hint_child} -> {hint_child_sane}!')

                            # If this child hint is unignorable...
                            if hint_child_sane is not HINT_SANE_IGNORABLE:
                                # Python expression yielding the value of the
                                # currently indexed item of this tuple to be
                                # type-checked against this child hint.
                                pith_child_expr = (
                                    CODE_PEP484585_TUPLE_FIXED_NONEMPTY_PITH_CHILD_EXPR_format(
                                        pith_curr_var_name=(
                                            hints_meta.pith_curr_var_name),
                                        pith_child_index=hint_child_index,
                                    ))

                                # Deeply type-check this child pith.
                                hints_meta.func_curr_code += (
                                    CODE_PEP484585_TUPLE_FIXED_NONEMPTY_CHILD_format(
                                        hint_child_placeholder=(
                                            hints_meta.enqueue_hint_child_sane(
                                                hint_sane=hint_child_sane,
                                                pith_expr=pith_child_expr,
                                            )
                                        ),
                                    ))
                            # Else, this child hint is ignorable.

                    # Munge this code to...
                    hints_meta.func_curr_code = (
                        # Strip the erroneous " and" suffix appended by the
                        # last child hint from this code.
                        f'{hints_meta.func_curr_code[:LINE_RSTRIP_INDEX_AND]}'
                        # Suffix this code by the substring suffixing all such
                        # code.
                        f'{CODE_PEP484585_TUPLE_FIXED_SUFFIX}'
                    # Format...
                    ).format(
                        indent_curr=hints_meta.indent_curr,
                        pith_curr_assign_expr=hints_meta.pith_curr_assign_expr,
                    )
                # Else, this hint is *NOT* a fixed-length tuple.
                #
                # ..........{ MAPPINGS                             }............
                # If this hint is a standard mapping (e.g., "dict[str, int]")...
                elif hint_curr_sign in HINT_SIGNS_MAPPING:
                    # Python expression evaluating to the origin type of this
                    # mapping hint as a hidden beartype-specific parameter
                    # injected into the signature of this wrapper function.
                    hints_meta.hint_curr_expr = (
                        hints_meta.add_func_scope_type_or_types(
                            get_hint_pep_origin_type_isinstanceable(hint_curr)))

                    # 2-tuple of the possibly ignorable insane child key and
                    # value hints subscripting this mapping hint, defined as
                    # either...
                    hint_childs = (
                        #FIXME: Note that a similar effect can also be achieved
                        #through a reduction from type hints the form
                        #"{collections,typing}.Counter[{hint_child}]" to:
                        #    typing.Annotated[
                        #        collections.abc.MutableMapping[{hint_child}, int],
                        #        beartype.vale.IsInstance[collections.Counter]
                        #    ]
                        #However, the current approach is even *MORE* trivial
                        #than that reduction. So, we currently prefer this.

                        # If this hint describes a "collections.Counter"
                        # dictionary subclass:
                        # * The "typing.Counter[...]" type hint factory is
                        #   subscriptable by only a single key child type hint
                        #   and assumes the value child type hint typically
                        #   subscripting dictionary type hint factories to be
                        #   the standard "int" type (e.g., "typing.Counter[str]"
                        #   effectively expands to "typing.Counter[str, int]").
                        # * The "collections.Counter[...]" type hint factory is
                        #   technically subscriptable by an arbitrary number of
                        #   child type hints but pragmatically subscriptable by
                        #   only a single key child type hint. Why? Static
                        #   type-checkers, which enforce that constraint.
                        #
                        # Despite these type-checking assumptions and
                        # constraints, the "collections.Counter" type is itself
                        # unconstrained. As of Python 3.13, the
                        # collections.Counter.__init__() initializer accepts
                        # arbitrary values that are *NOT* integers: e.g.,
                        #     >>> from collections import Counter
                        #     >>> c = Counter({'red': 'no, blue!', 'blue': 4.2})
                        #     >>> print(c)
                        #     Counter({'red': 'no, blue!', 'blue': 4.2})  # lol
                        #
                        # That permissiveness arguably constitutes a bug in both
                        # CPython itself *AND* user code attempting such
                        # shenanigans. Static type-checkers believe this to be
                        # the case, anyway -- and that's good enough for us.
                        # @beartype thus explicitly catches these bugs by
                        # defaulting the undeclared value child type hint for
                        # counter type hints to be the "int" type.
                        (
                            get_hint_pep484585_arg(
                                hint=hint_curr,
                                exception_prefix=EXCEPTION_PREFIX,
                            ),
                            int,
                        )
                        if hint_curr_sign is HintSignCounter else
                        # Else, this hint does *NOT* describe a
                        # "collections.Counter" dictionary subclass. In this
                        # case, introspect the child key and value type hints
                        # subscripting this parent hint in the standard way.
                        get_hint_pep484585_args(  # type: ignore[assignment]
                            hint=hint_curr,
                            args_len=2,
                            exception_prefix=EXCEPTION_PREFIX,
                        )
                    )

                    #FIXME: Consider also contextually considering child key
                    #hints that reduce to "Hashable" to be ignorable. This
                    #includes complex type hints like "Union[Hashable, str]",
                    #which reduces to "Hashable". We can't particularly be
                    #bothered at the moment. This is a microoptimization and
                    #will probably require a non-trivial amount of work. *sigh*
                    # Unignorable sane child key and value hints sanified from
                    # these possibly ignorable insane child key and value hints
                    # *OR* "None" otherwise (i.e., if ignorable).
                    hint_child_sane_key = hints_meta.sanify_hint_child(
                        hint_childs[0])
                    hint_child_sane_value = hints_meta.sanify_hint_child(
                        hint_childs[1])

                    # If at least one of these child hints are unignorable...
                    if not (
                        hint_child_sane_key   is HINT_SANE_IGNORABLE and
                        hint_child_sane_value is HINT_SANE_IGNORABLE
                    ):
                        # If this child key hint is unignorable...
                        if hint_child_sane_key is not HINT_SANE_IGNORABLE:
                            # If this child value hint is also unignorable...
                            if hint_child_sane_value is not HINT_SANE_IGNORABLE:
                                # Increase the indentation level of code
                                # type-checking this child value pith.
                                hints_meta.indent_level_child += 1

                                # Increment the integer suffixing the name of a
                                # unique local variable storing the value of
                                # this child key pith *BEFORE* defining this
                                # variable.
                                hints_meta.pith_curr_var_name_index += 1

                                # Name of this local variable.
                                pith_key_var_name = PITH_INDEX_TO_VAR_NAME[
                                    hints_meta.pith_curr_var_name_index]

                                # Placeholder string to be subsequently replaced
                                # by code type-checking this child key pith
                                # against this hint.
                                hint_key_placeholder = (
                                    hints_meta.enqueue_hint_child_sane(
                                        hint_sane=hint_child_sane_key,
                                        pith_expr=pith_key_var_name,
                                    ))

                                # Placeholder string to be subsequently replaced
                                # by code type-checking this child value pith
                                # against this hint.
                                hint_value_placeholder = (
                                    hints_meta.enqueue_hint_child_sane(
                                        hint_sane=hint_child_sane_value,
                                        pith_expr=CODE_PEP484585_MAPPING_KEY_VALUE_PITH_CHILD_EXPR_format(
                                            pith_curr_var_name=(
                                                hints_meta.pith_curr_var_name),
                                            pith_key_var_name=pith_key_var_name,
                                        ),
                                    ))

                                # Code deeply type-checking these child key and
                                # value piths against these hints.
                                func_curr_code_key_value = (
                                    CODE_PEP484585_MAPPING_KEY_VALUE_format(
                                        indent_curr=hints_meta.indent_curr,
                                        pith_key_var_name=pith_key_var_name,  # pyright: ignore
                                        pith_curr_var_name=(
                                            hints_meta.pith_curr_var_name),
                                        hint_key_placeholder=(
                                            hint_key_placeholder),
                                        hint_value_placeholder=(
                                            hint_value_placeholder),
                                    ))
                            # Else, this child value hint is ignorable. In this
                            # case...
                            else:
                                # Code deeply type-checking only this child key
                                # pith against this hint.
                                func_curr_code_key_value = (
                                    CODE_PEP484585_MAPPING_KEY_ONLY_format(
                                        indent_curr=hints_meta.indent_curr,
                                        # Placeholder string to be subsequently
                                        # replaced by code type-checking this
                                        # child key pith against this hint.
                                        hint_key_placeholder=(
                                            hints_meta.enqueue_hint_child_sane(
                                                hint_sane=hint_child_sane_key,
                                                pith_expr=CODE_PEP484585_MAPPING_KEY_ONLY_PITH_CHILD_EXPR_format(
                                                    pith_curr_var_name=(
                                                        hints_meta.pith_curr_var_name)),
                                            )
                                        ),
                                    )
                                )
                        # Else, this child key hint is ignorable. By process
                        # of elimination, this child value hint *MUST* be
                        # unignorable. In this case...
                        else:
                            # Code deeply type-checking only this child value
                            # pith against this hint.
                            func_curr_code_key_value = (
                                CODE_PEP484585_MAPPING_VALUE_ONLY_format(
                                    indent_curr=hints_meta.indent_curr,
                                    # Placeholder string to be subsequently
                                    # replaced by code type-checking this
                                    # child value pith against this hint.
                                    hint_value_placeholder=(
                                        hints_meta.enqueue_hint_child_sane(
                                            hint_sane=hint_child_sane_value,
                                            pith_expr=CODE_PEP484585_MAPPING_VALUE_ONLY_PITH_CHILD_EXPR_format(
                                                pith_curr_var_name=(
                                                    hints_meta.pith_curr_var_name)),
                                        )
                                    ),
                                )
                            )

                        # Code deeply type-checking this pith as well as at
                        # least one of these child key and value piths.
                        hints_meta.func_curr_code = CODE_PEP484585_MAPPING_format(
                            indent_curr=hints_meta.indent_curr,
                            pith_curr_assign_expr=hints_meta.pith_curr_assign_expr,
                            pith_curr_var_name=hints_meta.pith_curr_var_name,
                            hint_curr_expr=hints_meta.hint_curr_expr,
                            func_curr_code_key_value=func_curr_code_key_value,
                        )
                    # Else, these child key *AND* value hints are both
                    # ignorable. In this case, fallback to trivial code
                    # shallowly type-checking this pith as an instance of this
                    # origin type.
                # Else, this hint is *NOT* a mapping.
                #
                # ............{ PEP 593 ~ typing.Annotated[...]    }............
                # If this hint is a PEP 593-compliant type metahint, this
                # metahint is guaranteed by the reduction performed above to be
                # beartype-specific (i.e., metahint whose second argument is a
                # beartype validator produced by subscripting a beartype
                # validator factory). In this case...
                elif hint_curr_sign is HintSignAnnotated:
                    # Defer heavyweight imports.
                    from beartype.vale._core._valecore import BeartypeValidator

                    # Initialize the code type-checking this pith against this
                    # metahint to the substring prefixing all such code.
                    hints_meta.func_curr_code = CODE_PEP593_VALIDATOR_PREFIX

                    # Unignorable sane metahint annotating this parent hint
                    # sanified from this possibly ignorable insane metahint *OR*
                    # "None" otherwise (i.e., if this metahint is ignorable).
                    hint_child_sane = hints_meta.sanify_hint_child(
                        get_hint_pep593_metahint(hint_curr))
                    # print(f'[593] metahint: {repr(get_hint_pep593_metahint(hint_curr))}')
                    # print(f'[593] hint_curr_meta: {repr(hints_meta.hint_curr_meta)}')
                    # print(f'[593] hint_curr: {repr(hint_curr)}; hint_child_sane: {repr(hint_child_sane)}')

                    # Tuple of the one or more beartype validators annotating
                    # this metahint.
                    hints_child = get_hint_pep593_metadata(hint_curr)
                    # print(f'hints_child: {repr(hints_child)}')

                    # If this metahint is ignorable...
                    if hint_child_sane is HINT_SANE_IGNORABLE:
                        # Expression yielding the value of the current pith,
                        # defined as either...
                        hint_curr_expr = (
                            hints_meta.pith_curr_expr
                            # If this metahint is annotated by only one beartype
                            # validator, the most efficient expression yielding
                            # the value of the current pith is simply the full
                            # Python expression *WITHOUT* assigning that value
                            # to a reusable local variable in an assignment
                            # expression. *NO* assignment expression is needed
                            # in this case.
                            #
                            # Why? Because beartype validators are *NEVER*
                            # recursed into. Each beartype validator is
                            # guaranteed to be the leaf of a type-checking
                            # subtree, guaranteeing this pith to be evaluated
                            # only once.
                            if len(hints_child) == 1 else
                            # Else, this metahint is annotated by two or more
                            # beartype validators. In this case, the most
                            # efficient expression yielding the value of the
                            # current pith is the assignment expression
                            # assigning this value to a reusable local variable.
                            hints_meta.pith_curr_assign_expr
                        )
                    # Else, this metahint is unignorable. In this case...
                    else:
                        # Python expression yielding the value of the current
                        # pith, defaulting to the name of the local variable
                        # assigned to by the assignment expression performed
                        # below.
                        hint_curr_expr = hints_meta.pith_curr_var_name

                        # Code deeply type-checking this metahint.
                        hints_meta.func_curr_code += (
                            CODE_PEP593_VALIDATOR_METAHINT_format(
                                indent_curr=hints_meta.indent_curr,
                                # Python expression yielding the value of the
                                # current pith assigned to a local variable
                                # efficiently reused by code generated by the
                                # following iteration.
                                #
                                # Note this child hint is guaranteed to be followed
                                # by at least one more test expression referencing
                                # this local variable. Why? Because the "typing"
                                # module forces metahints to be subscripted by one
                                # child hint and one or more arbitrary objects.
                                # Ergo, we need *NOT* explicitly validate that here.
                                hint_child_placeholder=(
                                    hints_meta.enqueue_hint_child_sane(
                                        hint_sane=hint_child_sane,
                                        pith_expr=hints_meta.pith_curr_assign_expr,
                                    )
                                ),
                            )
                        )

                    #FIXME: Optimize by refactoring into a "while" loop. *sigh*
                    # For the 0-based index and each beartype validator
                    # annotating this metahint...
                    for hint_child_index, hint_child in enumerate(hints_child):
                        # print(f'Type-checking PEP 593 type hint {repr(hint_curr)} argument {repr(hint_child)}...')
                        # If this is *NOT* a beartype validator, raise an
                        # exception.
                        #
                        # Note that the previously called sanify_hint_child()
                        # function validated only the first such to be a
                        # beartype validator. All remaining arguments have yet
                        # to be validated, so we do so now for consistency and
                        # safety.
                        if not isinstance(hint_child, BeartypeValidator):
                            raise BeartypeDecorHintPep593Exception(
                                f'{EXCEPTION_PREFIX}PEP 593 type hint '
                                f'{repr(hint_curr)} subscripted by both '
                                f'@beartype-specific and -agnostic metadata '
                                f'(i.e., {represent_object(hint_child)} not '
                                f'beartype validator).'
                            )
                        # Else, this argument is beartype-specific.
                        #
                        # If this is any beartype validator *EXCEPT* the first,
                        # set the Python expression yielding the value of the
                        # current pith to the name of the local variable
                        # assigned to by the prior assignment expression. By
                        # deduction, it *MUST* be the case now that either:
                        # * This metahint was unignorable, in which case this
                        #   assignment uselessly reduplicates the exact same
                        #   assignment performed above. While non-ideal, this
                        #   assignment is sufficiently efficient to make any
                        #   optimizations here effectively worthless.
                        # * This metahint was ignorable, in which case this
                        #   expression was set above to the assignment
                        #   expression assigning this pith for the first
                        #   beartype validator. Since this iteration has already
                        #   processed the first beartype validator, this
                        #   assignment expression has already been performed.
                        #   Avoid inefficiently re-performing this assignment
                        #   expression for each additional beartype validator by
                        #   efficiently reusing the previously assigned local.
                        elif hint_child_index:
                            hint_curr_expr = hints_meta.pith_curr_var_name
                        # Else, this is the first beartype validator. See above.

                        # Code deeply type-checking this validator.
                        hints_meta.func_curr_code += CODE_PEP593_VALIDATOR_IS_format(
                            indent_curr=hints_meta.indent_curr,
                            # Python expression formatting the current pith into
                            # the "{obj}" format substring previously embedded
                            # by this validator into this code string.
                            hint_child_expr=hint_child._is_valid_code.format(
                                indent=hints_meta.indent_child,
                                obj=hint_curr_expr,
                            ),
                        )

                        # Generate locals safely merging the locals required by
                        # both this validator code *AND* the current code
                        # type-checking this entire root hint.
                        update_mapping(
                            mapping_trg=hints_meta.func_wrapper_scope,
                            mapping_src=hint_child._is_valid_code_locals,
                        )

                    # Munge this code to...
                    hints_meta.func_curr_code = (
                        # Strip the erroneous " and" suffix appended by the
                        # last child hint from this code.
                        f'{hints_meta.func_curr_code[:LINE_RSTRIP_INDEX_AND]}'
                        # Suffix this code by the substring suffixing all such
                        # code.
                        f'{CODE_PEP593_VALIDATOR_SUFFIX_format(indent_curr=hints_meta.indent_curr)}'
                    )
                # Else, this hint is *NOT* a metahint.
                #
                # ............{ SUBCLASS                           }............
                # If this hint is either a PEP 484- or 585-compliant subclass
                # type hint...
                elif hint_curr_sign is HintSignType:
                    # Metadata encapsulating the sanification of this possibly
                    # insane child hint.
                    hint_child_sane = hints_meta.sanify_hint_child(
                        # Possibly ignorable insane child hint subscripting
                        # this parent hint, validated to be the *ONLY* child
                        # hint subscripting this parent hint.
                        get_hint_pep484585_arg(
                            hint=hint_curr,
                            exception_prefix=hints_meta.exception_prefix,
                        )
                    )

                    # If this child hint is unignorable...
                    if hint_child_sane is not HINT_SANE_IGNORABLE:
                        # Child hint encapsulated by this metadata.
                        hint_child = hint_child_sane.hint

                        # Sign identifying this child hint.
                        hint_child_sign = get_hint_pep_sign_or_none(hint_child)

                        # If this child hint is a forward reference to a
                        # superclass, expose this forward reference to the body
                        # of this wrapper function. See above for commentary.
                        if hint_child_sign is HintSignForwardRef:
                            (
                                hint_curr_expr,
                                hint_refs_type_basename,
                            ) = express_func_scope_type_ref(
                                forwardref=hint_child,  # type: ignore[arg-type]
                                refs_type_basename=hint_refs_type_basename,
                                func_scope=hints_meta.func_wrapper_scope,
                                exception_prefix=EXCEPTION_PREFIX,
                            )
                        # Else, this child hint is *NOT* a forward reference. In
                        # this case...
                        else:
                            # If this child hint is a union of superclasses,
                            # reduce this union to a tuple of superclasses. Only
                            # the latter is safely passable as the second
                            # parameter to the issubclass() builtin under all
                            # supported Python versions.
                            if hint_child_sign is HintSignUnion:
                                hint_child = get_hint_pep_args(hint_child)
                            # Else, this child hint is *NOT* a union.

                            # If this child hint is *NOT* an issubclassable
                            # object, raise an exception.
                            #
                            # Note that the is_object_issubclassable() tester is
                            # considerably faster and thus called before the
                            # considerably slower
                            # die_unless_object_issubclassable() raiser.
                            if not is_object_issubclassable(hint_child):  # type: ignore[arg-type]
                                die_unless_object_issubclassable(
                                    obj=hint_child,  # type: ignore[arg-type]
                                    exception_prefix=(
                                        f'{EXCEPTION_PREFIX}PEP 484 or 585 '
                                        f'subclass type hint {repr(hint_curr)} '
                                        f'child type hint '
                                    ),
                                )
                            # Else, this child hint is an issubclassable object.

                            # Python expression evaluating to this child hint.
                            hint_curr_expr = hints_meta.add_func_scope_type_or_types(
                                hint_child)  # type: ignore[arg-type]

                        # Code type-checking this pith against this superclass.
                        hints_meta.func_curr_code = CODE_PEP484585_SUBCLASS_format(
                            pith_curr_assign_expr=hints_meta.pith_curr_assign_expr,
                            pith_curr_var_name=hints_meta.pith_curr_var_name,
                            hint_curr_expr=hint_curr_expr,
                            indent_curr=hints_meta.indent_curr,
                        )
                    # Else, this child hint is ignorable. In this case...
                    else:
                        # Python expression evaluating to the origin type of
                        # this hint -- which, by definition, is the "type"
                        # superclass. Since this superclass is a builtin (i.e.,
                        # universally accessible object), we efficiently
                        # hardcode the access of this superclass rather than
                        # inject a hidden beartype-specific parameter into the
                        # signature of this wrapper function as we usually do.
                        hints_meta.hint_curr_expr = 'type'

                        # Fallback to trivial code shallowly type-checking this
                        # pith as an instance of this origin type.
                # Else, this hint is *NOT* a subclass type hint.
                #
                # ............{ GENERIC or PROTOCOL                }............
                # If this hint is an unsubscripted generic, generate a Python
                # code snippet type-checking the current pith against this
                # unsubscripted generic.
                elif hint_curr_sign is HintSignPep484585GenericUnsubbed:
                    make_hint_pep484585_generic_unsubbed_check_expr(hints_meta)
                # Else, this hint is *NOT* an unsubscripted generic.
                #
                # ............{ PEP 484 ~ typing.TypeVar(...)      }............
                # If this hint is a PEP 484-compliant type variable (i.e.,
                # "typing.TypeVar" object), this hint is both dependent on and
                # less common than .PEP 484- and 585-compliant generics and thus
                # intentionally detected immediately after generics. In this
                # case...

                #FIXME: Preserved for posterity, once we begin generating
                #call-time type variable type-checking.
                #FIXME: Unit test us up, please.
                #FIXME: Implement corresponding "beartype._check.error"
                #validation, please. *sigh*
                # elif hint_curr_sign is HintSignTypeVar:
                #     # Either the unignorable hint this type variable reduces to
                #     # if any *OR* "None" if this type variable is ignorable.
                #     hint_child = make_hint_pep484_typevar_check_expr(  # type: ignore[assignment]
                #         hint_meta=hint_curr_meta,
                #         conf=conf,
                #         pith_curr_assign_expr=pith_curr_assign_expr,
                #         pith_curr_var_name_index=pith_curr_var_name_index,
                #         cls_stack=cls_stack,
                #         exception_prefix=EXCEPTION_PREFIX,
                #     )
                #
                #     # If this type variable is reducible to an unignorable
                #     # hint, revisit this hint metadata in the outermost "while"
                #     # loop. Doing so avoids the "CLEANUP" logic below, which
                #     # assumes this hint to be unignorable and thus
                #     # type-checkable.
                #     if hint_child is not None:
                #         continue
                #     # Else, this type variable is *NOT* reducible to an
                #     # unignorable hint. Since @beartype currently fails to
                #     # generate type-checking code for type variables in and of
                #     # themselves, type variables have *NO* intrinsic semantic
                #     # meaning and are thus ignorable. In this case, prepare this
                #     # BFS to visit the next enqueued hint by incrementing the
                #     # 0-based index of metadata describing the next visited hint
                #     # in the "hints_meta" list *BEFORE* visiting that hint.
                #     else:
                #         #FIXME: Insufficient. The parent type hint thought this
                #         #type variable was unignorable and thus... ugh.
                #         hints_meta_index_curr += 1
                # ............{ PEP 586 ~ typing.Literal[...]      }............
                # If this hint is a PEP 586-compliant type hint (i.e., the
                # "typing.Literal" type hint factory subscripted by one or more
                # literal objects), this hint is largely useless and thus
                # intentionally detected late. Why? Because "typing.Literal" is
                # subscriptable by objects that are instances of only *SIX*
                # possible types, which is sufficiently limiting as to render
                # this singleton patently absurd and a farce that we weep to
                # even implement. In this case...
                elif hint_curr_sign is HintSignLiteral:
                    # Tuple of zero or more literal objects subscripting this
                    # hint, intentionally replacing the current such tuple due
                    # to the non-standard implementation of the third-party
                    # "typing_extensions.Literal" type hint factory.
                    hint_childs = get_hint_pep586_literals(
                        hint=hint_curr, exception_prefix=EXCEPTION_PREFIX)

                    # Initialize the code type-checking this pith against this
                    # hint to the substring prefixing all such code.
                    hints_meta.func_curr_code = CODE_PEP586_PREFIX_format(
                        pith_curr_assign_expr=hints_meta.pith_curr_assign_expr,

                        #FIXME: If "typing.Literal" is ever extended to support
                        #substantially more types (and thus actually becomes
                        #useful), optimize the construction of the "types" set
                        #below to instead leverage a similar
                        #"acquire_instance(set)" caching solution as that
                        #currently employed for unions. For now, we only shrug.

                        # Python expression evaluating to a tuple of the unique
                        # types of all literal objects subscripting this hint.
                        hint_child_types_expr=hints_meta.add_func_scope_type_or_types({
                            #FIXME: Optimize by refactoring into a "while"
                            #loop. Also, this should probably be a "frozenset"
                            #rather than "set". *sigh*
                            # Set comprehension of all unique literal objects
                            # subscripting this hint, implicitly discarding all
                            # duplicate such objects.
                            type(hint_child) for hint_child in hint_childs}),
                    )

                    #FIXME: Optimize by refactoring into a "while" loop. *sigh*
                    # For each literal object subscripting this hint...
                    for hint_child in hint_childs:
                        # Generate and append efficient code type-checking
                        # this data validator by embedding this code as is.
                        hints_meta.func_curr_code += CODE_PEP586_LITERAL_format(
                            pith_curr_var_name=hints_meta.pith_curr_var_name,
                            # Python expression evaluating to this object.
                            hint_child_expr=add_func_scope_attr(
                                attr=hint_child,
                                func_scope=hints_meta.func_wrapper_scope,
                                exception_prefix=(
                                    EXCEPTION_PREFIX_FUNC_WRAPPER_LOCAL),
                            ),
                        )

                    # Munge this code to...
                    hints_meta.func_curr_code = (
                        # Strip the erroneous " or" suffix appended by the last
                        # child hint from this code.
                        f'{hints_meta.func_curr_code[:LINE_RSTRIP_INDEX_OR]}'
                        # Suffix this code by the appropriate substring.
                        f'{CODE_PEP586_SUFFIX}'
                    ).format(indent_curr=hints_meta.indent_curr)
                # Else, this hint is *NOT* a PEP 586-compliant type hint.
                #
                # ............{ PEP 589 ~ typing.TypeDict(...)     }............
                # If this hint is a PEP 589-compliant type hint (i.e., a
                # subclass of the "typing.TypeDict" superclass), this hint is...
                #FIXME: *CURRENTLY UNSUPPORTED.* We should eventually generate
                #proper type-checking code for typed dictionaries. At the
                #moment, this condition is true only for the single obscure edge
                #case of typed dictionary generics, resembling:
                #    class UserTypedDict(TypedDict, Generic[T]): ...
                #
                #When such a subclass is used as a type hint, the
                #get_hint_pep484585_generic_unsubbed_bases_unerased() detects
                #"TypeDict" to be an extrinsic pseudo-superclass and then yields
                #both the typed dictionary generic itself (e.g., "UserTypedDict"
                #above) *AND* "HintSignTypedDict", which then causes this
                #condition here to be triggered.
                #
                #This condition will suddenly become relevant when we remove the
                #reduce_hint_pep589() reducer.
                #FIXME: Actually, let's hold off on this until we need it! \o/
                # elif hint_curr_sign is HintSignTypedDict:
                #     pass
                # ............{ UNSUPPORTED                        }............
                # Else, this hint is neither shallowly nor deeply supported and
                # is thus unsupported. Since an exception should have already
                # been raised above in this case, this conditional branch
                # *NEVER* be triggered. Nonetheless, raise an exception.
                else:
                    raise BeartypeDecorHintPepUnsupportedException(
                        f'{EXCEPTION_PREFIX_HINT}'
                        f'{repr(hint_curr)} unsupported but '
                        f'erroneously detected as supported under '
                        f'beartype sign {repr(hint_curr_sign)}.'
                    )

        # ................{ NON-PEP                            }................
        # Else, this hint is *NOT* PEP-compliant.
        #
        # ................{ NON-PEP ~ type                     }................
        # If this hint is a non-"typing" class...
        #
        # Note that:
        # * This test is intentionally performed *AFTER* that testing whether
        #   this hint is PEP-compliant, thus guaranteeing this hint to be a
        #   PEP-noncompliant non-"typing" class rather than a PEP-compliant
        #   type hint originating from such a class. Since many hints are both
        #   PEP-compliant *AND* originate from such a class (e.g., the "List"
        #   in "List[int]", PEP-compliant but originating from the
        #   PEP-noncompliant builtin class "list"), testing these hints first
        #   for PEP-compliance ensures we generate non-trivial code deeply
        #   type-checking these hints instead of trivial code only shallowly
        #   type-checking the non-"typing" classes from which they originate.
        # * This class is guaranteed to be a subscripted argument of a
        #   PEP-compliant type hint (e.g., the "int" in "Union[Dict[str, str],
        #   int]") rather than the root type hint. Why? Because if this class
        #   were the root type hint, it would have already been passed into a
        #   faster submodule generating PEP-noncompliant code instead.
        elif isinstance(hint_curr, type):
            # Python expression evaluating to this type.
            hints_meta.hint_curr_expr = hints_meta.add_func_scope_type_or_types(
                hint_curr)
        # ................{ NON-PEP ~ bad                      }................
        # Else, this hint is neither PEP-compliant *NOR* a class. In this case,
        # raise an exception. Note that:
        # * This should *NEVER* happen, as the "typing" module goes to great
        #   lengths to validate the integrity of PEP-compliant types at
        #   declaration time.
        # * The higher-level die_unless_hint_nonpep() validator is
        #   intentionally *NOT* called here, as doing so would permit both:
        #   * PEP-noncompliant forward references, which could admittedly be
        #     disabled by passing "is_forwardref_valid=False" to that call.
        #   * PEP-noncompliant tuple unions, which currently *CANNOT* be
        #     disabled by passing such an option to that call.
        else:  # pragma: no cover
            die_as_hint_unsupported(
                hint=hint_curr, exception_prefix=EXCEPTION_PREFIX_HINT)

        # ................{ CLEANUP                            }................
        # If prior logic generated *NO* code snippet type-checking the current
        # pith against the currently visited hint.
        if hints_meta.func_curr_code is None:
            # Assert that a branch above defined the code snippet used below.
            assert hints_meta.hint_curr_expr is not None, (
                f'{EXCEPTION_PREFIX_HINT}'
                f'{repr(hint_curr)} expression undefined.'
            )

            # Fall back to a trivial code snippet shallowly type-checking this
            # pith as an instance of the origin type of this hint.
            hints_meta.func_curr_code = CODE_PEP484_INSTANCE_format(
                hint_curr_expr=hints_meta.hint_curr_expr,
                pith_curr_expr=hints_meta.pith_curr_expr,
            )
        # Else, prior logic generated a code snippet type-checking the current
        # pith against the currently visited hint. Preserve this snippet.

        # Inject this code into the body of this wrapper.
        func_wrapper_code = replace_str_substrs(
            text=func_wrapper_code,
            old=hints_meta.hint_curr_meta.hint_placeholder,
            new=hints_meta.func_curr_code,
        )

        # Nullify the previously visited hint in this list, avoiding spurious
        # memory leaks by encouraging garbage collection.
        hints_meta[hints_meta_index_curr] = None

        # Increment the 0-based index of metadata describing the next visited
        # hint in this list *BEFORE* visiting that hint (but *AFTER* performing
        # all other logic for the currently visited hint).
        hints_meta_index_curr += 1

    # ..................{ CLEANUP                            }..................
    # Release the fixed list of all such metadata.
    release_instance(hints_meta)

    # If the Python code snippet to be returned remains unchanged from its
    # initial value, the breadth-first search above failed to generate code. In
    # this case, raise an exception.
    #
    # Note that:
    # * This should *NEVER* happen. Nonetheless, this just happened.
    # * This test is inexpensive, as the third character of the "func_root_code"
    #   code snippet is guaranteed to differ from that of "func_wrapper_code"
    #   code snippet if this function behaved as expected, which it should
    #   have... but may not have. This is why we're testing.
    if func_wrapper_code == func_root_code:
        raise BeartypeDecorHintPepException(
            f'{EXCEPTION_PREFIX_HINT}{repr(hint_sane)} unchecked.')
    # Else, the breadth-first search above successfully generated code.

    # ..................{ CODE ~ scope                       }..................
    # If type-checking for the root pith requires a pseudo-random integer, pass
    # a hidden parameter to this wrapper function exposing the
    # random.getrandbits() function required to generate this integer.
    if hints_meta.is_var_random_int_needed:
        hints_meta.func_wrapper_scope[ARG_NAME_GETRANDBITS] = getrandbits
    # Else, type-checking for the root pith requires *NO* pseudo-random integer.

    # ..................{ CODE ~ suffix                      }..................
    # Tuple of the unqualified classnames referred to by all relative forward
    # references visitable from this hint converted from that set to reduce
    # space consumption after memoization by @callable_cached, defined as...
    hint_refs_type_basename_tuple = (
        # If *NO* relative forward references are visitable from this root
        # hint, the empty tuple;
        ()
        if hint_refs_type_basename is None else
        # Else, that set converted into a tuple.
        tuple(hint_refs_type_basename)
    )
    # print(f'func_wrapper_scope: {hints_meta.func_wrapper_scope}')

    # Return all metadata required by higher-level callers.
    return (
        func_wrapper_code,
        hints_meta.func_wrapper_scope,
        hint_refs_type_basename_tuple,
    )
