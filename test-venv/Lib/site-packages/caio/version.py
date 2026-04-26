author_info = (("Dmitry Orlov", "me@mosquito.su"),)

package_info = "Asynchronous file IO for Linux MacOS or Windows."
package_license = "Apache Software License"

team_email = author_info[0][1]

version_info = (0, 9, 25)

__author__ = ", ".join("{} <{}>".format(*info) for info in author_info)
__version__ = ".".join(map(str, version_info))


__all__ = (
    "author_info",
    "package_info",
    "package_license",
    "team_email",
    "version_info",
    "__author__",
    "__version__",
)
