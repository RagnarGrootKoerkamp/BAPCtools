#!/usr/bin/env python3
import queue
import threading
import signal

import config
import util


class Parallel:
    # f(task): the function to run on each queue item.
    # num_threads: True: the configured default
    #              None/False/0: disable parallelizatoin
    def __init__(self, f, num_threads=True):
        self.q = queue.Queue()
        self.error = None
        self.f = f
        self.running = True

        self.num_threads = config.args.jobs if num_threads is True else num_threads

        if self.num_threads:
            self.threads = []
            for _ in range(self.num_threads):
                t = threading.Thread(target=self._worker)
                t.start()
                self.threads.append(t)

            signal.signal(signal.SIGINT, self._interrupt_handler)

    # Clear the queue by marking all tasks as done.
    def _clear_queue(self, e=None):
        self.running = False
        if self.error is not None:
            return
        self.error = e
        try:
            while True:
                self.q.get(block=False)
                self.q.task_done()
        except queue.Empty:
            pass
        for _ in range(self.num_threads):
            self.q.put(None)
            self.q.task_done()

    def _worker(self):
        try:
            while self.running:
                task = self.q.get()
                if task is None:
                    break
                self.f(task)
                self.q.task_done()
        except Exception as e:
            self.q.task_done()
            self._clear_queue(e)

    def _interrupt_handler(self, sig, frame):
        self._clear_queue(True)
        util.fatal('Running interrupted')

    # Add one task.
    def put(self, task):
        if not self.running:
            return

        if self.num_threads:
            self.q.put(task)
        else:
            self.f(task)

    # Wait for all tasks to be done
    def join(self):
        if not self.num_threads:
            return

        if self.error is not None:
            raise self.error
        self.q.join()

    # Wait for all tasks to be done and stop all threads
    def done(self):
        if not self.num_threads:
            return

        self.join()
        self.running = False

        for _ in range(self.num_threads):
            self.q.put(None)

        for t in self.threads:
            t.join()

        if self.error is not None:
            raise self.error

    # Discard all remaining work in the queue and stop all threads.
    def stop(self):
        if not self.num_threads:
            return

        self.running = False

        self._clear_queue()
        done()
