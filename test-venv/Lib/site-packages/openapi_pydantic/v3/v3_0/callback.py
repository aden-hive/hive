from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    from .path_item import PathItem


Callback = Dict[str, "PathItem"]
"""
A map of possible out-of band callbacks related to the parent operation.
Each value in the map is a [Path Item Object](#pathItemObject)
that describes a set of requests that may be initiated by the API provider and the 
expected responses. The key value used to identify the path item object is an 
expression, evaluated at runtime, that identifies a URL to use for the callback 
operation.
"""

"""Patterned Fields"""

# {expression}: 'PathItem' = ...
"""
A Path Item Object used to define a callback request and expected responses.

A [complete example](../examples/v3.0/callback-example.yaml) is available.
"""
