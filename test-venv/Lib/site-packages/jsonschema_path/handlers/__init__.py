from typing import TYPE_CHECKING

from jsonschema_path.handlers.file import FileHandler
from jsonschema_path.handlers.urllib import UrllibHandler

if TYPE_CHECKING:
    from jsonschema_path.handlers.urllib import UrllibHandler as UrlHandler
else:
    try:
        from jsonschema_path.handlers.requests import (
            UrlRequestsHandler as UrlHandler,
        )
    except ImportError:
        from jsonschema_path.handlers.urllib import UrllibHandler as UrlHandler

__all__ = ["FileHandler", "UrlHandler"]

file_handler = FileHandler()
all_urls_handler = UrllibHandler("http", "https", "file")
default_handlers = {
    "<all_urls>": all_urls_handler,
    "http": UrlHandler("http"),
    "https": UrlHandler("https"),
    "file": UrllibHandler("file"),
}
