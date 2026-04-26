#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **abstract syntax tree (AST) factories** (i.e., low-level callables
creating and returning various types of nodes, typically for inclusion in the
currently visited AST).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from ast import (
    AST,
    Attribute,
    Call,
    Constant,
    Expr,
    FormattedValue,
    ImportFrom,
    Module,
    Name,
    alias,
    expr,
    keyword,
    parse as ast_parse,
)
from beartype.roar import BeartypeClawImportAstException
from beartype.roar._roarexc import _BeartypeUtilAstException
from beartype.typing import (
    List,
    Optional,
)
from beartype._cave._cavemap import NoneTypeOr
from beartype._data.api.standard.dataast import (
    NODE_CONTEXT_LOAD,
    NODE_CONTEXT_STORE,
)
# from beartype._data.typing.datatyping import NodesList
from beartype._data.kind.datakindsequence import LIST_EMPTY
from beartype._util.ast.utilastmunge import copy_node_metadata

# ....................{ FACTORIES                          }....................
#FIXME: Unit test us up, please. When we do, remove the "pragma: no cover" from
#the body of this getter below.
def make_node_from_code_snippet(code_snippet: str) -> AST:
    '''
    Abstract syntax tree (AST) node parsed from the passed (presumably)
    triple-quoted string defining a single child object.

    This function is principally intended to be called from our test suite as a
    convenient means of "parsing" triple-quoted strings into AST nodes.

    Caveats
    -------
    **This function assumes that this string defines only a single child
    object.** If this string defines either no *or* two or more child objects,
    an exception is raised.

    Parameters
    ----------
    code_snippet : str
        Triple-quoted string defining a single child object.

    Returns
    -------
    AST
        AST node encapsulating the object defined by this string.

    Raises
    -------
    _BeartypeUtilAstException
        If this string defines either no *or* two or more child objects.
    '''
    assert isinstance(code_snippet, str), f'{repr(code_snippet)} not string.'

    # "ast.Module" AST tree parsed from this string.
    node_module = ast_parse(code_snippet)

    # If this node is *NOT* actually a module node, raise an exception.
    if not isinstance(node_module, Module):  # pragma: no cover
        raise _BeartypeUtilAstException(
            f'{repr(node_module)} not AST module node.')
    # Else, this node is a module node.

    # List of all direct child nodes of this parent module name.
    nodes_child = node_module.body

    # If this module node contains either no *OR* two or more child nodes, raise
    # an exception.
    if len(nodes_child) != 1:  # pragma: no cover
        raise _BeartypeUtilAstException(
            f'Python code {repr(code_snippet)} defines '
            f'{len(nodes_child)} != 1 child objects.'
        )
    # Else, this module node contains exactly one child node.

    # Return this child node.
    return nodes_child[0]

# ....................{ FACTORIES ~ attribute              }....................
#FIXME: Unit test us up, please.
def make_node_object_attr_load(
    # Mandatory parameters.
    attr_name: str,
    node_sibling: AST,

    # Optional parameters.
    node_obj: Optional[AST] = None,
    obj_name: Optional[str] = None,
) -> Attribute:
    '''
    Create and return a new **object attribute access abstract syntax tree (AST)
    node** (i.e., node encapsulating an access of an object attribute) of the
    passed object with the passed attribute name.

    Note that exactly one of the ``node_obj`` and ``obj_name`` parameters *must*
    be passed. If neither or both of these parameters are passed, an exception
    is raised.

    Parameters
    ----------
    attr_name : str
        Unqualified basename of the attribute of this object to be accessed.
    node_sibling : AST
        Sibling node to copy source code metadata from.
    node_obj : Optional[expr]
        Either:

        * If the caller prefers supplying the name node accessing the parent
          object to load this attribute from, that node.
        * Else, :data:`None`. In this case, the caller *must* pass the
          ``obj_name`` parameter.

        Defaults to :data:`None`.
    obj_name : Optional[str]
        Either:

        * If the caller prefers supplying the unqualified basename of the parent
          object to load this attribute from in the current lexical scope,
          that basename.
        * Else, :data:`None`. In this case, the caller *must* pass the
          ``node_obj`` parameter.

        Defaults to :data:`None`.

    Returns
    -------
    Attribute
        Object attribute node accessing this attribute of this object.

    Raises
    ------
    BeartypeClawImportAstException
        If either:

        * Neither the ``node_obj`` nor ``obj_name`` parameters are passed.
        * Both of the ``node_obj`` and ``obj_name`` parameters are passed.
    '''
    assert isinstance(attr_name, str), f'{repr(attr_name)} not string.'

    # If the caller passed *NO* name node accessing the parent object to load
    # this attribute from...
    if not node_obj:
        # If the caller also passed *NO* unqualified basename of that object,
        # raise an exception.
        if not obj_name:
            raise BeartypeClawImportAstException(
                f'Attribute "{attr_name}" parent object undefined '
                f'(i.e., neither "node_obj" nor "obj_name" parameters passed).'
            )
        # Else, the caller also passed the unqualified basename of that object.

        # Child node accessing that object with this basename.
        node_obj = make_node_name_load(name=obj_name, node_sibling=node_sibling)
    # Else, the caller passed a name node accessing that object.
    #
    # If the caller also passed the unqualified basename of that object, raise
    # an exception.
    elif obj_name:
        raise BeartypeClawImportAstException(
            f'Attribute "{attr_name}" parent object overly defined '
            f'(i.e., both "node_obj" and "obj_name" parameters passed).'
        )
    # Else, the caller passed *NO* unqualified basename of that object.
    #
    # In any case, the "node_obj" variable is now the desired object node.
    assert isinstance(node_obj, expr), (
        f'{repr(node_obj)} not AST expression node.')

    # Object attribute node accessing this attribute of this object.
    node_attribute_load = Attribute(
        value=node_obj, attr=attr_name, ctx=NODE_CONTEXT_LOAD)

    # Copy source code metadata from this sibling node onto this new node.
    copy_node_metadata(node_src=node_sibling, node_trg=node_attribute_load)

    # Return this node.
    return node_attribute_load

