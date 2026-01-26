#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **abstract syntax tree (AST) getters** (i.e., low-level callables
acquiring various properties of various nodes in the currently visited AST).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from ast import (
    AST,
    Attribute,
    Expr,
    Name,
    dump as ast_dump,
)
from beartype.typing import Optional
from beartype._data.typing.datatyping import ListStrs

# ....................{ GETTERS                            }....................
#FIXME: Unit test us up, please.
def get_node_repr_indented(node: AST) -> str:
    '''
    Human-readable string pretty-printing the contents of the passed abstract
    syntax tree (AST), complete with readable indentation.

    Parameters
    ----------
    node : AST
        AST to be pretty-printed.

    Returns
    -------
    str
        Human-readable string pretty-printing the contents of this AST.
    '''
    assert isinstance(node, AST), f'{repr(node)} not AST.'

    # Return the pretty-printed contents of this AST.
    return ast_dump(node, indent=4)  # type: ignore[call-arg]

# ....................{ GETTERS ~ attr                     }....................
#FIXME: This getter could be significantly optimized. Rather than deferring to
#get_node_attr_basenames(), this getter could instead re-implement the subset of
#get_node_attr_basenames() relevant to retrieving *ONLY* the first basename.
#Doing so avoids the need for a passed "attr_basenames" list entirely. Although
#largely trivial, this optimization is currently largely unnecessary. Why?
#Because this getter is only called sporadically for outlier edge cases. *shrug*
def get_node_attr_basename_first(
    # Mandatory parameters.
    node: AST,

    # Optional parameters.
    attr_basenames: Optional[ListStrs] = None,
) -> Optional[str]:
    '''
    First unqualified basename prefixing the possibly fully-qualified
    ``"."``-delimited name of the passed **attribute name node** (i.e.,
    :class:`ast.Name` node *or* hierarchical nesting of one or more
    :class:`ast.Attribute` nodes terminating in a :class:`ast.Name` node) if
    this node is parsable by this getter *or* :data:`None` otherwise (i.e., if
    this node is unparsable by this getter).

    Parameters
    ----------
    node : AST
        Attribute name node to be unparsed.
    attr_basenames : Optional[ListStrs], default: None
        Existing caller-defined list to be efficiently cleared, reused, and
        returned by this getter if any *or* :data:`None` otherwise, in which
        case this getter instantiates and returns a new list.

    Returns
    -------
    str
        First unqualified basename prefixing the possibly fully-qualified
        ``"."``-delimited name of this attribute name node.

    See Also
    --------
    :func:`.get_node_attr_basenames`
        Further details.
    '''

    # List of the one or more unqualified basenames comprising the possibly
    # fully-qualified "."-delimited name of this attribute name node if this
    # node is parsable by this getter *OR* the empty list otherwise.
    node_attr_basenames = get_node_attr_basenames(
        node=node, attr_basenames=attr_basenames)

    # Return either the first item of this list if this list is non-empty *OR*
    # "None" otherwise (i.e., if this list is empty).
    return node_attr_basenames[0] if node_attr_basenames else None


