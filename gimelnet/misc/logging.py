import logging as _log
from rich.logging import RichHandler

__all__ = ['getLogger']

_log.basicConfig(
    level="NOTSET", format="%(message)s",
    datefmt="[%X]", handlers=[RichHandler()])

_log.getLogger('schedule').propagate = False
_log.getLogger('process').propagate = False
_log.getLogger('pyngrok.process').propagate = False
_log.getLogger("requests").setLevel(_log.INFO)
_log.getLogger("urllib3").setLevel(_log.INFO)

# noinspection PyPep8Naming
def getLogger(name) -> _log.Logger:
    return _log.getLogger(name)