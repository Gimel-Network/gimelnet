import logging as _log
from rich.logging import RichHandler

__all__ = ['getLogger']

_log.basicConfig(
    level="NOTSET", format="%(message)s",
    datefmt="[%X]", handlers=[RichHandler()])

_log.getLogger('schedule').propagate = False


# noinspection PyPep8Naming
def getLogger(name) -> _log.Logger:
    return _log.getLogger(name)