#FIXME: Unit test us up, please.
def get_node_attr_basenames(
    # Mandatory parameters.
    node: AST,

    # Optional parameters.
    attr_basenames: Optional[ListStrs] = None,
) -> ListStrs:
    '''
    List of the one or more unqualified basenames comprising the possibly
    fully-qualified ``"."``-delimited name of the passed **attribute name node**
    (i.e., :class:`ast.Name` node *or* hierarchical nesting of one or more
    :class:`ast.Attribute` nodes terminating in a :class:`ast.Name` node) if
    this node is parsable by this getter *or* the empty list otherwise (i.e., if
    this node is unparsable by this getter).

    This getter recursively "unparses" (i.e., decompiles) the hierarchically
    nested contents of this node, albeit without actually employing recursion.
    This getter instead internally iterates over a list of the one or more
    unqualified basenames comprising this name, enabling this iteration to
    reconstruct this name.

    A list is required, as the AST grammar hierarchically nests zero or more
    :class:`.Attribute` nodes encapsulating this name in the *reverse* order of
    the expected nesting. Specifically, an attribute name qualified by N number
    of ``"."``-delimited substrings (where N >= 3) is encapsulated by a
    hierarchical nesting of N-1 :class:`.Attribute` nodes followed by 1
    :class:`.Name` node: e.g.,

    .. code-block:: python

       @package.module.submodule.decorator
       def muh_fun(): pass

    ...which is encapsulated by this AST:

    .. code-block:: python

       FunctionDef(
           name='muh_fun',
           args=arguments(),
           body=[
               Pass()],
           decorator_list=[
               Attribute(
                   value=Attribute(
                       value=Attribute(
                           value=Name(id='package', ctx=Load()),
                           attr='module',
                           ctx=Load()),
                       attr='submodule',
                       ctx=Load()),
                   attr='decorator',
                   ctx=Load()),
           ])

    That is, the :class:`.attr` instance variable of the *outermost*
    :class:`Attribute` node yields the *last* ``"."``-delimited substring of the
    fully-qualified name of that decorator. This reconstruction algorithm thus
    resembles Reverse Polish Notation, for those familiar with ancient
    calculators that no longer exist. So, nobody.

    Parameters
    ----------
    node : AST
        Attribute name node to be unparsed.
    attr_basenames : Optional[ListStrs], default: None
        Existing caller-defined list to be efficiently cleared, reused, and
        returned by this getter if any *or* :data:`None` otherwise, in which
        case this getter instantiates and returns a new list.

    Returns
    -------
    str
        Fully-qualified name *or* unqualified basename of this name node.
    '''
    assert isinstance(node, AST), f'{repr(node)} not AST.'

    # In theory, this algorithm could also be implemented with an equivalent
    # trivial one-liner resembling:
    #     return ast.unparse(node).split('.')
    #
    # In practice, doing so would:
    # * Be *PROHIBITIVELY* expensive. Recursively unparsing a node into a string
    #   merely to parse that string back into a list of strings constitutes
    #   recursive string-munging -- the ultimate in inefficient one-liners. In
    #   Python, if you want speed, you pay for speed.
    # * Probably fall down in pernicious edge cases in which the returned string
    #   is *NOT* reasonably splittable on all "." delimiters (e.g.,
    #   "obj_name.attr_name['this.is.gonna.fail.hard,yo!']").

    # ....................{ DEFAULTS                       }....................
    # True only if this getter internally instantiates a new list rather than
    # reusing an existing list passed by the caller.
    is_attr_basenames_new = attr_basenames is None

    # If the caller explicitly passed *NO* pre-initialized list, initialize this
    # to the empty list.
    if is_attr_basenames_new:
        attr_basenames = []
    # Else, the caller explicitly passed a pre-initialized list. In this case...
    else:
        assert isinstance(attr_basenames, list), (
            f'{repr(attr_basenames)} not list.')

        # Clear this list.
        attr_basenames.clear()
    # In either case, this local variable is now the empty list.

    # ....................{ NODE ~ expr                    }....................
    # If this is a high-level "Expr" node wrapping one or more lower-level
    # "Attribute" nodes and/or a lower-level "Name" node, unwrap this "Expr" to
    # the root node at the top of this hierarchical nesting of child nodes.
    if isinstance(node, Expr):
        node = node.value
    # Else, this is *NOT* a high-level "Expr" node. In this case, this is
    # assumed to be a lower-level "Attribute" or "Name" node.

    # ....................{ NODE ~ attribute               }....................
    # While the next unqualified basename name comprising this name is still
    # encapsulated by an "Attribute" node...
    #
    # Note that the AST grammar hierarchically nests "Attribute" nodes in the
    # *REVERSE* of the expected nesting. That is, the "attr" instance variable
    # of the *OUTERMOST* "Attribute" node yields the *LAST* "."-delimited
    # substring of the fully-qualified name of this attribute. This
    # reconstruction algorithm thus resembles Reverse Polish Notation, for those
    # familiar with ancient calculators that no longer exist. So, nobody.
    while isinstance(node, Attribute):
        # Append the unqualified basename of this parent submodule of this
        # attribute encapsulated by this "Attribute" child node to this list.
        #
        # Note that, as described above, "Attribute" child nodes are
        # hierarchically nested in the reverse of the expected order. In theory,
        # this basename should be *PREPENDED* rather than *APPENDED* to produce
        # the partially-qualified name of this decorator. In practice, doing so
        # is inefficient. Why? Because:
        # * List appending exhibits average-time O(1) constant-time complexity.
        # * List prepending exhibits average-time O(n) linear-time complexity.
        #
        # This algorithm thus prefers appending, which then necessitates this
        # list be reversed after algorithm termination. It's a small price to
        # pay for a substantial optimization.
        attr_basenames.append(node.attr)

        # Unwrap one hierarchical level of this "Attribute" parent node into its
        # next "Attribute" or "Name" child node.
        node = node.value  # type: ignore[assignment]
    # Else, this name is *NOT* encapsulated by an "Attribute" node.

    # ....................{ NODE ~ name                    }....................
    #FIXME: Also handle "ast.Subscript" nodes produced by statements resembling:
    #    muh_object.muh_var[muh_index]

    # If the trailing unqualified basename of this attribute is encapsulated by
    # a "Name" node, append this trailing unqualified basename to this list.
    if isinstance(node, Name):
        attr_basenames.append(node.id)
    # Else, the trailing unqualified basename of this attribute is *NOT*
    # encapsulated by a "Name" node. In this case...
    #
    # Note that this should *NEVER* happen. All attribute names should be
    # encapsulated by nodes handled above. However, the Python language and
    # hence AST grammar describing that language is constantly evolving. Since
    # this just happened, it is likely that a future iteration of the Python
    # language has now evolved in an unanticipated (yet, ultimately valid) way.
    # To preserve forward compatibility in @beartype with future Python
    # versions, intentionally ignore this unknown AST node type.
    #
    # Sometimes, doing nothing at all is the best thing you can do.
    else:
        # Clear this list. Returning this list in its currently incomplete state
        # would erroneously expose callers to unforeseen issues. Yet again,
        # doing nothing is preferable to doing a bad thing.
        attr_basenames.clear()

    # ....................{ RETURN                         }....................
    # Reverse this list to produce a list in the expected non-reversed order.
    #
    # If the caller explicitly passed *NO* pre-initialized list, reverse this
    # list by efficiently slicing this list in the reverse order into a new
    # list. Note this one-liner has been profiled to be slightly faster than the
    # comparable reversed() builtin. See also:
    #     https://www.geeksforgeeks.org/python/python-reversed-vs-1-which-one-is-faster
    if is_attr_basenames_new:
        attr_basenames = attr_basenames[::-1]
    # Else, the caller explicitly passed a pre-initialized list, implying the
    # caller would prefer to preserve this list rather than instantiating any
    # new list. Reverse this existing list in-place. Note this one-liner has
    # been profiled to be slightly slower than the approach pursued above.
    else:
        attr_basenames.reverse()

    # Return this non-reversed list.
    return attr_basenames
