#!/usr/bin/env python3
"""Tests for to_media: the pure logic, the runner's safety rules, and real
conversions on generated media (skipped when ffmpeg or ImageMagick are missing).

Run directly (python3 tests/test_to_media.py) or via tests/run_tests.sh.
"""

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOL_DIR)

from to_medialib import cli, recipes, runner, sources  # noqa: E402
from to_medialib.jobs import Job  # noqa: E402
from to_medialib.media import natural_key, run_ffmpeg, safe_filename  # noqa: E402
from to_medialib.recipes import h264  # noqa: E402
from to_medialib.recipes import m4b  # noqa: E402
from to_medialib.recipes.base import Recipe  # noqa: E402
from to_medialib.recipes.image import imagemagick  # noqa: E402

ENTRY = os.path.join(TOOL_DIR, "to_media.py")
HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
HAVE_MAGICK = imagemagick() is not None


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, stdin=subprocess.DEVNULL)


def ffprobe_json(path, *flags):
    done = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", *flags, path],
                          capture_output=True, text=True, check=True)
    return json.loads(done.stdout)


class TempDirTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def read(self, *parts):
        with open(self.path(*parts)) as handle:
            return handle.read()

    def touch(self, *parts, text="x"):
        target = self.path(*parts)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w") as handle:
            handle.write(text)
        return target


class JobAndHelperTests(unittest.TestCase):
    def test_job_survives_json(self):
        job = Job("mp3", ["a.flac"], "a.mp3", {"quality": 2})
        self.assertEqual(Job.from_json(job.to_json()), job)

    def test_natural_order(self):
        self.assertEqual(sorted(["t10", "t2", "t1"], key=natural_key), ["t1", "t2", "t10"])

    def test_safe_filename(self):
        self.assertEqual(safe_filename("A: B/C  d"), "A_ B_C d")

    def test_alias_format(self):
        self.assertEqual(cli.alias_format("to_mp3"), "mp3")
        self.assertEqual(cli.alias_format("to_jpeg"), "jpeg")
        self.assertIsNone(cli.alias_format("to_media"))
        self.assertIsNone(cli.alias_format("to_nonsense"))
        self.assertIsNone(cli.alias_format("mp3"))

    def test_format_duration(self):
        self.assertEqual(runner.format_duration(75), "1:15")
        self.assertEqual(runner.format_duration(3725), "1:02:05")


class SourceCollectionTests(TempDirTestCase):
    def test_folders_are_searched_and_filtered_in_natural_order(self):
        for name in ("b/track 10.flac", "b/track 2.flac", "b/notes.txt", "a.flac"):
            self.touch("music", name)
        found, problems = sources.collect([self.path("music")], {".flac"})
        self.assertEqual([os.path.relpath(s.path, self.path("music")) for s in found],
                         ["a.flac", os.path.join("b", "track 2.flac"), os.path.join("b", "track 10.flac")])
        self.assertEqual(problems, [])
        self.assertTrue(all(s.root == self.path("music") for s in found))

    def test_explicit_files_are_kept_whatever_their_extension(self):
        target = self.touch("odd.xyz")
        found, _ = sources.collect([target], {".flac"})
        self.assertEqual([s.path for s in found], [target])
        self.assertIsNone(found[0].root)

    def test_missing_paths_are_reported(self):
        found, problems = sources.collect([self.path("nope")], {".flac"})
        self.assertEqual(found, [])
        self.assertIn("nope", problems[0])


class PlanningTests(TempDirTestCase):
    def test_output_goes_next_to_the_source_by_default(self):
        src = self.touch("in", "song.flac")
        job = recipes.get("mp3").plan([sources.Source(src)], {}, None)[0]
        self.assertEqual(job.output, self.path("in", "song.mp3"))

    def test_out_dir_keeps_the_folder_layout(self):
        src = self.touch("music", "album", "song.flac")
        found, _ = sources.collect([self.path("music")], {".flac"})
        job = recipes.get("mp3").plan(found, {}, self.path("out"))[0]
        self.assertEqual(job.output, self.path("out", "album", "song.mp3"))
        self.assertEqual(job.inputs, [src])

    def test_image_recipes_skip_their_own_format(self):
        self.assertNotIn(".jpg", recipes.get("jpg").input_exts)
        self.assertNotIn(".jpeg", recipes.get("jpg").input_exts)
        self.assertIn(".heic", recipes.get("jpg").input_exts)
        self.assertIn(".jpg", recipes.get("png").input_exts)

    def test_jpeg_is_an_alias_of_jpg(self):
        self.assertIs(recipes.get("jpeg"), recipes.get("jpg"))

    def test_mp3_options_reach_the_command(self):
        job = Job("mp3", ["a.flac"], "a.mp3", {"audiobook": True})
        command = recipes.get("mp3").command(job, "tmp.mp3")
        self.assertIn("-ac", command)
        self.assertEqual(command[command.index("-q:a") + 1], "8")
        job = Job("mp3", ["a.flac"], "a.mp3", {"bitrate": "192k"})
        command = recipes.get("mp3").command(job, "tmp.mp3")
        self.assertIn("192k", command)
        self.assertNotIn("-q:a", command)


