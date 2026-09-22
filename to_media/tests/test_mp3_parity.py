#!/usr/bin/env python3
"""Tests for to_mp3 parity work: re-encoding an existing MP3 in place, and
Audible (.aa/.aax) input with activation keys from a config file."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOL_DIR)

from to_medialib import cli  # noqa: E402
from to_medialib.jobs import Job  # noqa: E402
from to_medialib.media import RecipeError  # noqa: E402
from to_medialib.recipes.mp3 import Mp3, audible_probe, resolve_audible_key  # noqa: E402
from to_medialib.runner import Policy, run_one  # noqa: E402


def has_ffmpeg():
    return shutil.which("ffmpeg") and shutil.which("ffprobe")


class ResolveAudibleKeyTests(unittest.TestCase):
    """These stub out the actual probing, so they need no real Audible file."""

    def test_the_first_working_key_is_used(self):
        calls = []

        def fake_probe(path, key):
            calls.append(key)
            return (1, "mismatch in checksums!") if key == "bad" else (0, "")

        self.assertEqual(resolve_audible_key("book.aax", ["bad", "good", "unused"], fake_probe), "good")
        self.assertEqual(calls, ["bad", "good"])

    def test_no_keys_configured_names_the_config_file(self):
        with self.assertRaises(RecipeError) as ctx:
            resolve_audible_key("book.aax", [], audible_probe)
        self.assertIn("audible_keys", str(ctx.exception))

    def test_every_key_failing_says_so(self):
        def fake_probe(path, key):
            return 1, "mismatch in checksums!"

        with self.assertRaises(RecipeError) as ctx:
            resolve_audible_key("book.aax", ["a", "b"], fake_probe)
        self.assertIn("2 configured", str(ctx.exception))

    def test_a_mismatch_is_recognised_case_insensitively(self):
        def fake_probe(path, key):
            return 1, "Mismatch In Checksums!"

        with self.assertRaises(RecipeError):
            resolve_audible_key("book.aax", ["a"], fake_probe)


@unittest.skipUnless(has_ffmpeg(), "ffmpeg/ffprobe not installed")
class Mp3ParityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.recipe = Mp3()

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def make(self, name, *extra_args):
        target = self.path(name)
        subprocess.run(["ffmpeg", "-y", "-v", "quiet", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                        *extra_args, target], check=True)
        return target

    def test_an_existing_mp3_is_re_encoded_in_place(self):
        src = self.make("song.mp3", "-metadata", "title=Original")
        original_size = os.path.getsize(src)
        job = Job("mp3", [src], src, {"bitrate": "64k"})
        status, _ = run_one(self.recipe, job, Policy())
        self.assertEqual(status, "done")
        self.assertTrue(os.path.exists(src))
        self.assertNotEqual(os.path.getsize(src), original_size)

    def test_re_encoding_in_place_needs_no_force(self):
        src = self.make("song.mp3")
        job = Job("mp3", [src], src, {})
        status, _ = run_one(self.recipe, job, Policy(force=False))
        self.assertEqual(status, "done")

    def test_an_unrelated_existing_output_is_still_skipped(self):
        src = self.make("song.flac")
        dest = self.path("song.mp3")
        with open(dest, "w") as handle:
            handle.write("already here")
        job = Job("mp3", [src], dest, {})
        status, detail = run_one(self.recipe, job, Policy(force=False))
        self.assertEqual(status, "skipped")
        self.assertIn("output exists", detail)

    def test_the_recipe_lists_mp3_as_an_input_extension(self):
        self.assertIn(".mp3", self.recipe.source_extensions({}))
        self.assertIn(".aax", self.recipe.source_extensions({}))

    def test_an_audible_file_is_decoded_with_the_configured_key(self):
        # A real .aax cannot be created here (it needs Audible's DRM), so a
        # plain MP4/AAC file stands in: real .aax is itself an MP4 container,
        # so ffmpeg identifies this one the same way (by content, not
        # extension) and accepts -activation_bytes, which is simply unused
        # since there is no actual encryption here. That still exercises the
        # whole build/run path faithfully.
        src = self.make("book.aax", "-c:a", "aac", "-metadata", "title=A Book", "-metadata", "artist=An Author",
                        "-f", "mp4")
        dest = self.path("book.mp3")
        job = Job("mp3", [src], dest, {"audible": ["deadbeef"]})
        self.assertIn("-activation_bytes deadbeef", self.recipe.describe(job))
        status, _ = run_one(self.recipe, job, Policy())
        self.assertEqual(status, "done")
        self.assertTrue(os.path.exists(dest))

    def test_audible_keys_come_from_the_config_file_by_default(self):
        keys_file = self.path("audible_keys")
        with open(keys_file, "w") as handle:
            handle.write("# a comment\ndeadbeef  cafe0123\n")
        src = self.make("book.aax", "-f", "wav")
        job = Job("mp3", [src], self.path("book.mp3"), {})
        import to_medialib.recipes.mp3 as mp3_module
        original = mp3_module.load_audible_keys
        mp3_module.load_audible_keys = lambda: original(keys_file)
        try:
            self.assertIn("-activation_bytes deadbeef", self.recipe.describe(job))
        finally:
            mp3_module.load_audible_keys = original

    def test_a_missing_key_names_the_config_path(self):
        src = self.make("book.aax", "-f", "wav")
        job = Job("mp3", [src], self.path("book.mp3"), {})
        import to_medialib.recipes.mp3 as mp3_module
        original = mp3_module.load_audible_keys
        mp3_module.load_audible_keys = lambda: []
        try:
            with self.assertRaises(RecipeError) as ctx:
                self.recipe.describe(job)
            self.assertIn("audible_keys", str(ctx.exception))
        finally:
            mp3_module.load_audible_keys = original


@unittest.skipUnless(has_ffmpeg(), "ffmpeg/ffprobe not installed")
class CliAudibleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def call(self, *argv):
        import io
        out, err = io.StringIO(), io.StringIO()
        saved = sys.stderr
        sys.stderr = err
        try:
            code = cli.main(list(argv), prog="to_media", out=out)
        finally:
            sys.stderr = saved
        return code, out.getvalue(), err.getvalue()

    def test_the_audible_flag_overrides_the_config_file(self):
        src = self.path("book.aax")
        subprocess.run(["ffmpeg", "-y", "-v", "quiet", "-f", "lavfi", "-i", "sine=d=1", "-f", "wav", src],
                       check=True)
        code, out, err = self.call("mp3", "--dry-run", "--audible", "11112222", src)
        self.assertEqual(code, 0, err)
        self.assertIn("-activation_bytes 11112222", out)


if __name__ == "__main__":
    unittest.main()
