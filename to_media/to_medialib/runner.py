"""Run jobs inline: skip what exists, write output atomically, report progress."""

import dataclasses
import os
import shutil
import sys
import time

from .media import RecipeError, copy_times


@dataclasses.dataclass
class Policy:
    dry_run: bool = False
    force: bool = False
    replace: bool = False
    verbose: bool = False
    preserve_times: bool = True


def format_duration(seconds):
    hours, rest = divmod(int(round(seconds)), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def progress_text(fraction, elapsed, eta, columns):
    """One status line: a bar, the percentage, elapsed time and the estimate."""
    eta_text = "ETA --:--" if eta is None else f"ETA {format_duration(eta)}"
    tail = f" {fraction * 100:5.1f}%  elapsed {format_duration(elapsed)}  {eta_text}"
    width = max(10, min(30, columns - len(tail) - 8))
    filled = int(round(max(0.0, min(1.0, fraction)) * width))
    return ("    [" + "#" * filled + "-" * (width - filled) + "]" + tail)[:max(20, columns - 1)]


class ProgressLine:
    """A live progress line on a terminal; silent when output is not a terminal."""

    def __init__(self, out, clock=time.monotonic):
        self.out, self.clock = out, clock
        self.enabled = hasattr(out, "isatty") and out.isatty()
        self.start = clock()
        self.last = float("-inf")
        self.shown = False

    def update(self, fraction):
        if not self.enabled:
            return
        now = self.clock()
        if fraction < 1.0 and now - self.last < 0.25:
            return
        self.last = now
        elapsed = now - self.start
        eta = elapsed * (1 - fraction) / fraction if fraction >= 0.02 else None
        columns = shutil.get_terminal_size((80, 20)).columns
        self.out.write("\r" + progress_text(fraction, elapsed, eta, columns) + "\033[K")
        self.out.flush()
        self.shown = True

    def finish(self):
        if self.shown:
            self.out.write("\r\033[K")
            self.out.flush()
            self.shown = False


def partial_path(output):
    folder, name = os.path.split(output)
    stem, ext = os.path.splitext(name)
    return os.path.join(folder, f".{stem}.partial-{os.getpid()}{ext}")


def same_file(a, b):
    return os.path.abspath(a) == os.path.abspath(b)


def display(job):
    names = [os.path.basename(p) for p in job.inputs]
    source = names[0] if len(names) == 1 else f"{len(names)} files"
    return f"{source} -> {os.path.basename(job.output)}"


def run_one(recipe, job, policy, progress=None):
    """Returns (status, detail): done, skipped, failed or planned."""
    if any(same_file(path, job.output) for path in job.inputs):
        return "skipped", "output would overwrite the source"
    if os.path.exists(job.output) and not policy.force:
        return "skipped", "output exists (use --force to overwrite)"
    if policy.dry_run:
        try:
            return "planned", recipe.describe(job)
        except RecipeError as error:
            return "failed", str(error)
    tmp = partial_path(job.output)
    try:
        os.makedirs(os.path.dirname(job.output) or ".", exist_ok=True)
        notes = recipe.run(job, tmp, progress) or []
        if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            raise RecipeError("the converter produced no output")
        os.replace(tmp, job.output)
        if policy.preserve_times:
            copy_times(job.inputs, job.output)
    except (RecipeError, OSError) as error:
        return "failed", str(error)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    if policy.replace:
        for path in job.inputs:
            if not same_file(path, job.output):
                os.unlink(path)
    return "done", "\n".join(f"note: {note}" for note in notes)


def run_jobs(recipe, jobs, policy, out=None):
    out = out or sys.stdout
    counts = {"done": 0, "skipped": 0, "failed": 0, "planned": 0}
    started = time.monotonic()
    for index, job in enumerate(jobs, 1):
        print(f"[{index}/{len(jobs)}] {display(job)}", file=out, flush=True)
        bar = ProgressLine(out)
        status, detail = run_one(recipe, job, policy, bar.update)
        bar.finish()
        counts[status] += 1
        if status in ("planned", "done"):
            if status == "done" and policy.verbose:
                print("    done", file=out)
            for text in detail.splitlines():
                print(f"    {text}", file=out)
        else:
            print(f"    {status}: {detail}" if detail else f"    {status}", file=out, flush=True)
    summary = ", ".join(f"{n} {name}" for name, n in counts.items() if n)
    print(f"{summary or 'nothing to do'} in {format_duration(time.monotonic() - started)}", file=out)
    return counts