class BookNameTests(unittest.TestCase):
    def test_author_dash_title_with_narrator(self):
        self.assertEqual(m4b.parse_book_name("Jane Doe - Sample Book (Bob Reader)"),
                         ("Sample Book", "Jane Doe", "Bob Reader"))

    def test_hyphenated_words_are_not_split(self):
        self.assertEqual(m4b.parse_book_name("Spider-Man by Stan Lee"), ("Spider-Man", "Stan Lee", None))
        self.assertEqual(m4b.parse_book_name("Spider-Man"), ("Spider-Man", None, None))

    def test_chapter_titles(self):
        self.assertEqual(m4b.chapter_title("01 - Intro.mp3", 1), "Intro")
        self.assertEqual(m4b.chapter_title("003_The Middle.mp3", 3), "The Middle")
        self.assertEqual(m4b.chapter_title("Chapter 4 - End.mp3", 4), "End")
        self.assertEqual(m4b.chapter_title("Part 1 - Start - 12.mp3", 1), "Part 1 - Start")

    def test_book_filename(self):
        self.assertEqual(m4b.book_filename("A: Title", "Some Author"), "Some Author - A_ Title.m4b")
        self.assertEqual(m4b.book_filename(None, None), "Unknown Audiobook.m4b")

    def test_chapter_metadata_escapes_special_characters(self):
        text = m4b.chapters_metadata([("A=B;C", 0, 1.5)])
        self.assertIn("title=A\\=B\\;C", text)
        self.assertIn("END=1500", text)


class FakeTerminal(io.StringIO):
    def isatty(self):
        return True


class ProgressTests(unittest.TestCase):
    def test_progress_text_shows_bar_percent_elapsed_and_eta(self):
        text = runner.progress_text(0.5, 60, 60, 80)
        self.assertIn("50.0%", text)
        self.assertIn("elapsed 1:00", text)
        self.assertIn("ETA 1:00", text)
        self.assertGreater(text.count("#"), 0)

    def test_progress_text_fits_a_narrow_terminal(self):
        self.assertLess(len(runner.progress_text(0.5, 60, 60, 40)), 40)

    def test_unknown_eta_is_shown_as_dashes(self):
        self.assertIn("ETA --:--", runner.progress_text(0.0, 0, None, 80))

    def test_line_updates_in_place_on_a_terminal_and_clears_when_done(self):
        now = [0.0]
        out = FakeTerminal()
        line = runner.ProgressLine(out, clock=lambda: now[0])
        now[0] = 10.0
        line.update(0.25)
        self.assertIn("25.0%", out.getvalue())
        self.assertIn("ETA 0:30", out.getvalue())
        line.finish()
        self.assertTrue(out.getvalue().endswith("\r\033[K"))

    def test_updates_are_rate_limited_but_the_end_is_always_shown(self):
        now = [0.0]
        out = FakeTerminal()
        line = runner.ProgressLine(out, clock=lambda: now[0])
        line.update(0.1)
        now[0] = 0.1
        line.update(0.2)
        self.assertEqual(out.getvalue().count("%"), 1)
        line.update(1.0)
        self.assertIn("100.0%", out.getvalue())

    def test_silent_when_output_is_not_a_terminal(self):
        out = io.StringIO()
        line = runner.ProgressLine(out)
        line.update(0.5)
        line.finish()
        self.assertEqual(out.getvalue(), "")


