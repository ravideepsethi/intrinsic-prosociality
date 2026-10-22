"""Two live ETAs, based only on newly accounted work in this invocation."""
import contextlib
import datetime as dt
import threading
import time


def duration(seconds):
    minutes = max(0, int(round(seconds / 60)))
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    return (f'{days}d ' if days else '') + f'{hours}h {minutes:02}m'


class Progress:
    def __init__(self, done, targets, prior_rate, logger, interval=30, clock=time.monotonic):
        self.done = int(done)
        self.initial = int(done)
        self.targets = dict(sorted(targets.items()))
        self.total = self.targets[100]
        self.prior_rate = prior_rate
        self.logger = logger
        self.interval = interval
        self.clock = clock
        self.started = clock()
        self.paused_seconds = 0.
        self.paused_at = None
        self.completed_reports = set()
        self.stage = 'checking saved checkpoints'
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.thread = None

    def snapshot(self):
        with self.lock:
            now = self.clock() if self.paused_at is None else self.paused_at
            elapsed = max(0., now - self.started - self.paused_seconds)
            added = self.done - self.initial
            measured = added > 0 and elapsed >= 30
            rate = added / max(elapsed, .001) if measured else self.prior_rate
            next_p = next((p for p in self.targets if p not in self.completed_reports), None)
            next_left = max(0, self.targets[next_p] - self.done) if next_p else 0
            return dict(done=self.done, total=self.total, next_percent=next_p,
                next_seconds=next_left / rate, finish_seconds=max(0, self.total-self.done) / rate,
                rate=rate, rate_basis='this run' if measured else 'prior rate', stage=self.stage)

    def emit(self):
        s = self.snapshot()
        if s['next_percent'] is None:
            self.logger(f"All four checkpoint reports saved; {s['done']:,}/{s['total']:,} API targets accounted.")
            return
        label = (f"next {s['next_percent']}%: saving report" if s['next_seconds'] == 0 else
                 f"ETA next {s['next_percent']}%: {duration(s['next_seconds'])}")
        end = dt.datetime.now().astimezone() + dt.timedelta(seconds=s['finish_seconds'])
        finish = ('download complete; finishing local work' if s['finish_seconds'] == 0 else
                  f"ETA finish 100%: {duration(s['finish_seconds'])} (~{end:%a %d %b %H:%M %Z})")
        self.logger(f"API {s['done']:,}/{s['total']:,}; {s['rate']:.2f} IDs/s ({s['rate_basis']}); "
                    f"{label}; {finish}; {s['stage']}")

    def advance(self, count):
        with self.lock:
            if count < 0 or self.done + count > self.total:
                raise RuntimeError('Progress accounting exceeds the fixed target list')
            self.done += count

    def set_stage(self, label):
        with self.lock:
            self.stage = label

    def report_done(self, percent):
        with self.lock:
            self.completed_reports.add(percent)
        self.emit()

    @contextlib.contextmanager
    def local_work(self, label):
        with self.lock:
            if self.paused_at is not None:
                raise RuntimeError('Nested progress pause')
            self.stage = label
            self.paused_at = self.clock()
        self.emit()
        try:
            yield
        finally:
            with self.lock:
                self.paused_seconds += self.clock() - self.paused_at
                self.paused_at = None

    def __enter__(self):
        def heartbeat():
            while not self.stop.wait(self.interval):
                self.emit()
        self.emit()
        self.thread = threading.Thread(target=heartbeat, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        if self.thread:
            self.thread.join()