# ....................{ FACTORIES ~ attribute : name       }....................
#FIXME: Unit test us up.
def make_node_name_load(name: str, node_sibling: AST) -> Name:
    '''
    Create and return a new **attribute access abstract syntax tree (AST) node**
    (i.e., node encapsulating an access of an attribute) in the current lexical
    scope with the passed name.

    Parameters
    ----------
    name : str
        Fully-qualified name of the attribute to be accessed.
    node_sibling : AST
        Sibling node to copy source code metadata from.

    Returns
    -------
    Name
        Name node accessing this attribute in the current lexical scope.
    '''
    assert isinstance(name, str), f'{repr(name)} not string.'

    # Child node accessing this attribute in the current lexical scope.
    node_name = Name(name, ctx=NODE_CONTEXT_LOAD)

    # Copy source code metadata from this sibling node onto this new node.
    copy_node_metadata(node_src=node_sibling, node_trg=node_name)

    # Return this child node.
    return node_name


#FIXME: Unit test us up.
def make_node_name_store(name: str, node_sibling: AST) -> Name:
    '''
    Create and return a new **attribute assignment abstract syntax tree (AST)
    node** (i.e., node encapsulating an assignment of an attribute) in the
    current lexical scope with the passed name.

    Parameters
    ----------
    name : str
        Fully-qualified name of the attribute to be assigned.
    node_sibling : AST
        Sibling node to copy source code metadata from.

    Returns
    -------
    Name
        Name node assigning this attribute in the current lexical scope.
    '''
    assert isinstance(name, str), f'{repr(name)} not string.'

    # Child node assigning this attribute in the current lexical scope.
    node_name = Name(name, ctx=NODE_CONTEXT_STORE)

    # Copy source code metadata from this sibling node onto this new node.
    copy_node_metadata(node_src=node_sibling, node_trg=node_name)

    # Return this child node.
    return node_name

# ....................{ FACTORIES ~ call                   }....................
#FIXME: Unit test us up, please.
def make_node_call_expr(*args, node_sibling: AST, **kwargs) -> Expr:
    '''
    Create and return a new **callable call expression abstract syntax tree
    (AST) node** (i.e., node encapsulating a Python expression expressing a call
    to an arbitrary function or method) calling the function or method with the
    passed name, positional arguments, and keyword arguments.

    Parameters
    ----------
    node_sibling : AST
        Sibling node to copy source code metadata from.

    All remaining passed positional and keyword parameters are passed to the
    lower-level :func:`.make_node_call` factory function as is.

    Returns
    -------
    Expr
        Expression node calling this callable with these parameters.
    '''

    # Child node calling this callable.
    node_func_call = make_node_call(*args, node_sibling=node_sibling, **kwargs)  # type: ignore[misc]

    # Child node expressing this call as a Python expression.
    node_func = Expr(node_func_call)

    # Copy source code metadata from this sibling node onto this new node.
    copy_node_metadata(node_src=node_sibling, node_trg=node_func)

    # Return this expression node.
    return node_func


