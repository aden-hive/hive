import importlib.metadata


package_metadata = importlib.metadata.metadata("aiofile")

__author__ = package_metadata["Author"]
__version__ = package_metadata["Version"]
author_info = [(package_metadata["Author"], package_metadata["Author-email"])]
package_info = package_metadata["Summary"]
package_license = package_metadata["License"]
project_home = package_metadata["Home-page"]
team_email = package_metadata["Author-email"]
version_info = tuple(map(int, __version__.split(".")))
