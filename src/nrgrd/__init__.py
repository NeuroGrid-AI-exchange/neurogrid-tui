from importlib.metadata import PackageNotFoundError, version

try:
    # Set at build time from the git tag, so there is one source of truth.
    __version__ = version("nrgrd")
except PackageNotFoundError:  # Running from a checkout that was never installed.
    __version__ = "0.0.0"
