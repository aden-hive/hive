"""
UUID v7 polyfill for Python < 3.14.

On Python 3.14+, we use the stdlib implementation. On older versions,
we use a simplified vendored implementation.

The vendored code can be removed once Python 3.13 support is dropped.
"""

import os
import sys
import time
import uuid
from typing import Callable

__all__ = ("uuid7",)


# Vendored implementation for Python < 3.14
# From Stephen Simmons' implementation (v0.1.0, 2021-12-27)
# Original: https://github.com/stevesimmons/uuid7
# Adapted to match stdlib signature (no parameters)

# Module-level state for sequence counter (maintains monotonicity within same timestamp)
_last = [0, 0, 0, 0]


def _vendored_uuid7() -> uuid.UUID:
    """
    Generate a UUID v7 with embedded timestamp and sequence counter.

    This implementation matches stdlib behavior by using a sequence counter
    to guarantee monotonic ordering when multiple UUIDs are generated within
    the same timestamp tick.

    The 128 bits in the UUID are allocated as follows:
    - 36 bits of whole seconds
    - 24 bits of fractional seconds, giving approx 50ns resolution
    - 14 bits of sequence counter (increments when time unchanged)
    - 48 bits of randomness
    plus, at locations defined by RFC4122, 4 bits for the
    uuid version (0b0111) and 2 bits for the uuid variant (0b10).

             0                   1                   2                   3
             0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    t1      |                 unixts (secs since epoch)                     |
            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    t2/t3   |unixts |  frac secs (12 bits)  |  ver  |  frac secs (12 bits)  |
            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    t4/rand |var|       seq (14 bits)       |          rand (16 bits)       |
            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    rand    |                          rand (32 bits)                       |
            +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    """
    # Get current time in nanoseconds
    ns = time.time_ns()

    # Split into seconds and fractional parts for high-precision timestamp
    # Treat the first 8 bytes of the uuid as a long (t1) and two ints
    # (t2 and t3) holding 36 bits of whole seconds and 24 bits of
    # fractional seconds.
    # This gives a nominal 60ns resolution, comparable to the
    # timestamp precision in Linux (~200ns) and Windows (100ns ticks).
    sixteen_secs = 16_000_000_000
    t1, rest1 = divmod(ns, sixteen_secs)
    t2, rest2 = divmod(rest1 << 16, sixteen_secs)
    t3, _ = divmod(rest2 << 12, sixteen_secs)
    t3 |= 7 << 12  # Put uuid version in top 4 bits, which are 0 in t3

    # The next two bytes are an int (t4) with two bits for
    # the variant 2 and a 14 bit sequence counter which increments
    # if the time is unchanged.
    if t1 == _last[0] and t2 == _last[1] and t3 == _last[2]:
        # Stop the seq counter wrapping past 0x3FFF.
        # This won't happen in practice, but if it does,
        # uuids after the 16383rd with that same timestamp
        # will not longer be correctly ordered but
        # are still unique due to the 6 random bytes.
        if _last[3] < 0x3FFF:
            _last[3] += 1
    else:
        _last[:] = (t1, t2, t3, 0)
    t4 = (2 << 14) | _last[3]  # Put variant 0b10 in top two bits

    # Six random bytes for the lower part of the uuid
    rand = os.urandom(6)

    # Build the UUID from components
    r = int.from_bytes(rand, "big")
    uuid_int = (t1 << 96) + (t2 << 80) + (t3 << 64) + (t4 << 48) + r
    return uuid.UUID(int=uuid_int)


# On Python 3.14+, use stdlib uuid7; otherwise use vendored implementation
if sys.version_info >= (3, 14):
    from uuid import uuid7
else:
    uuid7: Callable[[], uuid.UUID] = _vendored_uuid7
