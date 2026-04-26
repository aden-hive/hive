"""Pathable types module"""

from typing import Any

from pathable.protocols import Subscriptable

LookupKey = str | int
LookupValue = Any
LookupNode = Subscriptable[LookupKey, LookupValue] | LookupValue