class H264OptionTests(unittest.TestCase):
    recipe = recipes.get("h264")

    def command(self, **options):
        return self.recipe.command(Job("h264", ["in.mkv"], "out.mp4", options), "tmp.mp4")

    def test_default_is_the_balanced_profile(self):
        command = self.command()
        self.assertEqual(command[command.index("-crf") + 1], "22")
        self.assertEqual(command[command.index("-preset") + 1], "medium")
        self.assertNotIn("-vf", command)

    def test_profile_sets_defaults_and_options_override_them(self):
        command = self.command(profile="fast720", crf=30)
        self.assertEqual(command[command.index("-crf") + 1], "30")
        self.assertEqual(command[command.index("-preset") + 1], "veryfast")
        self.assertIn("min(ih,720)", command[command.index("-vf") + 1])

    def test_chapters_metadata_and_all_audio_are_mapped(self):
        command = self.command()
        self.assertIn("-map_chapters", command)
        self.assertEqual(command[command.index("0:a?") - 1], "-map")

    def test_nvenc_uses_the_gpu_encoder(self):
        command = self.command(encoder="nvenc", crf=25)
        self.assertIn("h264_nvenc", command)
        self.assertEqual(command[command.index("-cq") + 1], "25")
        self.assertNotIn("libx264", command)

    def test_deinterlace_comes_before_scaling(self):
        chain = self.command(deinterlace=True, max_height=480)
        self.assertTrue(chain[chain.index("-vf") + 1].startswith("yadif,scale"))

    def test_mp4_files_found_in_folders_are_not_reencoded_over_themselves(self):
        self.assertNotIn(".mp4", self.recipe.input_exts)
        self.assertIn(".mkv", self.recipe.input_exts)

    def test_settings_merge(self):
        self.assertEqual(h264.settings({"profile": "hq1080", "max_height": 720})["max_height"], 720)
        self.assertEqual(h264.settings({})["audio_bitrate"], "160k")


class FakeRecipe(Recipe):
    """Writes the text 'converted', or fails when told to."""
    name = "fake"
    output_ext = ".out"

    def __init__(self, fail=False, write_nothing=False):
        self.fail, self.write_nothing = fail, write_nothing

    def run(self, job, tmp_output, progress=None):
        if self.fail:
            with open(tmp_output, "w") as handle:
                handle.write("half written")
            raise runner.RecipeError("boom")
        if not self.write_nothing:
            with open(tmp_output, "w") as handle:
                handle.write("converted")

    def describe(self, job):
        return "fake command"


class RunnerTests(TempDirTestCase):
    def job(self, name="a"):
        src = self.touch(f"{name}.src")
        return Job("fake", [src], self.path(f"{name}.out")), src

    def run_one(self, job, recipe=None, **policy):
        return runner.run_one(recipe or FakeRecipe(), job, runner.Policy(**policy))

    def test_converts_and_keeps_the_source(self):
        job, src = self.job()
        self.assertEqual(self.run_one(job)[0], "done")
        self.assertEqual(self.read(job.output), "converted")
        self.assertTrue(os.path.exists(src))
        self.assertEqual([f for f in os.listdir(self.tmp) if "partial" in f], [])

    def test_existing_output_is_skipped_unless_forced(self):
        job, _ = self.job()
        self.touch("a.out", text="old")
        self.assertEqual(self.run_one(job)[0], "skipped")
        self.assertEqual(self.read(job.output), "old")
        self.assertEqual(self.run_one(job, force=True)[0], "done")
        self.assertEqual(self.read(job.output), "converted")

    def test_dry_run_changes_nothing(self):
        job, _ = self.job()
        status, detail = self.run_one(job, dry_run=True)
        self.assertEqual((status, detail), ("planned", "fake command"))
        self.assertFalse(os.path.exists(job.output))

    def test_failure_leaves_no_output_and_no_partial_file(self):
        job, src = self.job()
        status, detail = self.run_one(job, FakeRecipe(fail=True), replace=True)
        self.assertEqual((status, detail), ("failed", "boom"))
        self.assertFalse(os.path.exists(job.output))
        self.assertTrue(os.path.exists(src), "a failed conversion must never delete the source")
        self.assertEqual([f for f in os.listdir(self.tmp) if "partial" in f], [])

    def test_empty_output_counts_as_a_failure(self):
        job, src = self.job()
        status, _ = self.run_one(job, FakeRecipe(write_nothing=True), replace=True)
        self.assertEqual(status, "failed")
        self.assertTrue(os.path.exists(src))

    def test_replace_deletes_the_source_only_after_success(self):
        job, src = self.job()
        self.assertEqual(self.run_one(job, replace=True)[0], "done")
        self.assertFalse(os.path.exists(src))
        self.assertTrue(os.path.exists(job.output))

    def test_output_that_would_overwrite_the_source_is_skipped(self):
        src = self.touch("same.out")
        status, detail = self.run_one(Job("fake", [src], src), force=True, replace=True)
        self.assertEqual(status, "skipped")
        self.assertTrue(os.path.exists(src))

    def test_output_folders_are_created(self):
        src = self.touch("a.src")
        job = Job("fake", [src], self.path("deep", "er", "a.out"))
        self.assertEqual(self.run_one(job)[0], "done")

    def test_run_jobs_summary(self):
        job, _ = self.job()
        out = io.StringIO()
        counts = runner.run_jobs(FakeRecipe(), [job], runner.Policy(), out)
        self.assertEqual(counts["done"], 1)
        self.assertIn("1 done", out.getvalue())


