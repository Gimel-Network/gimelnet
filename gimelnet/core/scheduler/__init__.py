from queue import Queue
from typing import Callable
import schedule
from select import select

from rich.console import Console

console = Console()


class Scheduler:

    READ = 0
    WRITE = 1
    DELETE_JOB = 2

    SELECT_TIMEOUT = 1

    def __init__(self):

        # TODO (qnbhd) remove threading.Queue
        #  we need something simpler

        self._jobs = Queue()

        self._readable = dict()

        self._writeable = dict()

        self._exceptors = dict()

        self._finalizer = None

    # noinspection PyMethodMayBeStatic
    def spawn_periodic(self, job, interval):
        schedule.every(interval).seconds.do(job)

    def clear(self):
        self._jobs.queue.clear()
        self._readable.clear()
        self._writeable.clear()

    def _add_readable(self, k, v):
        self._readable[k] = v

    def spawn(self, job):
        self._jobs.put_nowait(job)

    def add_finalizer(self, callback: Callable):
        self._finalizer = callback

    def add_exceptor(self, exception_type, exceptor):
        self._exceptors[exception_type] = exceptor

    def run(self):
        try:
            # event loop
            while any((self._jobs, self._readable, self._writeable)):
                while self._jobs.empty():

                    ready2read, ready2write, _ = select(
                        self._readable, self._writeable, [],
                        Scheduler.SELECT_TIMEOUT)

                    for r in ready2read:
                        task = self._readable.pop(r)
                        self._jobs.put_nowait(task)

                    for w in ready2write:
                        task = self._writeable.pop(w)
                        self._jobs.put_nowait(task)

                    schedule.run_pending()

                # noinspection PyBroadException
                try:
                    task = self._jobs.get_nowait()
                    reason, sock = next(task)

                    if reason == Scheduler.READ:
                        self._readable[sock] = task
                    if reason == Scheduler.WRITE:
                        self._writeable[sock] = task

                except Exception as e:
                    if callback := self._exceptors.get(type(e), lambda *_, **__: None):
                        callback(e)
                    console.print_exception(show_locals=True)
        finally:
            self._finalizer()
