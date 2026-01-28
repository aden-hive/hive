#!/usr/bin/python
# encoding: utf-8
# Copyright © 2012 Felix Richter <wtfpl@syntax-fehler.de>
# This work is free. You can redistribute it and/or modify it under the
# terms of the Do What The Fuck You Want To Public License, Version 2,
# as published by Sam Hocevar. See the COPYING file for more details.

# Standard Library imports
import json
import sys
import glob
import argparse

# JsonPath-RW imports
from jsonpath_ng import parse

def find_matches_for_file(expr, f):
    return expr.find(json.load(f))

def print_matches(matches):
    print('\n'.join(['{0}'.format(match.value) for match in matches]))


def main(*argv):
    parser = argparse.ArgumentParser(
        description='Search JSON files (or stdin) according to a JSONPath expression.',
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
        Quick JSONPath reference (see more at https://github.com/kennknowles/python-jsonpath-rw)

        atomics:
            $              - root object
            `this`         - current object

        operators:
            path1.path2    - same as xpath /
            path1|path2    - union
            path1..path2   - somewhere in between

        fields:
            fieldname       - field with name
            *               - any field
            [_start_?:_end_?] - array slice
            [*]             - any array index
    """)



    parser.add_argument('expression', help='A JSONPath expression.')
    parser.add_argument('files', metavar='file', nargs='*', help='Files to search (if none, searches stdin)')

    args = parser.parse_args(argv[1:])

    expr = parse(args.expression)
    glob_patterns = args.files

    if len(glob_patterns) == 0:
        # stdin mode
        print_matches(find_matches_for_file(expr, sys.stdin))
    else:
        # file paths mode
        for pattern in glob_patterns:
            for filename in glob.glob(pattern):
                with open(filename) as f:
                    print_matches(find_matches_for_file(expr, f))

def entry_point():
    main(*sys.argv)
