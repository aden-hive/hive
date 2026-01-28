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

import re
from .. import DatumInContext, This


SUB = re.compile(r"sub\(/(.*)/,\s+(.*)\)")
# Regex generated using the EZRegex package (ezregex.org)
# EZRegex code: 
# param1 = group(optional(either("'", '"')), name='quote') + group(chunk) + earlier_group('quote')
# param2 = group(either(optional('-') + number, '*'))
# param3 = group(optional('-') + number)
# pattern = 'split' + ow + '(' + ow + param1 + ow + ',' + ow + param2 + ow + ',' + ow + param3 + ow + ')'
SPLIT = re.compile(r"split(?:\s+)?\((?:\s+)?(?P<quote>(?:(?:'|\"))?)(.+)(?P=quote)(?:\s+)?,(?:\s+)?((?:(?:\-)?\d+|\*))(?:\s+)?,(?:\s+)?((?:\-)?\d+)(?:\s+)?\)")
STR = re.compile(r"str\(\)")


class DefintionInvalid(Exception):
    pass


class Sub(This):
    """Regex substituor

    Concrete syntax is '`sub(/regex/, repl)`'
    """

    def __init__(self, method=None):
        m = SUB.match(method)
        if m is None:
            raise DefintionInvalid("%s is not valid" % method)
        self.expr = m.group(1).strip()
        self.repl = m.group(2).strip()
        self.regex = re.compile(self.expr)
        self.method = method

    def find(self, datum):
        datum = DatumInContext.wrap(datum)
        value = self.regex.sub(self.repl, datum.value)
        if value == datum.value:
            return []
        else:
            return [DatumInContext.wrap(value)]

    def __eq__(self, other):
        return (isinstance(other, Sub) and self.method == other.method)

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.method)

    def __str__(self):
        return '`sub(/%s/, %s)`' % (self.expr, self.repl)


class Split(This):
    """String splitter

    Concrete syntax is '`split(chars, segment, max_split)`'
    `chars` can optionally be surrounded by quotes, to specify things like commas or spaces
    `segment` can be `*` to select all
    `max_split` can be negative, to indicate no limit
    """

    def __init__(self, method=None):
        m = SPLIT.match(method)
        if m is None:
            raise DefintionInvalid("%s is not valid" % method)
        self.chars = m.group(2)
        self.segment = m.group(3)
        self.max_split = int(m.group(4))
        self.method = method

    def find(self, datum):
        datum = DatumInContext.wrap(datum)
        try:
            if self.segment == '*':
                value = datum.value.split(self.chars, self.max_split)
            else:
                value = datum.value.split(self.chars, self.max_split)[int(self.segment)]
        except:
            return []
        return [DatumInContext.wrap(value)]

    def __eq__(self, other):
        return (isinstance(other, Split) and self.method == other.method)

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.method)

    def __str__(self):
        return '`%s`' % self.method


class Str(This):
    """String converter

    Concrete syntax is '`str()`'
    """

    def __init__(self, method=None):
        m = STR.match(method)
        if m is None:
            raise DefintionInvalid("%s is not valid" % method)
        self.method = method

    def find(self, datum):
        datum = DatumInContext.wrap(datum)
        value = str(datum.value)
        return [DatumInContext.wrap(value)]

    def __eq__(self, other):
        return (isinstance(other, Str) and self.method == other.method)

    def __repr__(self):
        return '%s(%r)' % (self.__class__.__name__, self.method)

    def __str__(self):
        return '`str()`'
