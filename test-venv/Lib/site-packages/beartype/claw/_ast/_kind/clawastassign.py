#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **assignment statement abstract syntax tree (AST) transformer mixin**
(i.e., low-level superclass instrumenting assignment statements relevant to
runtime type-checking in modules hooked by :mod:`beartype.claw` import hooks).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from ast import (
    AST,
    AnnAssign,
    Assign,
    Attribute,
    Call,
    Name,
    unparse,
)
from beartype._data.claw.dataclawmagic import BEARTYPE_RAISER_FUNC_NAME
from beartype._conf.confcommon import BEARTYPE_CONF_DEFAULT
from beartype._data.typing.datatyping import NodeVisitResult
from beartype._util.ast.utilastmake import (
    make_node_call_expr,
    make_node_kwarg,
    make_node_name_load,
    make_node_object_attr_load,
    make_node_str,
)
from beartype._util.text.utiltextansi import color_attr_name

# ....................{ SUBCLASSES                         }....................
class BeartypeNodeTransformerAssignMixin(object):
    '''
    Beartype :pep:`526`-compliant **abstract syntax tree (AST) node
    transformer** (i.e., visitor pattern recursively transforming *all*
    :pep:`526`-compliant annotated variable assignments in the AST tree passed
    to the :meth:`visit` method of the
    :class:`beartype.claw._ast.clawastmain.BeartypeNodeTransformer` subclass
    also subclassing this mixin).
    '''

    # ..................{ VISITORS ~ pep : 526               }..................
    def visit_Assign(self, node: Assign) -> NodeVisitResult:
        '''
        Track the passed **assignment node** (i.e., node signifying the
        assignment of an attribute) if this node signifies an instantiation of a
        third-party type defining one or more decorator-hostile decorators
        previously imported into a scope of the currently visited module.

        Parameters
        ----------
        node : Assign
            Assignment node to be tracked.

        Returns
        -------
        NodeVisitResult
            This assignment node unmodified.
        '''

        # ..................{ PREAMBLE                       }..................
        # Recursively transform *ALL* child nodes of this parent node.
        self.generic_visit(node)  # type: ignore[attr-defined]

        # ..................{ DECORATOR-HOSTILE              }..................
        # Child node encapsulating the right-hand side (RHS) of this assignment
        # statement, localized purely as a negligible optimization.
        node_source = node.value

        # If this attribute is assigned the result of a call...
        if isinstance(node_source, Call):
            # For each child node encapsulating a left-hand side (LHS) of this
            # assignment statement...
            for node_name_assigned in node.targets:
                # Map the hint annotating the target attribute being assigned to
                # if this call instantiates a third-party type transitively
                # defining decorator-hostile decorators *OR* silently reduce to
                # a noop otherwise (i.e., if this call is *NOT* such an
                # instantiation).
                self.map_node_attr_imported_to_assigned(  # type: ignore[attr-defined]
                    node_name_imported=node_source.func,
                    node_name_assigned=node_name_assigned,
                )
        # Else, this attribute is *NOT* assigned the result of a call.

        # ..................{ RETURN                         }..................
        # Return this node unmodified.
        return node

    # ..................{ VISITORS ~ pep : 526               }..................
    def visit_AnnAssign(self, node: AnnAssign) -> NodeVisitResult:
        '''
        Add a new child node to the passed **annotated assignment node** (i.e.,
        node signifying the assignment of an attribute annotated by a
        :pep:`526`-compliant type hint) inserting a subsequent statement
        following that annotated assignment type-checking that attribute against
        that type hint by passing both to our :func:`beartype.door.is_bearable`
        tester.

        This visitor also additionally track this node if this node signifies an
        instantiation of a third-party type defining one or more
        decorator-hostile decorators previously imported into a scope of the
        currently visited module.

        Design
        ------
        Note that the :class:`.AnnAssign` subclass defines these instance
        variables:

        * ``node.annotation``, a child node describing the PEP-compliant type
          hint annotating this assignment, typically an instance of either:

          * :class:`ast.Name`.
          * :class:`ast.Constant`.

          Note that this node is *not* itself a valid PEP-compliant type hint
          and should *not* be treated as such here or elsewhere.
        * ``node.target``, a child node describing the target attribute assigned
          to by this assignment, guaranteed to be an instance of either:

          * :class:`ast.Name`, in which case this is a **simple assignment**
            (i.e., to a local or global variable). This is the common case in
            which the attribute being assigned to is *NOT* embedded in
            parentheses and thus denotes a simple attribute name rather than a
            full-blown Python expression.
          * :class:`ast.Attribute`, in which case this is an **object
            assignment** (i.e., to an instance or class variable of an object).
          * :class:`ast.Subscript`, in which case this assignment is to the item
            subscripted by an index of a container rather than to that container
            itself.

        * ``node.simple``, an integer :superscript:`sigh` that is either:

          * If ``node.target`` is an :class:`ast.Name` node, 1.
          * Else, 0.

        * ``node.value``, an optional child node defined as either:

          * If this attribute is actually assigned to, a node encapsulating
            the new value assigned to this target attribute.
          * Else, :data:`None`.

        Caveats
        -------
        You may now be thinking to yourself as you wear a bear hat while
        rummaging through this filthy code: "What do you mean, 'if this
        attribute is actually assigned to'? Isn't this attribute necessarily
        assigned to? Isn't that what the 'AnnAssign' subclass means? I mean,
        it's right there in the bloody subclass name: 'AnnAssign', right?
        Clearly, *something* is bloody well being assigned to. Right?"
        Wrong. The name of the :class:`.AnnAssign` subclass was poorly chosen.
        That subclass ambiguously encapsulates both:

        * Annotated variable assignments (e.g., ``muh_attr: int = 42``).
        * Annotated variables *without* assignments (e.g., ``muh_attr: int``).

        Parameters
        ----------
        node : AnnAssign
            Annotated assignment node to be transformed.

        Returns
        -------
        NodeVisitResult
            Either:

            * If this annotated assignment node is *not* **simple** (i.e., the
              attribute being assigned to is embedded in parentheses and thus
              denotes a full-blown Python expression rather than a simple
              attribute name), that same parent node unmodified.
            * If this annotated assignment node is *not* **assigned** (i.e., the
              attribute in question is simply annotated with a type hint rather
              than both annotated with a type hint *and* assigned to), that same
              parent node unmodified.
            * Else, a 2-list comprising both that node and a new adjacent
              :class:`Call` node performing this type-check.

        See Also
        --------
        https://github.com/awf/awfutils
            Third-party Python package whose ``@awfutils.typecheck`` decorator
            implements statement-level :func:`isinstance`-based type-checking in
            a similar manner, strongly inspiring this implementation. Thanks so
            much to Cambridge researcher @awf (Andrew Fitzgibbon) for the
            phenomenal inspiration!
        '''

        # ..................{ PREAMBLE                       }..................
        # Recursively transform *ALL* child nodes of this parent node.
        self.generic_visit(node)  # type: ignore[attr-defined]

        # ..................{ DECORATOR-HOSTILE              }..................
        # Child node encapsulating the hint annotating the target attribute
        # being assigned to, localized purely as a negligible optimization.
        node_hint = node.annotation

        # Child node encapsulating the target attribute being assigned to,
        # localized purely as a negligible optimization.
        node_target = node.target

        # Map the hint annotating the target attribute being assigned to if
        # this hint is the simple name of an isinstanceable third-party type
        # transitively defining decorator-hostile decorators *OR* silently
        # reduce to a noop otherwise (i.e., if this hint is *NOT* such a name).
        self.map_node_attr_imported_to_assigned(  # type: ignore[attr-defined]
            node_name_imported=node_hint,
            node_name_assigned=node_target,
        )

        # ..................{ NOOP                           }..................
        # If either...
        if (
            # It is *NOT* the case that...
            not (
                # This beartype configuration enables type-checking of PEP
                # 526-compliant annotated variable assignments *AND*...
                self._conf.claw_is_pep526 and  # type: ignore[attr-defined]
                # This statement is an assignment (e.g., "muh_var: int = 2")
                # rather than just an unassigned annotation of an attribute
                # (e.g., "muh_var: int").
                node.value
            # Then either this beartype configuration disables type-checking of
            # PEP 526-compliant annotated variable assignments *OR* this
            # statement is just an unassigned annotation of an attribute *OR*...
            ) or
            # This assignment node has one or more parent nodes previously
            # visited by this node transformer *AND* the immediate parent node
            # of this assignment node is a class node, then this assignment node
            # encapsulates a PEP 681-compliant annotated field declaration
            # rather than an PEP 526-compliant annotated variable assignment. In
            # this case, the visit_ClassDef() method defined above has already
            # explicitly decorated the class declaring this annotated field by
            # the @beartype decorator, which then implicitly decorates both this
            # and all other fields of that class by that decorator. For safety
            # and efficiency, avoid needlessly re-decorating this field by the
            # same decorator by simply preserving and returning this node as is.
            #
            # Note, however, that this is *NOT* simply an efficiency concern.
            # This is a significant semantic concern. While a subset of PEP
            # 681-compliant annotated field declarations *ARE* amenable to
            # type-checking by our die_if_unbearable() raiser, still others are
            # absolutely *NOT* amenable to such type-checking. Indeed, in both
            # the average and the worst case, PEP 681-compliant annotated field
            # declarations both supersede and violate PEP 484-compliant typing
            # semantics. Since PEP 681 assumes supremacy over PEP 484 here,
            # @beartype has little to say and much to ignore: e.g.,
            #     from dataclasses import dataclass, field
            #
            #     @dataclass
            #     class MuhDataclass(object):
            #         # This annotated field declaration is safely
            #         # type-checkable by die_if_unbearable(), clearly.
            #         muh_safe_field: int = 0xBABECAFE
            #
            #         # This annotated field declaration is *NOT* safely
            #         # type-checkable by die_if_unbearable(). Clearly, a
            #         # dataclass "field" instance is *NOT* a valid integer and
            #         # thus violates the type hint annotating this field. Since
            #         # PEP 681 standardizes declarations like this as
            #         # semantically valid, @beartype has *NO* alternative but
            #         # to quietly turn a blind eye to what otherwise might be
            #         # considered a type violation.
            #         muh_unsafe_field: int = field(default=0xCAFEBABE)
            self._scopes.is_scope_class  # type: ignore[attr-defined]
        ):
            # Then simply preserve and return this node as is.
            return node
        # Else:
        # * This beartype configuration enables type-checking of PEP
        #   526-compliant annotated variable assignments.
        # * This assignment is simple and assigning to an attribute name.

        # ..................{ LOCALS                         }..................
        # Human-readable label prefixing the exception message raised by our
        # die_if_unbearable() type-checker called below when the value assigned
        # to this variable violates the type hint annotating this variable. For
        # efficiency, we precompute this label at import hook time.
        exception_prefix: str = None  # type: ignore[assignment]

        # Unqualified basename *OR* partially-qualified name of this variable,
        # relative to the current lexical scope.
        var_scoped_name: str = None  # type: ignore[assignment]

        # Child node passing the value newly assigned to this variable by this
        # assignment as the first parameter to die_if_unbearable().
        node_func_arg_pith: AST = None  # type: ignore[assignment]

        # ..................{ PITH                           }..................
        # If this target variable is a simple local or global variable...
        if isinstance(node_target, Name):
            # Unqualified basename of this variable in this lexical scope.
            var_scoped_name = node_target.id

            # Child node accessing this local or global variable.
            #
            # Note that this call effectively shallowly copies this existing
            # "Name" node with context "NODE_CONTEXT_STORE" into a new "Name
            # node with context "NODE_CONTEXT_LOAD". Sadly, the "ast" module
            # provides *NO* means of shallowly copying nodes subject to a
            # trivial modification like this. Ergo, we have *NO* recourse but to
            # do so manually.
            node_func_arg_pith = make_node_name_load(
                name=var_scoped_name, node_sibling=node)
        # Else, this target variable is *NOT* a simple local or global variable.
        #
        # If this target variable is an instance or class variable...
        elif isinstance(node_target, Attribute):
            #FIXME: Insufficient. Attributes can contain arbitrary nested child
            #nodes, including other attributes and/or names. Thankfully, the
            #only reason to even bother attempting to do this is to rigorously
            #sanitize line and column numbers -- which doesn't appear to be
            #particularly necessary or even desirable for dynamically generated
            #code. For now, we simply shallowly reuse the existing "value" node.
            # # Child node referencing the object containing this instance or
            # # class variable (e.g., the "self" in "self.attr: str = 'Attr!'").
            # node_func_arg_pith_obj = Name(
            #     node_target.value.id, ctx=NODE_CONTEXT_LOAD)
            # copy_node_metadata(node_src=node, node_trg=node_func_arg_pith_obj)

            # Child node referencing this instance or class variable.
            #
            # Note that this call effectively shallowly copies this existing
            # "Attribute" node with context "NODE_CONTEXT_STORE" into a new
            # "Attribute" node with context "NODE_CONTEXT_LOAD". Sadly, the
            # "ast" module provides *NO* means of shallowly copying nodes
            # subject to a trivial modification like this. Ergo, we have *NO*
            # recourse but to do so manually.
            node_func_arg_pith = make_node_object_attr_load(
                node_obj=node_target.value,
                attr_name=node_target.attr,
                node_sibling=node,
            )

            # Partially-qualified name of this variable in this lexical scope,
            # defined by "unparsing" this child node. The standard ast.unparse()
            # function "unparses" (i.e., obtains the machine-readable
            # representations of) arbitrary nodes.
            #
            # Note that the parent object of this attribute is described by the
            # external node "node_target.value", encapsulating an arbitrarily
            # complex Python expression. "Unparsing" this expression manually is
            # *ABSOLUTELY* infeasible.
            var_scoped_name = f'{unparse(node_target.value)}.{node_target.attr}'

        #FIXME: Actually, it *WOULD* be useful to type-check "ast.Subscripted"
        #nodes. There's no particular reason *NOT* to, after all. More
        #type-checking can only be a good thing.

        # Else, this target variable is *NOT* an instance or class variable. In
        # this case, this target variable is currently unsupported by this node
        # transformer for automated type-checking. Simply preserve and return
        # this node as is.
        #
        # Examples include:
        # * "ast.Subscripted", in which case this target variable is an item of
        #   a container. It is unclear whether PEP 526 even supports annotated
        #   variable assignments of container items *OR* whether any @beartype
        #   users even annotate variable assignments of container items. Ergo,
        #   this node transformer currently ignores this odd edge case.
        else:
            return node

        # ..................{ CONF                           }..................
        # List of all nodes encapsulating keyword arguments passed to
        # die_if_unbearable(), defaulting to the empty list and thus *NO* such
        # keyword arguments.
        node_func_kwargs = []

        # If the current beartype configuration is *NOT* the default beartype
        # configuration, this configuration is a user-defined beartype
        # configuration which *MUST* be passed as well. In this case...
        if self._conf != BEARTYPE_CONF_DEFAULT:  # type: ignore[attr-defined]
            # Child node encapsulating the passing of this configuration as the
            # "conf" keyword argument to die_if_unbearable().
            node_func_kwarg_conf = self._make_node_keyword_conf(  # type: ignore[attr-defined]
                node_sibling=node)

            # Append this node to the list of all keyword arguments passed to
            # die_if_unbearable().
            node_func_kwargs.append(node_func_kwarg_conf)
        # Else, this configuration is simply the default beartype configuration.
        # In this case, avoid passing that configuration to the beartype
        # decorator for both efficiency and simplicity.

        # ..................{ CONF ~ exception : prefix      }..................
        # If the lexical scope of this parent node is module scope, this node
        # encapsulates a global variable assignment. In this case...
        if self._scopes.is_scope_module:  # type: ignore[attr-defined]
            # Fully-qualified name of this global variable.
            var_name = f'{self._module_name}.{var_scoped_name}'  # type: ignore[attr-defined]

            # Human-readable label prefixing this exception message.
            exception_prefix = f'Global variable "{color_attr_name(var_name)}" '
        # Else, the lexical scope of this parent node is *NOT* module scope.
        # However, by above, this scope is also *NOT* class scope. By
        # elimination, this scope *MUST* thus be a callable scope. In this
        # case...
        else:
            # Fully-qualified name of the callable defining this local variable.
            callable_name = f'{self._scopes[-1].name}()'  # type: ignore[attr-defined]

            # Human-readable label prefixing this exception message.
            exception_prefix = (
                f'Callable {color_attr_name(callable_name)} '
                f'local variable "{color_attr_name(var_scoped_name)}" '
            )
        # print(f'PEP 526 exception_prefix: {exception_prefix}')

        # Child node encapsulating this label as a string literal.
        node_exception_prefix = make_node_str(
            text=exception_prefix, node_sibling=node)

        # Child node encapsulating the passing of this exception prefix as the
        # "exception_prefix" keyword argument to die_if_unbearable().
        node_func_kwarg_exception_prefix = make_node_kwarg(
            kwarg_name='exception_prefix',
            kwarg_value=node_exception_prefix,
            node_sibling=node,
        )

        # Append this node to the list of all keyword arguments passed to
        # die_if_unbearable().
        node_func_kwargs.append(node_func_kwarg_exception_prefix)

        # ..................{ RETURN                         }..................
        # Child node type-checking this newly assigned attribute against the
        # type hint annotating this assignment via our die_if_unbearable()
        # type-checker.
        node_func = make_node_call_expr(
            func_name=BEARTYPE_RAISER_FUNC_NAME,
            nodes_args=[
                # Child node passing the value newly assigned to this
                # attribute by this assignment as the first parameter.
                node_func_arg_pith,
                # Child node passing the type hint annotating this assignment as
                # the second parameter.
                node_hint,
            ],
            nodes_kwargs=node_func_kwargs,
            node_sibling=node,
        )

        # Return a list comprising these two adjacent nodes.
        #
        # Note that order is *EXTREMELY* significant. This order ensures that
        # this attribute is type-checked after being assigned to, as expected.
        return [node, node_func]
