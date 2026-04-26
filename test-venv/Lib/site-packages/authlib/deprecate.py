import warnings


class AuthlibDeprecationWarning(DeprecationWarning):
    pass


warnings.simplefilter("always", AuthlibDeprecationWarning)


def deprecate(message, version=None, stacklevel=3):
    if version:
        message += f"\nIt will be compatible before version {version}."

    warnings.warn(AuthlibDeprecationWarning(message), stacklevel=stacklevel)
