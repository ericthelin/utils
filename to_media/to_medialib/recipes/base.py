"""The interface every output format implements."""

import os
import shlex

from ..jobs import Job
from ..media import missing_programs, run_checked, run_ffmpeg


class Recipe:
    name = ""
    kind = ""
    description = ""
    output_ext = ""
    input_exts = frozenset()
    many_to_one = False
    allow_overwrite_source = False  # true only for a format that may re-encode itself in place

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

    def extension(self, options):
        """The output file extension; some recipes let an option change it."""
        return self.output_ext

    def source_extensions(self, options):
        """Extensions searched for when a folder is given."""
        return self.input_exts

    def plan(self, sources, options, out_dir):
        """One job per source file. Many-to-one recipes override this."""
        extension = self.extension(options)
        return [Job(self.name, [s.path], self.output_path(s, out_dir, extension), dict(options))
                for s in sources]

    def output_path(self, source, out_dir, extension=None):
        extension = extension or self.output_ext
        stem = os.path.splitext(os.path.basename(source.path))[0]
        if not out_dir:
            return os.path.join(os.path.dirname(source.path), stem + extension)
        relative = os.path.relpath(os.path.dirname(source.path), source.root) if source.root else ""
        return os.path.normpath(os.path.join(out_dir, relative, stem + extension))

    def command(self, job, tmp_output):
        """The program and arguments that convert one job (simple recipes)."""
        raise NotImplementedError

    def duration(self, job):
        """Seconds of media in the job, for progress reporting; None if unknown."""
        return None

    def run(self, job, tmp_output, progress=None):
        """Convert the job. May return a list of notes to show the user."""
        command = self.command(job, tmp_output)
        if command[0] == "ffmpeg":
            run_ffmpeg(command, self.duration(job), progress)
        else:
            run_checked(command)

    def describe(self, job):
        return shlex.join(self.command(job, job.output))
