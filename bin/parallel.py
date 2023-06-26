#!/usr/bin/env python3
import threading
import signal

import config
import util


class Parallel:
    # f(task): the function to run on each queue item.
    # num_threads: True: the configured default
    #              None/False/0: disable parallelization
    def __init__(self, f, num_threads=True):
        self.f = f
        self.num_threads = config.args.jobs if num_threads is True else num_threads

        self.mutex = threading.Lock()
        self.todo = threading.Condition(self.mutex)
        self.all_done = threading.Condition(self.mutex)

        self.first_error = None
        self.tasks = []
        self.missing = 0
        self.abort = False
        self.finish = False

        if self.num_threads:
            self.threads = []
            for _ in range(self.num_threads):
                t = threading.Thread(target=self._worker, daemon=True)
                t.start()
                self.threads.append(t)

            signal.signal(signal.SIGINT, self._interrupt_handler)

    def _worker(self):
        while True:
            with self.mutex:
                if len(self.tasks) == 0:
                    self.todo.wait_for(lambda: len(self.tasks) > 0 or self.abort or self.finish)
                
                if self.abort or len(self.tasks) == 0:
                    break
                else:
                    task = self.tasks.pop(0)
            
            try:
                current_error = None
                self.f(task)
            except Exception as e:
                self.stop()
                current_error = e

            with self.mutex:
                if not self.first_error:
                    self.first_error = current_error
                self.missing -= 1
                if self.missing == 0:
                    self.all_done.notify_all()

    def _interrupt_handler(self, sig, frame):
        util.fatal('Running interrupted')

    # Add one task.
    def put(self, task):
        if not self.num_threads:
            self.f(task)
            return

        with self.mutex:
            assert(not self.finish)
            if not self.abort:
                self.missing += 1
                self.tasks.append(task)
                self.todo.notify()

    def join(self):
        if not self.num_threads:
            return

        with self.all_done:
            if self.missing > 0:
                self.all_done.wait_for(lambda: self.missing == 0)
            if self.first_error:
                raise self.first_error

    # Wait for all tasks to be done and stop all threads
    def done(self):
        if not self.num_threads:
            return

        with self.todo:
            self.finish = True
            self.todo.notify_all()

        for t in self.threads:
            t.join()

        # mutex is no longer needed
        if self.first_error is not None:
            raise self.first_error

    # Discard all remaining work in the queue and stop all workers.
    # Call done() to join the threads.
    def stop(self):
        if not self.num_threads:
            return

        with self.mutex:
            self.missing -= len(self.tasks)
            self.tasks = []
            self.abort = True
            self.todo.notify_all()
            if self.missing == 0:
                self.all_done.notify_all()
