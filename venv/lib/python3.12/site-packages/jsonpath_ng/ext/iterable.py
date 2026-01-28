#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import functools
from .. import This, DatumInContext, JSONPath


class SortedThis(This):
    """The JSONPath referring to the sorted version of the current object.

    Concrete syntax is '`sorted`' or [\\field,/field].
    """
    def __init__(self, expressions=None):
        self.expressions = expressions

    def _compare(self, left, right):
        left = DatumInContext.wrap(left)
        right = DatumInContext.wrap(right)

        for expr in self.expressions:
            field, reverse = expr
            l_datum = field.find(left)
            r_datum = field.find(right)
            if (not l_datum or not r_datum or
                    len(l_datum) > 1 or len(r_datum) > 1 or
                    l_datum[0].value == r_datum[0].value):
                # NOTE(sileht): should we do something if the expression
                # match multiple fields, for now ignore them
                continue
            elif l_datum[0].value < r_datum[0].value:
                return 1 if reverse else -1
            else:
                return -1 if reverse else 1
        return 0

    def find(self, datum):
        """Return sorted value of This if list or dict."""
        if isinstance(datum.value, dict) and self.expressions:
            return datum

        if isinstance(datum.value, dict) or isinstance(datum.value, list):
            key = (functools.cmp_to_key(self._compare)
                   if self.expressions else None)
            return [DatumInContext.wrap(
                [value for value in sorted(datum.value, key=key)])]
        return datum

    def __eq__(self, other):
        return isinstance(other, Len)

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.expressions)

    def __str__(self):
        return '[?%s]' % self.expressions


class Len(JSONPath):
    """The JSONPath referring to the len of the current object.

    Concrete syntax is '`len`'.
    """

    def find(self, datum):
        datum = DatumInContext.wrap(datum)
        try:
            value = len(datum.value)
        except TypeError:
            return []
        else:
            return [DatumInContext(value,
                                               context=None,
                                               path=Len())]

    def __eq__(self, other):
        return isinstance(other, Len)

    def __str__(self):
        return '`len`'

    def __repr__(self):
        return 'Len()'


class Keys(JSONPath):
    """The JSONPath referring to the keys of the current object.
    Concrete syntax is '`keys`'.
    """

    def find(self, datum):
        datum = DatumInContext.wrap(datum)
        try:
            value = list(datum.value.keys())
        except Exception as e:
            return []
        else:
            return [DatumInContext(value[i],
                                               context=None,
                                               path=Keys()) for i in range (0, len(datum.value))]

    def __eq__(self, other):
        return isinstance(other, Keys)

    def __str__(self):
        return '`keys`'

    def __repr__(self):
        return 'Keys()'

class Path(JSONPath):
    """The JSONPath referring to the path of the current object.
    Concrete syntax is 'path`'.
    """

    def find(self, datum):
        datum = DatumInContext.wrap(datum)
        try:
            value = str(datum.path)
        except Exception as e:
            return []
        else:
            return [DatumInContext(value,
                                   context=datum,
                                   path=Path())]

    def __eq__(self, other):
        return isinstance(other, Path)

    def __str__(self):
        return '`path`'

    def __repr__(self):
        return 'Path()'
