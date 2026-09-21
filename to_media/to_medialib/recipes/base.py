"""The interface every output format implements."""

import os
import shlex

from ..jobs import Job
from ..media import missing_programs, run_checked


class Recipe:
    name = ""
    kind = ""
    description = ""
    output_ext = ""
    input_exts = frozenset()
    many_to_one = False

    def requires(self):
        """Programs that must be installed."""
        return []

    def missing(self):
        return missing_programs(self.requires())

    def add_arguments(self, parser):
        """Add this recipe's options to its argument parser."""

    def options_from_args(self, args):
        """Return the job options (plain data) chosen on the command line."""
        return {}

    def plan(self, sources, options, out_dir):
        """One job per source file. Many-to-one recipes override this."""
        return [Job(self.name, [s.path], self.output_path(s, out_dir), dict(options)) for s in sources]

    def output_path(self, source, out_dir):
        stem = os.path.splitext(os.path.basename(source.path))[0]
        if not out_dir:
            return os.path.join(os.path.dirname(source.path), stem + self.output_ext)
        relative = os.path.relpath(os.path.dirname(source.path), source.root) if source.root else ""
        return os.path.normpath(os.path.join(out_dir, relative, stem + self.output_ext))

    def command(self, job, tmp_output):
        """The program and arguments that convert one job (simple recipes)."""
        raise NotImplementedError

    def run(self, job, tmp_output):
        run_checked(self.command(job, tmp_output))

    def describe(self, job):
        return shlex.join(self.command(job, job.output))
