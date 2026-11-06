"""A small task registry, with the same shape as the Celery app the workers used to run on.

Tasks are registered by name, messages refer to tasks by name, and a worker pulls messages off a
queue and runs whatever the name points at. A task's name is `module.function` unless it is given
one explicitly.
"""

import functools
from collections import deque
from dataclasses import dataclass, field


class UnknownTask(Exception):
    """A message named a task this worker does not have."""


@dataclass
class Message:
    task: str
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)


class Task:
    def __init__(self, app, fn, name):
        functools.update_wrapper(self, fn)
        self.app = app
        self.name = name
        self.run = fn

    def __call__(self, *args, **kwargs):
        return self.run(*args, **kwargs)

    def delay(self, *args, **kwargs):
        return self.app.send_task(self.name, *args, **kwargs)


class TaskApp:
    def __init__(self, main):
        self.main = main
        self.tasks = {}
        self.pending = deque()

    def task(self, fn=None, *, name=None):
        """Register a function as a task: `@app.task`, or `@app.task(name="billing.close")`."""

        def register(function):
            task_name = name or f"{function.__module__}.{function.__name__}"
            if task_name in self.tasks:
                raise ValueError(f"task {task_name} is already registered")
            task = Task(self, function, task_name)
            self.tasks[task_name] = task
            return task

        return register(fn) if fn is not None else register

    def task_names(self):
        return sorted(self.tasks)

    def send_task(self, name, *args, **kwargs):
        """Queue a message for a task, by name."""
        if name not in self.tasks:
            raise UnknownTask(name)
        message = Message(name, args, kwargs)
        self.pending.append(message)
        return message

    def run_task(self, name, *args, **kwargs):
        if name not in self.tasks:
            raise UnknownTask(name)
        return self.tasks[name].run(*args, **kwargs)

    def drain(self):
        """Run everything queued, including anything the queued tasks queue in turn."""
        results = []
        while self.pending:
            message = self.pending.popleft()
            results.append({"task": message.task, "result": self.run_task(message.task, *message.args, **message.kwargs)})
        return results


app = TaskApp("grainbank")
