#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **abstract syntax tree (AST) mungers** (i.e., low-level callables
modifying various properties of various nodes in the currently visited AST).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from ast import (
    AST,
    Call,
    ClassDef,
    Name,
    Subscript,
    expr,
    keyword,
)
from beartype._data.api.standard.dataast import NODE_CONTEXT_LOAD
from beartype._data.claw.dataclawmagic import BEARTYPE_CLAW_STATE_OBJ_NAME
from beartype._util.ast.utilastmake import (
    make_node_kwarg,
    make_node_object_attr_load,
    make_node_str,
)
from beartype._util.ast.utilastmunge import copy_node_metadata

# ....................{ SUBCLASSES                         }....................
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# CAUTION: To improve forward compatibility with the superclass API over which
# we have *NO* control, avoid accidental conflicts by suffixing *ALL* private
# and public attributes of this subclass by "_beartype".
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

class BeartypeNodeTransformerUtilityMixin(object):
    '''
    **Beartype abstract syntax tree (AST) node utility transformer** (i.e.,
    low-level mixin of the high-level
    :class:`beartype.claw._ast.clawastmain.BeartypeNodeTransformer` subclass
    supplementing that subclass with various low-level methods creating,
    modifying, and introspecting common node types and subclass properties).
    '''

    # ....................{ PRIVATE ~ factories            }....................
    #FIXME: Unit test us up, please.
    def _make_node_keyword_conf(self, node_sibling: AST) -> keyword:
        '''
        Create and return a new **beartype configuration keyword argument node**
        (i.e., abstract syntax tree (AST) node passing the beartype
        configuration associated with the currently visited module as a ``conf``
        keyword to a :func:`beartype.beartype` decorator orchestrated by the
        caller).

        Parameters
        ----------
        node_sibling : AST
            Sibling node to copy source code metadata from.

        Returns
        -------
        keyword
            Keyword node passing this configuration to an arbitrary function.
        '''

        # Node encapsulating the fully-qualified name of the current module.
        node_module_name = make_node_str(
            text=self._module_name, node_sibling=node_sibling)  # type: ignore[attr-defined]

        # Node encapsulating a reference to the beartype configuration object
        # cache (i.e., dictionary mapping from fully-qualified module names to
        # the beartype configurations associated with those modules).
        node_module_name_to_conf = make_node_object_attr_load(
            obj_name=BEARTYPE_CLAW_STATE_OBJ_NAME,
            attr_name='module_name_to_beartype_conf',
            node_sibling=node_sibling,
        )

        # Expression node encapsulating the indexation of a dictionary by the
        # fully-qualified name of the current module. For simplicity, simply
        # reuse this node.
        node_module_name_index = node_module_name

        # Node encapsulating a reference to this beartype configuration,
        # indirectly (and efficiently) accessed via a dictionary lookup into
        # this object cache. While cumbersome, this indirection is effectively
        # "glue" integrating this AST node generation algorithm with the
        # corresponding Python code subsequently interpreted by Python at
        # runtime during module importation.
        node_conf = Subscript(
            value=node_module_name_to_conf,
            slice=node_module_name_index,  # type: ignore[arg-type]
            ctx=NODE_CONTEXT_LOAD,
        )

        # Node encapsulating the passing of this beartype configuration as the
        # "conf" keyword argument to an arbitrary function call of some suitable
        # "beartype" function orchestrated by the caller.
        node_keyword_conf = make_node_kwarg(
            kwarg_name='conf', kwarg_value=node_conf, node_sibling=node_sibling)

        # Copy all source code metadata (e.g., line numbers) from this sibling
        # node onto these new nodes.
        copy_node_metadata(node_src=node_sibling, node_trg=node_conf)

        # Return this "conf" keyword node.
        return node_keyword_conf