#FIXME: Unit test us up, please.
def make_node_call(
    # Mandatory parameters.
    func_name: str,
    node_sibling: AST,

    # Optional parameters.
    nodes_args: List[expr] = LIST_EMPTY,
    nodes_kwargs: List[keyword] = LIST_EMPTY,
) -> Call:
    '''
    Create and return a new **callable call abstract syntax tree (AST) node**
    (i.e., node encapsulating a call to an arbitrary function or method)
    calling the function or method with the passed name, positional arguments,
    and keyword arguments.

    Parameters
    ----------
    func_name : str
        Fully-qualified name of the module to import this attribute from.
    node_sibling : AST
        Sibling node to copy source code metadata from.
    nodes_args : List[expr], optional
        List of zero or more **positional parameter AST expression nodes**
        comprising the tuple of all positional parameters to be passed to this
        call. Defaults to the empty list.
    nodes_kwargs : List[keyword], optional
        List of zero or more **keyword parameter AST nodes** comprising the
        dictionary of all keyword parameters to be passed to this call. Defaults
        to the empty list.

    Returns
    -------
    Call
        Callable call node calling this callable with these parameters.
    '''
    assert isinstance(nodes_args, list), f'{repr(nodes_args)} not list.'
    assert isinstance(nodes_kwargs, list), f'{repr(nodes_kwargs)} not list.'
    assert all(
        isinstance(node_args, expr) for node_args in nodes_args), (
        f'{repr(nodes_args)} not list of AST expression nodes.')
    assert all(
        isinstance(node_kwargs, keyword) for node_kwargs in nodes_kwargs), (
        f'{repr(nodes_kwargs)} not list of AST keyword nodes.')

    # Child node referencing the callable to be called.
    node_func_name = make_node_name_load(
        name=func_name, node_sibling=node_sibling)

    # Child node calling this callable.
    node_func_call = Call(
        func=node_func_name,
        args=nodes_args,
        keywords=nodes_kwargs,
    )

    # Copy source code metadata from this sibling node onto this new node.
    copy_node_metadata(node_src=node_sibling, node_trg=node_func_call)

    # Return this call node.
    return node_func_call

# ....................{ FACTORIES ~ call : arg             }....................
#FIXME: Unit test us up, please.
def make_node_kwarg(
    kwarg_name: str, kwarg_value: expr, node_sibling: AST) -> keyword:
    '''
    Create and return a new **keyword argument abstract syntax tree (AST) node**
    (i.e., node encapsulating a keyword argument of a call to an arbitrary
    function or method) passing the keyword argument with the passed name and
    value to some parent node encapsulating a call to some function or method.

    Parameters
    ----------
    kwarg_name : str
        Name of this keyword argument.
    kwarg_value : expr
        Expression node passing the value of this keyword argument.
    node_sibling : AST
        Sibling node to copy source code metadata from.

    Returns
    -------
    keyword
        Keyword node passing a keyword argument with this name and value.
    '''
    assert isinstance(kwarg_name, str), f'{repr(kwarg_name)} not string.'
    assert isinstance(kwarg_value, expr), (
        f'{repr(kwarg_value)} not AST expression node.')

    # Child node encapsulating this keyword argument.
    node_kwarg = keyword(arg=kwarg_name, value=kwarg_value)

    # Copy source code metadata from this sibling node onto this new node.
    copy_node_metadata(node_src=node_sibling, node_trg=node_kwarg)

    # Return this expression node.
    return node_kwarg

