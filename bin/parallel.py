#!/usr/bin/env python3
import heapq
import os
import signal
import threading

import config
import util


class QueueItem:
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


class AbstractQueue:
    def __init__(self, f, pin):
        self.f = f
        self.pin = pin
        self.num_threads = 1

        # min heap
        self.tasks: list[QueueItem] = []
        self.total_tasks = 0
        self.missing = 0

        self.aborted = False

        # mutex to lock parallel access
        self.mutex = threading.RLock()

    def __enter__(self):
        self.mutex.__enter__()

    def __exit__(self, *args):
        self.mutex.__exit__(*args)

    # Add one task. Higher priority => done first
    def put(self, task, priority=0):
        raise "Abstract method"

    # By default, do nothing on .join(). This is overridden in ParallelQueue.
    def join(self):
        return

    def done(self):
        raise "Abstract method"

    def abort(self):
        self.aborted = True


class SequentialQueue(AbstractQueue):
    def __init__(self, f, pin):
        super().__init__(f, pin)

    # Add one task. Higher priority => done first
    def put(self, task, priority=0):
        # no task will be handled after self.abort() so skip adding
        if self.aborted:
            return

        self.total_tasks += 1
        heapq.heappush(self.tasks, QueueItem(task, priority, self.total_tasks))

    # Execute all tasks.
    def done(self):
        if self.pin:
            cores = list(os.sched_getaffinity(0))
            os.sched_setaffinity(0, {cores[0]})

        # no task will be handled after self.abort()
        while self.tasks and not self.aborted:
            self.f(heapq.heappop(self.tasks).task)

        if self.pin:
            os.sched_setaffinity(0, cores)


class ParallelQueue(AbstractQueue):
    def __init__(self, f, pin, num_threads):
        super().__init__(f, pin)

        assert num_threads and type(num_threads) is int
        self.num_threads = num_threads

        # condition used to notify worker if the queue has changed
        self.todo = threading.Condition(self.mutex)
        # condition used to notify join that the queue is empty
        self.all_done = threading.Condition(self.mutex)

        self.first_error = None
        self.finish = False

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

    def _worker(self, cores: bool | list[int] = False):
        if cores is not False:
            os.sched_setaffinity(0, cores)
        while True:
            with self.mutex:
                # if self.aborted we need no item in the queue and can stop
                # if self.finish we may need to wake up if all tasks were completed earlier
                # else we need an item to handle
                self.todo.wait_for(lambda: len(self.tasks) > 0 or self.aborted or self.finish)

                if self.aborted:
                    # we don't handle the queue if self.aborted
                    break
                elif self.finish and len(self.tasks) == 0:
                    # if self.finish, we can only stop after the queue runs empty
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
                self.abort()
                current_error = e

            with self.mutex:
                if not self.first_error:
                    self.first_error = current_error
                # mark task as completed and notify .join() if queue runs empty
                self.missing -= 1
                if self.missing == 0:
                    self.all_done.notify_all()

    def _interrupt_handler(self, sig, frame):
        util.fatal('Running interrupted', force=True)

    def _handle_first_error(self):
        if self.first_error is not None:
            first_error = self.first_error
            self.first_error = None
            # we are the main thread now, so we can handle this
            if isinstance(first_error, ChildProcessError):
                self._interrupt_handler(None, None)
            raise first_error

    # Add one task. Higher priority => done first
    def put(self, task, priority=0):
        with self.mutex:
            # no task should be added after .done() was called
            assert not self.finish
            # no task will be handled after self.aborted so skip adding
            if not self.aborted:
                # mark task as to be done and notify workers
                self.missing += 1
                self.total_tasks += 1
                heapq.heappush(self.tasks, QueueItem(task, priority, self.total_tasks))
                self.todo.notify()

    def join(self):
        # wait for all current task to be completed
        with self.all_done:
            self.all_done.wait_for(lambda: self.missing == 0)
            self._handle_first_error()

    # Wait for all tasks to be done and stop all threads
    def done(self):
        self.finish = True

        # notify all workers with permission to leave main loop
        with self.todo:
            self.todo.notify_all()

        # wait for all workers to leave main loop
        for t in self.threads:
            t.join()

        # mutex is no longer needed
        # report first error occurred during execution
        self._handle_first_error()

    # Discard all remaining work in the queue and stop all workers.
    # Call done() to join the threads.
    def abort(self):
        super().abort()

        with self.mutex:
            # drop all items in the queue at once
            self.missing -= len(self.tasks)
            self.tasks = []
            # notify all workers to stop waiting for tasks
            self.todo.notify_all()
            # notify .join() if queue runs empty
            if self.missing == 0:
                self.all_done.notify_all()


def new_queue(f, pin=False):
    """
    f(task): the function to run on each queue item.

    pin: whether to pin the threads to (physical) CPU cores.
    """
    pin = pin and not util.is_windows() and not util.is_bsd()

    num_threads = config.args.jobs
    if num_threads:
        return ParallelQueue(f, pin, num_threads)
    else:
        return SequentialQueue(f, pin)


def run_tasks(f, tasks: list, pin=False):
    queue = new_queue(f, pin)
    for task in tasks:
        queue.put(task)
    queue.done()
