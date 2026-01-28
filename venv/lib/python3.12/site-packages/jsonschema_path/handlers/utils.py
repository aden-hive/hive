import os.path
import urllib.parse
import urllib.request


def uri_to_path(uri: str) -> str:
    parsed = urllib.parse.urlparse(uri)
    host = "{0}{0}{mnt}{0}".format(os.path.sep, mnt=parsed.netloc)
    return os.path.normpath(
        os.path.join(
            host,
            urllib.request.url2pathname(urllib.parse.unquote(parsed.path)),
        )
    )
