"""Instrument implementations — auto-registered on import."""

# Importing each module triggers @instrument() registration.
from . import shell     # noqa: F401
from . import reader    # noqa: F401
from . import writer    # noqa: F401
from . import editor    # noqa: F401
from . import finder    # noqa: F401
from . import delegate  # noqa: F401
from . import skill     # noqa: F401
