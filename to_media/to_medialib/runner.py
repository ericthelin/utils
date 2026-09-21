"""Run jobs inline: skip what exists, write output atomically, report progress."""

import dataclasses
import os
import sys
import time

from .media import RecipeError


@dataclasses.dataclass
class Policy:
    dry_run: bool = False
    force: bool = False
    replace: bool = False
    verbose: bool = False


def format_duration(seconds):
    hours, rest = divmod(int(round(seconds)), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


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


def run_one(recipe, job, policy):
    """Returns (status, detail): done, skipped, failed or planned."""
    if any(same_file(path, job.output) for path in job.inputs):
        return "skipped", "output would overwrite the source"
    if os.path.exists(job.output) and not policy.force:
        return "skipped", "output exists (use --force to overwrite)"
    if policy.dry_run:
        return "planned", recipe.describe(job)
    tmp = partial_path(job.output)
    try:
        os.makedirs(os.path.dirname(job.output) or ".", exist_ok=True)
        recipe.run(job, tmp)
        if not os.path.exists(tmp) or os.path.getsize(tmp) == 0:
            raise RecipeError("the converter produced no output")
        os.replace(tmp, job.output)
    except (RecipeError, OSError) as error:
        return "failed", str(error)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    if policy.replace:
        for path in job.inputs:
            if not same_file(path, job.output):
                os.unlink(path)
    return "done", ""


def run_jobs(recipe, jobs, policy, out=None):
    out = out or sys.stdout
    counts = {"done": 0, "skipped": 0, "failed": 0, "planned": 0}
    started = time.monotonic()
    for index, job in enumerate(jobs, 1):
        print(f"[{index}/{len(jobs)}] {display(job)}", file=out, flush=True)
        status, detail = run_one(recipe, job, policy)
        counts[status] += 1
        if status == "planned":
            print(f"    {detail}", file=out)
        elif status != "done" or policy.verbose:
            print(f"    {status}: {detail}" if detail else f"    {status}", file=out, flush=True)
    summary = ", ".join(f"{n} {name}" for name, n in counts.items() if n)
    print(f"{summary or 'nothing to do'} in {format_duration(time.monotonic() - started)}", file=out)
    return counts
