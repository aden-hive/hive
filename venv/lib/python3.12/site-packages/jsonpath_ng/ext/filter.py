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

import operator
import re

from .. import JSONPath, DatumInContext, Index


OPERATOR_MAP = {
    '!=': operator.ne,
    '==': operator.eq,
    '=': operator.eq,
    '<=': operator.le,
    '<': operator.lt,
    '>=': operator.ge,
    '>': operator.gt,
    '=~': lambda a, b: True if isinstance(a, str) and re.search(b, a) else False,
}


class Filter(JSONPath):
    """The JSONQuery filter"""

    def __init__(self, expressions):
        self.expressions = expressions

    def find(self, datum):
        if not self.expressions:
            return datum

        datum = DatumInContext.wrap(datum)

        if isinstance(datum.value, dict):
            datum.value = list(datum.value.values())

        if not isinstance(datum.value, list):
            return []

        return [DatumInContext(datum.value[i], path=Index(i), context=datum)
                for i in range(0, len(datum.value))
                if (len(self.expressions) ==
                    len(list(filter(lambda x: x.find(datum.value[i]),
                                    self.expressions))))]

    def filter(self, fn, data):
        # NOTE: We reverse the order just to make sure the indexes are preserved upon
        #  removal.
        for datum in reversed(self.find(data)):
            index_obj = datum.path
            if isinstance(data, dict):
                index_obj.index = list(data)[index_obj.index]
            index_obj.filter(fn, data)
        return data

    def update(self, data, val):
        if type(data) is list:
            for index, item in enumerate(data):
                shouldUpdate = len(self.expressions) == len(list(filter(lambda x: x.find(item), self.expressions)))
                if shouldUpdate:
                    if hasattr(val, '__call__'):
                        val.__call__(data[index], data, index)
                    else:
                        data[index] = val
        return data
    
    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.expressions)

    def __str__(self):
        return '[?%s]' % self.expressions

    def __eq__(self, other):
        return (isinstance(other, Filter)
                and self.expressions == other.expressions)


class Expression(JSONPath):
    """The JSONQuery expression"""

    def __init__(self, target, op, value):
        self.target = target
        self.op = op
        self.value = value

    def find(self, datum):
        datum = self.target.find(DatumInContext.wrap(datum))

        if not datum:
            return []
        if self.op is None:
            return datum

        found = []
        for data in datum:
            value = data.value
            if isinstance(self.value, int):
                try:
                    value = int(value)
                except ValueError:
                    continue
            elif isinstance(self.value, bool):
                try:
                    value = bool(value)
                except ValueError:
                    continue

            if OPERATOR_MAP[self.op](value, self.value):
                found.append(data)

        return found

    def __eq__(self, other):
        return (isinstance(other, Expression) and
                self.target == other.target and
                self.op == other.op and
                self.value == other.value)

    def __repr__(self):
        if self.op is None:
            return '%s(%r)' % (self.__class__.__name__, self.target)
        else:
            return '%s(%r %s %r)' % (self.__class__.__name__,
                                     self.target, self.op, self.value)

    def __str__(self):
        if self.op is None:
            return '%s' % self.target
        else:
            return '%s %s %s' % (self.target, self.op, self.value)