class CliTests(TempDirTestCase):
    def call(self, *argv, prog="to_media"):
        out = io.StringIO()
        saved = sys.stderr
        sys.stderr = err = io.StringIO()
        try:
            code = cli.main(list(argv), prog=prog, out=out)
        finally:
            sys.stderr = saved
        return code, out.getvalue(), err.getvalue()

    def test_formats_lists_every_recipe(self):
        code, out, _ = self.call("formats")
        self.assertEqual(code, 0)
        for name in recipes.names():
            self.assertIn(name, out)

    def test_server_commands_are_reserved_but_not_available(self):
        for command in cli.SERVER_COMMANDS:
            code, _, err = self.call(command)
            self.assertEqual(code, 2)
            self.assertIn("not available yet", err)

    def test_queue_is_refused_clearly(self):
        src = self.touch("a.flac")
        code, _, err = self.call("mp3", "--queue", src)
        self.assertEqual(code, 2)
        self.assertIn("--queue", err)
        self.assertFalse(os.path.exists(self.path("a.mp3")))

    def test_no_matching_files_is_an_error(self):
        os.makedirs(self.path("empty"))
        code, _, err = self.call("mp3", self.path("empty"))
        self.assertEqual(code, 1)
        self.assertIn("no mp3 source files", err)

    def test_missing_path_is_reported(self):
        code, _, err = self.call("mp3", self.path("nope.flac"))
        self.assertEqual(code, 1)
        self.assertIn("not a file or folder", err)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