# ....................{ FACTORIES ~ import                 }....................
#FIXME: Unit test us up, please.
def make_node_importfrom(
    # Mandatory parameters.
    module_name: str,
    source_attr_name: str,
    node_sibling: AST,

    # Optional parameters.
    target_attr_name: Optional[str] = None,
) -> ImportFrom:
    '''
    Create and return a new **import-from abstract syntax tree (AST) node**
    (i.e., node encapsulating an import statement of the alias-style format
    ``from {module_name} import {attr_name}``) importing the attribute with the
    passed source name from the module with the passed name into the currently
    visited module as a new attribute with the passed target name.

    Parameters
    ----------
    module_name : str
        Fully-qualified name of the module to import this attribute from.
    source_attr_name : str
        Unqualified basename of the attribute to import from this module.
    target_attr_name : Optional[str]
        Either:

        * If this attribute is to be imported into the currently visited module
          under a different unqualified basename, that basename.
        * If this attribute is to be imported into the currently visited module
          under the same unqualified basename as ``source_attr_name``,
          :data:`None`.

        Defaults to :data:`None`.
    node_sibling : AST
        Sibling node to copy source code metadata from.

    Returns
    -------
    ImportFrom
        Import-from node importing this attribute from this module.
    '''
    assert isinstance(module_name, str), f'{repr(module_name)} not string.'
    assert isinstance(source_attr_name, str), (
        f'{repr(source_attr_name)} not string.')
    assert isinstance(target_attr_name, NoneTypeOr[str]), (
        f'{repr(target_attr_name)} neither string nor "None".')

    # Node encapsulating the name of the attribute to import from this module,
    # defined as either...
    node_importfrom_name = (
        # If this attribute is to be imported into the currently visited module
        # under a different basename, do so;
        alias(name=source_attr_name, asname=target_attr_name)
        if target_attr_name else
        # Else, this attribute is to be imported into the currently visited
        # module under the same basename. In this case, do so.
        alias(name=source_attr_name)
    )

    # Node encapsulating the name of the module to import this attribute from.
    node_importfrom = ImportFrom(
        module=module_name,
        names=[node_importfrom_name],
        # Force an absolute import for safety (i.e., prohibit relative imports).
        level=0,
    )

    # Copy all source code metadata (e.g., line numbers) from this sibling node
    # onto these new nodes.
    copy_node_metadata(
        node_src=node_sibling, node_trg=(node_importfrom, node_importfrom_name))

    # Return this import-from node.
    return node_importfrom

# ....................{ FACTORIES ~ literal : string       }....................
#FIXME: Unit test us up, please.
def make_node_str(text: str, node_sibling: AST) -> Constant:
    '''
    Create and return a new **string literal abstract syntax tree
    (AST) node** (i.e., node encapsulating the passed string).

    Parameters
    ----------
    text : str
        String literal to be encapsulated in a new node.
    node_sibling : AST
        Sibling node to copy source code metadata from.

    Returns
    -------
    Constant
        String literal node encapsulating this string.
    '''
    assert isinstance(text, str), f'{repr(text)} not string.'

    # Child node encapsulating this string.
    node_str = Constant(value=text)

    # Copy source code metadata from this sibling node onto this new node.
    copy_node_metadata(node_src=node_sibling, node_trg=node_str)

    # Return this string literal node.
    return node_str

# ....................{ FACTORIES ~ literal : f-string     }....................
#FIXME: Unit test us up, please.
def make_node_fstr_field(node_expr: expr, node_sibling: AST) -> FormattedValue:
    '''
    Create and return a new **f-string formatting field abstract syntax tree
    (AST) node** (i.e., node embedding the substring created and returned by the
    evaluation of the passed arbitrary expression in some parent node
    encapsulating an f-string embedding this field).

    This factory function creates substrings resembling ``{some_fstr_field}`` in
    larger f-strings resembling ``f'This is {some_fstr_field}, isn't it?'``.

    Caveats
    -------
    This field assumes *no* suffixing ``!``-prefixed conversion (e.g., "!a",
    "!r", "!s"). Thankfully, those conversions are only syntactic sugar for more
    human-readable builtins (e.g., ``repr()``, ``str()``). Ergo, this caveat
    does *not* actually constitute a hard constraint. Just prefer the builtins.

    Parameters
    ----------
    node_expr : expr
        Formatting field to be embedded in some parent f-string node.
    node_sibling : AST
        Sibling node to copy source code metadata from.

    Returns
    -------
    Name
        Name node accessing this attribute in the current lexical scope.
    '''
    assert isinstance(node_expr, expr), (
        f'{repr(node_expr)} not AST expression node.')

    # Child node encapsulating a formatting field "{node_expr.value}" in some
    # parent node encapsulating an f-string embedding this field. For unknown
    # reasons, the standard "ast" module requires that the "conversion"
    # parameter be passed as a non-standard magic integer constant. Whatevahs!
    node_fstr_field = FormattedValue(value=node_expr, conversion=-1)

    # Copy source code metadata from this sibling node onto this new node.
    copy_node_metadata(node_src=node_sibling, node_trg=node_fstr_field)

    # Return this f-string field node.
    return node_fstr_field
