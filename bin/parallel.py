#!/usr/bin/env python3
import queue
import threading
import signal

import config
import util


class Parallel:
    # f(task): the function to run on each queue item.
    # num_threads: True: the configured default
    #              None/False/0: disable parallelization
    def __init__(self, f, num_threads=True):
        self.q = queue.Queue()
        self.error = None
        self.f = f
        self.stopping = False

        self.num_threads = config.args.jobs if num_threads is True else num_threads

        if self.num_threads:
            self.threads = []
            for _ in range(self.num_threads):
                t = threading.Thread(target=self._worker, daemon=True)
                t.start()
                self.threads.append(t)

            signal.signal(signal.SIGINT, self._interrupt_handler)

    def _worker(self):
        try:
            while not self.stopping:
                task = self.q.get()
                if task is None:
                    break
                self.f(task)
                self.q.task_done()
        except Exception as e:
            self.stop()
            if not self.error:
                self.error = e

    def _interrupt_handler(self, sig, frame):
        util.fatal('Running interrupted')

    # Add one task.
    def put(self, task):
        if self.stopping:
            return

        if self.num_threads:
            self.q.put(task)
        else:
            self.f(task)

    def join(self):
        if self.error:
            raise self.error
        self.q.join()
        if self.error:
            raise self.error

    # Wait for all tasks to be done and stop all threads
    def done(self):
        if not self.num_threads:
            return

        for _ in range(self.num_threads):
            self.q.put(None)

        for t in self.threads:
            t.join()

        if self.error is not None:
            raise self.error

    # Discard all remaining work in the queue and stop all workers.
    # Call done() to join the threads.
    def stop(self):
        if self.stopping:
            return

        self.stopping = True

        if not self.num_threads:
            return

        try:
            while True:
                self.q.get(block=False)
        except queue.Empty:
            pass
        for _ in range(self.num_threads):
            self.q.put(None)
