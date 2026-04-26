from json import loads
from urllib.parse import urlsplit
from urllib.request import urlopen

from referencing import Resource
from referencing import Specification
from referencing.typing import URI
from referencing.typing import Retrieve

from jsonschema_path.typing import ResolverHandlers
from jsonschema_path.typing import Schema

USE_REQUESTS = False
try:
    import requests
except ImportError:
    pass
else:
    USE_REQUESTS = True


class SchemaRetriever(Retrieve[Schema]):
    def __init__(
        self, handlers: ResolverHandlers, specification: Specification[Schema]
    ):
        self.handlers = handlers
        self.specification = specification

    def __call__(self, uri: URI) -> Resource[Schema]:
        scheme = urlsplit(uri).scheme
        if scheme in self.handlers:
            handler = self.handlers[scheme]
            contents = handler(uri)
            return self.specification.create_resource(contents)

        else:
            if scheme in ["http", "https"] and USE_REQUESTS:
                # Requests has support for detecting the correct encoding of
                # json over http
                contents = requests.get(uri).json()
                return self.specification.create_resource(contents)

            # Otherwise, pass off to urllib and assume utf-8
            with urlopen(uri) as url:
                contents = loads(url.read().decode("utf-8"))
                return self.specification.create_resource(contents)