class AudioConversionTests(TempDirTestCase):
    def run_cli(self, *argv):
        return subprocess.run([sys.executable, ENTRY, *argv], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)

    def test_flac_becomes_mp3_with_tags(self):
        src = self.path("song.flac")
        ffmpeg("-f", "lavfi", "-i", "sine=d=1", "-metadata", "title=Flac Song", "-metadata",
               "artist=Some Band", src)
        done = self.run_cli("mp3", src)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        info = ffprobe_json(self.path("song.mp3"), "-show_format", "-show_streams")
        self.assertEqual(info["streams"][0]["codec_name"], "mp3")
        self.assertEqual(info["format"]["tags"]["title"], "Flac Song")
        self.assertEqual(info["format"]["tags"]["artist"], "Some Band")
        self.assertTrue(os.path.exists(src), "sources are kept by default")

    def test_out_dir_and_replace(self):
        src = self.path("music", "song.wav")
        os.makedirs(os.path.dirname(src))
        ffmpeg("-f", "lavfi", "-i", "sine=d=1", src)
        done = self.run_cli("mp3", "--out", self.path("out"), "--replace", self.path("music"))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(os.path.exists(self.path("out", "song.mp3")))
        self.assertFalse(os.path.exists(src))

    def test_second_run_skips_finished_files(self):
        src = self.path("song.wav")
        ffmpeg("-f", "lavfi", "-i", "sine=d=1", src)
        self.run_cli("mp3", src)
        done = self.run_cli("mp3", src)
        self.assertIn("skipped", done.stdout)
        self.assertIn("1 skipped", done.stdout)

    def test_unreadable_audio_fails_cleanly(self):
        bad = self.touch("broken.flac", text="not audio")
        done = self.run_cli("mp3", bad)
        self.assertEqual(done.returncode, 1)
        self.assertIn("failed", done.stdout)
        self.assertFalse(os.path.exists(self.path("broken.mp3")))
        self.assertEqual([f for f in os.listdir(self.tmp) if "partial" in f], [])

    def test_alias_command_name_selects_the_format(self):
        alias = self.path("to_mp3")
        os.symlink(ENTRY, alias)
        src = self.path("song.wav")
        ffmpeg("-f", "lavfi", "-i", "sine=d=1", src)
        done = subprocess.run([alias, src], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(os.path.exists(self.path("song.mp3")))

    def test_folder_of_files_becomes_one_chaptered_book(self):
        book = self.path("Jane Doe - Sample Book (Bob Reader)")
        os.makedirs(book)
        for number in (10, 2, 1):
            ffmpeg("-f", "lavfi", "-i", f"sine=frequency={300 + number * 20}:d=2", "-c:a", "libmp3lame",
                   os.path.join(book, f"{number} - Part {number}.mp3"))
        done = self.run_cli("m4b", "--out", self.path("books"), book)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        output = self.path("books", "Jane Doe - Sample Book.m4b")
        info = ffprobe_json(output, "-show_format", "-show_chapters")
        self.assertEqual([c["tags"]["title"] for c in info["chapters"]], ["Part 1", "Part 2", "Part 10"])
        tags = info["format"]["tags"]
        self.assertEqual((tags["title"], tags["artist"], tags["composer"], tags["genre"]),
                         ("Sample Book", "Jane Doe", "Bob Reader", "Audiobook"))
        self.assertTrue(os.path.exists(os.path.join(book, "1 - Part 1.mp3")))

    def test_loose_files_are_separate_books_unless_combined(self):
        for name in ("one", "two"):
            ffmpeg("-f", "lavfi", "-i", "sine=d=1", "-c:a", "libmp3lame", self.path(f"{name}.mp3"))
        done = self.run_cli("m4b", "-n", self.path("one.mp3"), self.path("two.mp3"))
        self.assertIn("2 planned", done.stdout)
        done = self.run_cli("m4b", "-n", "--combine", self.path("one.mp3"), self.path("two.mp3"))
        self.assertIn("1 planned", done.stdout)


def nvenc_works():
    try:
        done = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=320x240:d=1",
                               "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


@unittest.skipUnless(HAVE_FFMPEG and h264.has_encoder("libx264"), "ffmpeg with libx264 not installed")
class VideoConversionTests(TempDirTestCase):
    def run_cli(self, *argv):
        return subprocess.run([sys.executable, ENTRY, *argv], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)

    def make_video(self, name, size="640x360", audio_tracks=1, chapters=False):
        target = self.path(name)
        args = ["-f", "lavfi", "-i", f"testsrc=s={size}:r=25:d=2"]
        for track in range(audio_tracks):
            args += ["-f", "lavfi", "-i", f"sine=frequency={400 + track * 100}:d=2"]
        if chapters:
            meta = self.touch("chapters.txt", text=";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1000\n"
                              "title=One\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=1000\nEND=2000\ntitle=Two\n")
            args += ["-i", meta]
        maps = ["-map", "0:v"] + sum((["-map", f"{i + 1}:a"] for i in range(audio_tracks)), [])
        if chapters:
            maps += ["-map_metadata", str(audio_tracks + 1)]
        ffmpeg(*args, *maps, "-c:v", "mpeg4", "-c:a", "mp3", target)
        return target

    def streams(self, path):
        return ffprobe_json(path, "-show_streams", "-show_chapters")

    def test_converts_to_h264_and_aac_and_keeps_the_source(self):
        src = self.make_video("clip.avi")
        done = self.run_cli("h264", src)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        info = self.streams(self.path("clip.mp4"))
        kinds = {s["codec_type"]: s for s in info["streams"]}
        self.assertEqual((kinds["video"]["codec_name"], kinds["video"]["pix_fmt"]), ("h264", "yuv420p"))
        self.assertEqual(kinds["audio"]["codec_name"], "aac")
        self.assertTrue(os.path.exists(src))

    def test_max_height_shrinks_but_never_enlarges(self):
        big = self.make_video("big.avi", size="640x360")
        small = self.make_video("small.avi", size="160x90")
        done = self.run_cli("h264", "--max-height", "180", big, small)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        big_video = [s for s in self.streams(self.path("big.mp4"))["streams"] if s["codec_type"] == "video"][0]
        small_video = [s for s in self.streams(self.path("small.mp4"))["streams"] if s["codec_type"] == "video"][0]
        self.assertEqual((big_video["width"], big_video["height"]), (320, 180))
        self.assertEqual((small_video["width"], small_video["height"]), (160, 90))

    def test_chapters_and_every_audio_track_are_kept(self):
        src = self.make_video("multi.mkv", audio_tracks=2, chapters=True)
        done = self.run_cli("h264", src)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        info = self.streams(self.path("multi.mp4"))
        self.assertEqual([c["tags"]["title"] for c in info["chapters"]], ["One", "Two"])
        self.assertEqual(sum(1 for s in info["streams"] if s["codec_type"] == "audio"), 2)

    def test_mp4_in_a_folder_is_skipped_but_named_explicitly_it_converts_with_out(self):
        self.make_video("a.mkv")
        self.make_video("b.avi")
        shutil.copy(self.path("a.mkv"), self.path("c.mp4"))
        done = self.run_cli("h264", "-n", self.tmp)
        self.assertIn("2 planned", done.stdout)
        done = self.run_cli("h264", "--out", self.path("out"), self.path("c.mp4"))
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertTrue(os.path.exists(self.path("out", "c.mp4")))

    def test_progress_is_reported_while_encoding(self):
        src = self.make_video("clip.avi")
        seen = []
        recipe = recipes.get("h264")
        job = Job("h264", [src], self.path("out.mp4"), {"speed": "ultrafast"})
        recipe.run(job, self.path("out.mp4"), seen.append)
        self.assertTrue(seen)
        self.assertEqual(seen, sorted(seen))
        self.assertEqual(seen[-1], 1.0)

    def test_a_bad_input_fails_without_leaving_output(self):
        bad = self.touch("broken.mkv", text="not video")
        done = self.run_cli("h264", bad)
        self.assertEqual(done.returncode, 1)
        self.assertFalse(os.path.exists(self.path("broken.mp4")))
        self.assertEqual([f for f in os.listdir(self.tmp) if "partial" in f], [])

    @unittest.skipUnless(nvenc_works(), "NVENC not available")
    def test_nvenc_encoder(self):
        src = self.make_video("gpu.avi")
        done = self.run_cli("h264", "--encoder", "nvenc", src)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        video = [s for s in self.streams(self.path("gpu.mp4"))["streams"] if s["codec_type"] == "video"][0]
        self.assertEqual(video["codec_name"], "h264")


@unittest.skipUnless(HAVE_MAGICK, "ImageMagick not installed")
class ImageConversionTests(TempDirTestCase):
    def make_image(self, name, size, color="red"):
        target = self.path(name)
        subprocess.run(imagemagick() + ["-size", size, f"xc:{color}", target], check=True)
        return target

    def convert(self, *argv):
        return subprocess.run([sys.executable, ENTRY, *argv], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)

    def size_of(self, path):
        identify = ["magick", "identify"] if imagemagick() == ["magick"] else ["identify"]
        done = subprocess.run(identify + ["-format", "%wx%h", path], capture_output=True, text=True, check=True)
        return done.stdout

    def test_png_becomes_jpg_and_shrinks_but_never_enlarges(self):
        wide = self.make_image("wide.png", "400x200")
        small = self.make_image("small.bmp", "50x50", "blue")
        done = self.convert("jpg", "--max", "100", wide, small)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.size_of(self.path("wide.jpg")), "100x50")
        self.assertEqual(self.size_of(self.path("small.jpg")), "50x50")

    def test_webp_output(self):
        src = self.make_image("pic.png", "40x40")
        done = self.convert("webp", src)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        with open(self.path("pic.webp"), "rb") as handle:
            header = handle.read(12)
        self.assertEqual((header[:4], header[8:12]), (b"RIFF", b"WEBP"))

    def test_a_folder_skips_files_already_in_the_target_format(self):
        self.make_image("a.png", "10x10")
        self.make_image("b.jpg", "10x10")
        done = self.convert("jpg", "-n", self.tmp)
        self.assertIn("1 planned", done.stdout)


if __name__ == "__main__":
    unittest.main()
