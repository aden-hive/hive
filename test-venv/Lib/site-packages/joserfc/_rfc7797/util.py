from ..registry import Header
from ..errors import MissingCritHeaderError


def is_rfc7797_enabled(header: Header) -> bool:
    if "b64" not in header:
        return False

    if header["b64"] is True:
        return False

    # https://datatracker.ietf.org/doc/html/rfc7797#section-6
    crit = header.get("crit")
    if isinstance(crit, list) and "b64" in crit:
        return True

    raise MissingCritHeaderError("b64")
