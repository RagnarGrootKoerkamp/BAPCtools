#!/usr/bin/env python3
import threading
import signal
import heapq

import os

import config
import util


class ParallelItem:
    def __init__(self, task, priority, id):
        self.task = task
        self.priority = priority
        self.id = id

    # Note: heapq uses a min heap, so higher priorities are 'smaller'.
    def __lt__(self, other):
        if self.priority != other.priority:
            # python priority queue is a min heap but larger priority
            # items should come first => reverse compare
            return self.priority > other.priority
        else:
            # items with same priority should be handled in FIFO order
            return self.id < other.id


class Parallel:
    # f(task): the function to run on each queue item.
    # num_threads: True: the configured default
    #              None/False/0: disable parallelization
    def __init__(self, f, num_threads=True, pin=False):
        self.f = f
        self.num_threads = config.args.jobs if num_threads is True else num_threads
        self.pin = pin and not util.is_windows() and not util.is_bsd()

        # mutex to lock parallel access
        self.mutex = threading.RLock()
        # condition used to notify worker if the queue has changed
        self.todo = threading.Condition(self.mutex)
        # condition used to notify join that the queue is empty
        self.all_done = threading.Condition(self.mutex)

        # only used in parallel mode
        self.first_error = None
        # min heap
        self.tasks = []
        self.total_tasks = 0
        self.missing = 0

        # also used if num_threads is false
        self.abort = False
        self.finish = False

        if self.num_threads:
            if self.pin:
                # only use available cores and reserve one
                cores = list(os.sched_getaffinity(0))
                if self.num_threads > len(cores) - 1:
                    self.num_threads = len(cores) - 1

                # sort cores by id. If num_threads << len(cores) this ensures that we
                # use different physical cores instead of hyperthreads
                cores.sort()

            self.threads = []
            for i in range(self.num_threads):
                args = [{cores[i]}] if self.pin else []
                t = threading.Thread(target=self._worker, args=args, daemon=True)
                t.start()
                self.threads.append(t)

            signal.signal(signal.SIGINT, self._interrupt_handler)

    def __enter__(self):
        self.mutex.__enter__()

    def __exit__(self, *args):
        self.mutex.__exit__(*args)

    def _worker(self, cores=False):
        if cores is not False:
            os.sched_setaffinity(0, cores)
        while True:
            with self.mutex:
                # if self.abort we need no item in the queue and can stop
                # if self.finish we may need to wake up if all tasks were completed earlier
                # else we need an item to handle
                self.todo.wait_for(lambda: len(self.tasks) > 0 or self.abort or self.finish)

                if self.abort:
                    # we dont handle the queue on abort
                    break
                elif self.finish and len(self.tasks) == 0:
                    # on finish we can only stop after the queue runs empty
                    break
                else:
                    # get item from queue (update self.missing after the task is done)
                    task = heapq.heappop(self.tasks).task

            # call f and catch all exceptions occurring in f
            # store the first exception for later
            try:
                current_error = None
                self.f(task)
            except Exception as e:
                self.stop()
                current_error = e

            with self.mutex:
                if not self.first_error:
                    self.first_error = current_error
                # mark task as completed and notify .join() if queue runs empty
                self.missing -= 1
                if self.missing == 0:
                    self.all_done.notify_all()

    def _interrupt_handler(self, sig, frame):
        util.fatal('Running interrupted')

    # Add one task. Higher priority => done first
    def put(self, task, priority=0):
        if not self.num_threads:
            # no task should be added after .done() was called
            assert not self.finish
            # no task will be handled after self.abort
            if not self.abort:
                if self.pin:
                    cores = list(os.sched_getaffinity(0))
                    os.sched_setaffinity(0, {cores[0]})
                    self.f(task)
                    os.sched_setaffinity(0, cores)
                else:
                    self.f(task)
            return

        with self.mutex:
            # no task should be added after .done() was called
            assert not self.finish
            # no task will be handled after self.abort so skip adding
            if not self.abort:
                # mark task as to be done and notify workers
                self.missing += 1
                self.total_tasks += 1
                heapq.heappush(self.tasks, ParallelItem(task, priority, self.total_tasks))
                self.todo.notify()

    def join(self):
        if not self.num_threads:
            return

        # wait for all current task to be completed
        with self.all_done:
            self.all_done.wait_for(lambda: self.missing == 0)
            if self.first_error:
                raise self.first_error

    # Wait for all tasks to be done and stop all threads
    def done(self):
        self.finish = True

        if not self.num_threads:
            return

        # notify all workes with permission to leave main loop
        with self.todo:
            self.todo.notify_all()

        # wait for all workers to leave main loop
        for t in self.threads:
            t.join()

        # mutex is no longer needed
        # report first error occured during execution
        if self.first_error is not None:
            raise self.first_error

    # Discard all remaining work in the queue and stop all workers.
    # Call done() to join the threads.
    def stop(self):
        self.abort = True

        if not self.num_threads:
            return

        with self.mutex:
            # drop all items in the queue at once
            self.missing -= len(self.tasks)
            self.tasks = []
            # notify all workers to stop waiting for tasks
            self.todo.notify_all()
            # notify .join() if queue runs empty
            if self.missing == 0:
                self.all_done.notify_all()
