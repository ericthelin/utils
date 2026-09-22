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
from to_medialib.media import (attached_pictures, copy_times, format_tags, main_video, natural_key,  # noqa: E402
                               run_ffmpeg, safe_filename)
from to_medialib.recipes import image as image_recipe  # noqa: E402
from to_medialib.recipes import mp3 as mp3_recipe  # noqa: E402
from to_medialib.recipes import h264  # noqa: E402
from to_medialib.recipes import m4b  # noqa: E402
from to_medialib.recipes.base import Recipe  # noqa: E402
from to_medialib.recipes.image import imagemagick  # noqa: E402

ENTRY = os.path.join(TOOL_DIR, "to_media.py")
HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
HAVE_MAGICK = imagemagick() is not None
HAVE_EXIFTOOL = bool(shutil.which("exiftool"))
HAVE_MEDIAINFO = bool(shutil.which("mediainfo"))


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
        info = {"streams": [{"index": 0, "codec_type": "audio"}]}
        job = Job("mp3", ["a.flac"], "a.mp3", {"audiobook": True})
        command = recipes.get("mp3").build(job, "tmp.mp3", info)
        self.assertIn("-ac", command)
        self.assertEqual(command[command.index("-q:a") + 1], "8")
        job = Job("mp3", ["a.flac"], "a.mp3", {"bitrate": "192k"})
        command = recipes.get("mp3").build(job, "tmp.mp3", info)
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


NO_SUBTITLES = {"streams": [{"index": 0, "codec_type": "video", "codec_name": "h264"},
                            {"index": 1, "codec_type": "audio", "codec_name": "aac"}]}


def sub(codec, language=None, **extra):
    stream = {"codec_type": "subtitle", "codec_name": codec}
    if language:
        stream["tags"] = {"language": language}
    return dict(stream, **extra)


def with_subs(*subs, **info):
    streams = [dict(s, index=number) for number, s in enumerate(NO_SUBTITLES["streams"] + list(subs))]
    return dict({"streams": streams}, **info)


class H264OptionTests(unittest.TestCase):
    recipe = recipes.get("h264")

    def command(self, **options):
        return self.recipe.build(Job("h264", ["in.mkv"], "out.mp4", options), "tmp.mp4", NO_SUBTITLES).argv

    def test_default_is_the_balanced_profile(self):
        command = self.command()
        self.assertEqual(command[command.index("-crf:v:0") + 1], "22")
        self.assertEqual(command[command.index("-preset:v:0") + 1], "medium")
        self.assertNotIn("-filter:v:0", command)

    def test_profile_sets_defaults_and_options_override_them(self):
        command = self.command(profile="fast720", crf=30)
        self.assertEqual(command[command.index("-crf:v:0") + 1], "30")
        self.assertEqual(command[command.index("-preset:v:0") + 1], "veryfast")
        self.assertIn("min(ih,720)", command[command.index("-filter:v:0") + 1])

    def test_chapters_metadata_and_all_audio_are_mapped(self):
        command = self.command()
        self.assertIn("-map_chapters", command)
        self.assertEqual(command[command.index("0:a?") - 1], "-map")

    def test_nvenc_uses_the_gpu_encoder(self):
        command = self.command(encoder="nvenc", crf=25)
        self.assertIn("h264_nvenc", command)
        self.assertEqual(command[command.index("-cq:v:0") + 1], "25")
        self.assertNotIn("libx264", command)

    def test_deinterlace_comes_before_scaling(self):
        chain = self.command(deinterlace=True, max_height=480)
        self.assertTrue(chain[chain.index("-filter:v:0") + 1].startswith("yadif,scale"))

    def test_mp4_files_found_in_folders_are_not_reencoded_over_themselves(self):
        self.assertNotIn(".mp4", self.recipe.input_exts)
        self.assertIn(".mkv", self.recipe.input_exts)

    def test_settings_merge(self):
        self.assertEqual(h264.settings({"profile": "hq1080", "max_height": 720})["max_height"], 720)
        self.assertEqual(h264.settings({})["audio_bitrate"], "160k")


class SubtitlePlanTests(unittest.TestCase):
    recipe = recipes.get("h264")

    def plan(self, info, **options):
        return self.recipe.build(Job("h264", ["in.mkv"], "out.mp4", options), "tmp.mp4", info)

    def maps(self, plan):
        return [plan.argv[i + 1] for i, a in enumerate(plan.argv) if a == "-map"]

    def test_text_subtitles_are_kept_as_mov_text_in_mp4(self):
        plan = self.plan(with_subs(sub("subrip", "eng"), sub("ass", "fra")))
        self.assertEqual(self.maps(plan), ["0:0", "0:a?", "0:s:0", "0:s:1"])
        self.assertEqual(plan.argv[plan.argv.index("-c:s") + 1], "mov_text")
        self.assertEqual((plan.soft_subtitles, plan.notes), (2, []))

    def test_no_subtitle_codec_option_when_there_are_no_subtitles(self):
        self.assertNotIn("-c:s", self.plan(NO_SUBTITLES).argv)

    def test_image_subtitles_are_left_out_with_a_note_that_says_what_to_do(self):
        plan = self.plan(with_subs(sub("hdmv_pgs_subtitle", "eng")))
        self.assertEqual(self.maps(plan), ["0:0", "0:a?"])
        self.assertEqual(plan.soft_subtitles, 0)
        self.assertEqual(len(plan.notes), 1)
        for expected in ("image subtitle", "hdmv_pgs_subtitle", "--burn-subtitles", "--container mkv"):
            self.assertIn(expected, plan.notes[0])

    def test_mixed_tracks_keep_the_text_ones_and_report_the_rest(self):
        plan = self.plan(with_subs(sub("subrip", "eng"), sub("dvd_subtitle", "eng"), sub("eia_608")))
        self.assertEqual(self.maps(plan), ["0:0", "0:a?", "0:s:0"])
        self.assertEqual(len(plan.notes), 2)
        self.assertIn("unsupported format", plan.notes[1])

    def test_subtitles_none_drops_them_quietly(self):
        plan = self.plan(with_subs(sub("subrip", "eng"), sub("hdmv_pgs_subtitle")), subtitles="none")
        self.assertEqual(self.maps(plan), ["0:0", "0:a?"])
        self.assertEqual(plan.notes, [])

    def test_mkv_keeps_every_subtitle_track_and_the_fonts(self):
        plan = self.plan(with_subs(sub("subrip", "eng"), sub("hdmv_pgs_subtitle")), container="mkv")
        self.assertEqual(self.maps(plan), ["0:0", "0:a?", "0:s?", "0:t?"])
        self.assertEqual(plan.argv[plan.argv.index("-c:s") + 1], "copy")
        self.assertEqual(plan.argv[plan.argv.index("-f") + 1], "matroska")
        self.assertEqual(plan.notes, [])

    def test_container_changes_the_output_extension_and_the_folder_scan(self):
        self.assertEqual(self.recipe.extension({}), ".mp4")
        self.assertEqual(self.recipe.extension({"container": "mkv"}), ".mkv")
        self.assertIn(".mp4", self.recipe.source_extensions({"container": "mkv"}))
        self.assertNotIn(".mkv", self.recipe.source_extensions({"container": "mkv"}))
        self.assertIn(".mkv", self.recipe.source_extensions({}))

    def test_burning_a_text_track_uses_the_subtitles_filter_and_drops_soft_tracks(self):
        plan = self.plan(with_subs(sub("subrip", "eng"), sub("subrip", "fra")), burn_subtitles="fra")
        chain = plan.argv[plan.argv.index("-filter:v:0") + 1]
        self.assertEqual(chain, "subtitles=source.mkv:si=1")
        self.assertEqual(plan.links, {"source.mkv": os.path.abspath("in.mkv")})
        self.assertEqual(self.maps(plan), ["0:0", "0:a?"])
        self.assertNotIn("mov_text", plan.argv)

    def test_burning_by_number_and_the_default_is_the_first_track(self):
        subs = with_subs(sub("subrip", "eng"), sub("subrip", "fra"))

        def chain(track):
            argv = self.plan(subs, burn_subtitles=track).argv
            return argv[argv.index("-filter:v:0") + 1]

        self.assertIn("si=0", chain("0"))
        self.assertIn("si=1", chain("1"))

    def test_burning_an_image_track_overlays_it_before_scaling(self):
        plan = self.plan(with_subs(sub("hdmv_pgs_subtitle", "eng")), burn_subtitles="eng", max_height=480)
        graph = plan.argv[plan.argv.index("-filter_complex") + 1]
        self.assertTrue(graph.startswith("[0:0][0:s:0]overlay[ov];[ov]"))
        self.assertIn("min(ih,480)", graph)
        self.assertNotIn("-filter:v:0", plan.argv)
        self.assertEqual(self.maps(plan)[0], "[v]")
        self.assertEqual(plan.links, {})

    def test_burning_an_image_track_without_scaling_maps_the_overlay(self):
        plan = self.plan(with_subs(sub("dvd_subtitle", "eng")), burn_subtitles="0")
        self.assertEqual(plan.argv[plan.argv.index("-filter_complex") + 1], "[0:0][0:s:0]overlay[ov]")
        self.assertEqual(self.maps(plan)[0], "[ov]")

    def test_language_matching_accepts_two_and_three_letter_codes(self):
        subs = [sub("subrip", "eng"), sub("subrip", "fra")]
        self.assertEqual(h264.pick_subtitle(subs, "en"), 0)
        self.assertEqual(h264.pick_subtitle(subs, "FRA"), 1)

    def test_burning_errors_are_clear(self):
        from to_medialib.media import RecipeError
        with self.assertRaisesRegex(RecipeError, "no subtitle tracks"):
            self.plan(NO_SUBTITLES, burn_subtitles="0")
        with self.assertRaisesRegex(RecipeError, r"no subtitle track matches 'zzz' \(tracks: eng\)"):
            self.plan(with_subs(sub("subrip", "eng")), burn_subtitles="zzz")
        with self.assertRaisesRegex(RecipeError, "there is no subtitle track 3"):
            self.plan(with_subs(sub("subrip", "eng")), burn_subtitles="3")
        with self.assertRaisesRegex(RecipeError, "cannot be burned"):
            self.plan(with_subs(sub("eia_608")), burn_subtitles="0")

    def test_burning_combines_with_deinterlace_before_scaling(self):
        plan = self.plan(with_subs(sub("subrip", "eng")), burn_subtitles="0", deinterlace=True, max_height=360)
        chain = plan.argv[plan.argv.index("-filter:v:0") + 1]
        self.assertTrue(chain.startswith("yadif,subtitles=source.mkv:si=0,scale="))

    def test_describe_lists_the_command_and_the_notes(self):
        class Fake(recipes.get("h264").__class__):
            def build(self, job, tmp_output, info=None):
                return super().build(job, tmp_output, with_subs(sub("hdmv_pgs_subtitle", "eng")))
        text = Fake().describe(Job("h264", ["in.mkv"], "out.mp4", {}))
        self.assertIn("ffmpeg", text.splitlines()[0])
        self.assertTrue(text.splitlines()[-1].startswith("note: 1 image subtitle track(s)"))


class SubtitleFallbackTests(unittest.TestCase):
    """A subtitle track that will not convert must not cost the whole file."""

    class Flaky(recipes.get("h264").__class__):
        def __init__(self):
            self.attempts = []

        def build(self, job, tmp_output, info=None):
            return super().build(job, tmp_output, with_subs(sub("subrip", "eng")))

        def execute(self, plan, job, progress):
            self.attempts.append(plan)
            if len(self.attempts) == 1:
                raise runner.RecipeError("ffmpeg failed (exit 1): Could not write header (incorrect codec)\nmore")

    def test_retries_without_subtitles_and_says_so(self):
        recipe = self.Flaky()
        notes = recipe.run(Job("h264", ["in.mkv"], "out.mp4", {}), "tmp.mp4")
        self.assertEqual(len(recipe.attempts), 2)
        self.assertEqual(recipe.attempts[0].soft_subtitles, 1)
        self.assertEqual(recipe.attempts[1].soft_subtitles, 0)
        self.assertNotIn("mov_text", recipe.attempts[1].argv)
        self.assertEqual(len(notes), 1)
        self.assertIn("could not be converted and were left out", notes[0])
        self.assertIn("Could not write header", notes[0])

    def test_no_retry_when_there_were_no_subtitles_to_blame(self):
        class Plain(self.Flaky):
            def build(self, job, tmp_output, info=None):
                return recipes.get("h264").__class__.build(self, job, tmp_output, NO_SUBTITLES)
        recipe = Plain()
        with self.assertRaises(runner.RecipeError):
            recipe.run(Job("h264", ["in.mkv"], "out.mp4", {}), "tmp.mp4")
        self.assertEqual(len(recipe.attempts), 1)


class RunnerNotesTests(TempDirTestCase):
    def test_notes_are_shown_even_without_verbose(self):
        class Noting(FakeRecipe):
            def run(self, job, tmp_output, progress=None):
                super().run(job, tmp_output, progress)
                return ["something worth knowing"]
        src = self.touch("a.src")
        out = io.StringIO()
        runner.run_jobs(Noting(), [Job("fake", [src], self.path("a.out"))], runner.Policy(), out)
        self.assertIn("    note: something worth knowing", out.getvalue())

    def test_dry_run_of_an_unreadable_input_reports_a_failure_instead_of_crashing(self):
        class Unreadable(FakeRecipe):
            def describe(self, job):
                raise runner.RecipeError("ffprobe could not read x")
        src = self.touch("a.src")
        status, detail = runner.run_one(Unreadable(), Job("fake", [src], self.path("a.out")),
                                        runner.Policy(dry_run=True))
        self.assertEqual((status, detail), ("failed", "ffprobe could not read x"))


def cover(index=2, codec="mjpeg", **tags):
    return {"index": index, "codec_type": "video", "codec_name": codec, "disposition": {"attached_pic": 1},
            "tags": tags}


class MetadataHelperTests(TempDirTestCase):
    def test_id3_fixes_merge_track_and_disc_totals(self):
        fixes = dict(mp3_recipe.id3_tag_fixes({"track": "3", "tracktotal": "12", "disc": "1", "disctotal": "2"}))
        self.assertEqual(fixes["track"], "3/12")
        self.assertEqual(fixes["disc"], "1/2")
        self.assertEqual((fixes["tracktotal"], fixes["disctotal"]), ("", ""))

    def test_id3_fixes_leave_an_already_merged_number_alone(self):
        self.assertEqual(mp3_recipe.id3_tag_fixes({"track": "3/12", "tracktotal": "12"}), [])
        self.assertEqual(mp3_recipe.id3_tag_fixes({"track": "3"}), [])

    def test_id3_fixes_understand_other_field_names(self):
        fixes = dict(mp3_recipe.id3_tag_fixes({"tracknumber": "3", "totaltracks": "9"}))
        self.assertEqual((fixes["track"], fixes["tracknumber"], fixes["totaltracks"]), ("3/9", "", ""))

    def test_id3_fixes_use_real_frame_names_for_isrc_and_bpm(self):
        fixes = dict(mp3_recipe.id3_tag_fixes({"isrc": "USRC1", "bpm": "128", "title": "x"}))
        self.assertEqual((fixes["TSRC"], fixes["TBPM"], fixes["isrc"], fixes["bpm"]), ("USRC1", "128", "", ""))
        self.assertEqual(mp3_recipe.id3_tag_fixes({"tsrc": "x", "isrc": "y"}), [])

    def test_tags_are_lower_cased_and_missing_ones_tolerated(self):
        self.assertEqual(format_tags({"format": {"tags": {"TITLE": "A", "Artist": "B"}}}), {"title": "A", "artist": "B"})
        self.assertEqual(format_tags({}), {})

    def test_covers_are_told_apart_from_the_real_video(self):
        info = {"streams": [cover(0), {"index": 1, "codec_type": "video"}, {"index": 2, "codec_type": "audio"}]}
        self.assertEqual([p["index"] for p in attached_pictures(info)], [0])
        self.assertEqual(main_video(info)["index"], 1)
        self.assertIsNone(main_video({"streams": [cover(0)]}))

    def test_copy_times_uses_the_newest_source(self):
        old, new, out = self.touch("old"), self.touch("new"), self.touch("out")
        os.utime(old, (1_000_000_000, 1_000_000_000))
        os.utime(new, (1_500_000_000, 1_500_000_000))
        copy_times([old, new], out)
        self.assertEqual(int(os.stat(out).st_mtime), 1_500_000_000)

    def test_copy_times_ignores_a_missing_file(self):
        copy_times([self.path("gone")], self.touch("out"))

    def test_the_runner_keeps_the_source_time_unless_told_not_to(self):
        src = self.touch("a.src")
        os.utime(src, (1_200_000_000, 1_200_000_000))
        job = Job("fake", [src], self.path("a.out"))
        runner.run_one(FakeRecipe(), job, runner.Policy())
        self.assertEqual(int(os.stat(job.output).st_mtime), 1_200_000_000)
        again = Job("fake", [src], self.path("b.out"))
        runner.run_one(FakeRecipe(), again, runner.Policy(preserve_times=False))
        self.assertGreater(int(os.stat(again.output).st_mtime), 1_200_000_000)

    def test_cover_image_files_are_found_by_name(self):
        self.touch("book", "notes.txt")
        self.assertIsNone(m4b.find_cover_image(self.path("book")))
        self.touch("book", "Folder.PNG")
        self.assertEqual(os.path.basename(m4b.find_cover_image(self.path("book"))), "Folder.PNG")
        self.touch("book", "cover.jpg")
        self.assertEqual(os.path.basename(m4b.find_cover_image(self.path("book"))), "cover.jpg")

    def test_webp_says_when_it_cannot_keep_iptc(self):
        recipe = recipes.get("webp")
        original = image_recipe.source_profiles
        try:
            image_recipe.source_profiles = lambda path: {"exif", "iptc"}
            notes = recipe.notes(Job("webp", ["a.jpg"], "a.webp", {}))
            self.assertEqual(len(notes), 1)
            self.assertIn("IPTC", notes[0])
            self.assertIn("use jpg or png", notes[0])
            self.assertEqual(recipe.notes(Job("webp", ["a.jpg"], "a.webp", {"strip": True})), [])
            self.assertEqual(recipes.get("jpg").notes(Job("jpg", ["a.png"], "a.jpg", {})), [])
            image_recipe.source_profiles = lambda path: {"exif"}
            self.assertEqual(recipe.notes(Job("webp", ["a.jpg"], "a.webp", {})), [])
        finally:
            image_recipe.source_profiles = original


class H264MetadataPlanTests(unittest.TestCase):
    recipe = recipes.get("h264")

    def info(self, pictures=(), tags=None, extra_streams=(), video=None):
        streams = [dict({"index": 0, "codec_type": "video", "codec_name": "h264"}, **(video or {})),
                   {"index": 1, "codec_type": "audio", "codec_name": "aac"}]
        streams += list(pictures) + list(extra_streams)
        return {"streams": streams, "format": {"tags": tags or {}}}

    def plan(self, info, **options):
        return self.recipe.build(Job("h264", ["in.mkv"], "out.mp4", options), "tmp.mp4", info)

    def maps(self, plan):
        return [plan.argv[i + 1] for i, a in enumerate(plan.argv) if a == "-map"]

    def test_the_real_video_is_mapped_even_when_a_cover_comes_first(self):
        info = {"streams": [cover(0), {"index": 1, "codec_type": "video", "codec_name": "h264"},
                            {"index": 2, "codec_type": "audio"}], "format": {}}
        plan = self.plan(info)
        self.assertEqual(self.maps(plan)[0], "0:1")
        self.assertIn("0:0", self.maps(plan))

    def test_covers_are_kept_in_an_mp4_as_attached_pictures(self):
        plan = self.plan(self.info(pictures=[cover(2)]))
        self.assertEqual(self.maps(plan), ["0:0", "0:a?", "0:2"])
        self.assertEqual(plan.argv[plan.argv.index("-c:v:1") + 1], "copy")
        self.assertEqual(plan.argv[plan.argv.index("-disposition:v:1") + 1], "attached_pic")

    def test_a_cover_ffmpeg_cannot_copy_into_mp4_becomes_jpeg(self):
        plan = self.plan(self.info(pictures=[cover(2, codec="webp")]))
        self.assertEqual(plan.argv[plan.argv.index("-c:v:1") + 1], "mjpeg")

    def test_standard_tags_need_no_special_handling(self):
        plan = self.plan(self.info(tags={"title": "T", "genre": "G", "creation_time": "x", "encoder": "y"}))
        self.assertNotIn("use_metadata_tags", plan.argv[plan.argv.index("-movflags") + 1])
        self.assertEqual(plan.notes, [])

    def test_extra_tags_without_a_cover_use_quicktime_metadata_and_say_so(self):
        plan = self.plan(self.info(tags={"title": "T", "com.apple.quicktime.location.iso6709": "+1+2/"}))
        self.assertIn("use_metadata_tags", plan.argv[plan.argv.index("-movflags") + 1])
        self.assertEqual(len(plan.notes), 1)
        self.assertIn("com.apple.quicktime.location.iso6709", plan.notes[0])
        self.assertIn("QuickTime metadata", plan.notes[0])

    def test_extra_tags_with_a_cover_keep_the_cover_and_report_the_tags_left_out(self):
        plan = self.plan(self.info(pictures=[cover(2)], tags={"actor": "A", "director": "D"}))
        self.assertNotIn("use_metadata_tags", plan.argv[plan.argv.index("-movflags") + 1])
        self.assertIn("0:2", self.maps(plan))
        self.assertEqual(len(plan.notes), 1)
        for expected in ("actor", "director", "cover picture", "were left out", "--container mkv", "--tags all"):
            self.assertIn(expected, plan.notes[0])

    def test_tags_all_keeps_the_tags_and_says_the_cover_was_dropped(self):
        plan = self.plan(self.info(pictures=[cover(2)], tags={"actor": "A"}), tags="all")
        self.assertIn("use_metadata_tags", plan.argv[plan.argv.index("-movflags") + 1])
        self.assertNotIn("0:2", self.maps(plan))
        self.assertNotIn("-c:v:1", plan.argv)
        self.assertEqual(len(plan.notes), 2)
        self.assertIn("cover picture(s) cannot be stored alongside QuickTime metadata", plan.notes[1])

    def test_tags_standard_keeps_the_cover_and_stays_quiet(self):
        plan = self.plan(self.info(pictures=[cover(2)], tags={"actor": "A"}), tags="standard")
        self.assertIn("0:2", self.maps(plan))
        self.assertNotIn("use_metadata_tags", plan.argv[plan.argv.index("-movflags") + 1])
        self.assertEqual(plan.notes, [])

    def test_mkv_keeps_every_tag_with_no_notes_and_no_quicktime_flag(self):
        plan = self.plan(self.info(tags={"actor": "A"}), container="mkv")
        self.assertEqual(plan.notes, [])
        self.assertNotIn("use_metadata_tags", " ".join(plan.argv))

    def test_mkv_covers_are_extracted_and_attached_not_mapped_as_video(self):
        plan = self.plan(self.info(pictures=[cover(2, filename="poster.jpg", mimetype="image/jpeg")]),
                         container="mkv")
        self.assertNotIn("0:2", self.maps(plan))
        self.assertEqual(plan.covers[0]["index"], 2)
        self.assertEqual(plan.argv[plan.argv.index("-attach") + 1], "<cover:0>")
        self.assertIn("filename=poster.jpg", plan.argv)
        self.assertIn("mimetype=image/jpeg", plan.argv)
        self.assertIn("-metadata:s:t:0", plan.argv)

    def test_mkv_cover_slots_come_after_the_fonts_that_are_copied(self):
        fonts = [{"index": 3, "codec_type": "attachment"}, {"index": 4, "codec_type": "attachment"}]
        plan = self.plan(self.info(pictures=[cover(2)], extra_streams=fonts), container="mkv")
        self.assertIn("-metadata:s:t:2", plan.argv)

    def test_mkv_attachments_are_kept_even_when_there_are_no_subtitles(self):
        self.assertIn("0:t?", self.maps(self.plan(self.info(), container="mkv")))
        self.assertNotIn("0:t?", self.maps(self.plan(self.info(), container="mkv", subtitles="none")))

    def test_hdr_sources_get_a_note(self):
        plan = self.plan(self.info(video={"color_transfer": "smpte2084"}))
        self.assertEqual(len(plan.notes), 1)
        self.assertIn("HDR", plan.notes[0])
        self.assertEqual(self.plan(self.info(video={"color_transfer": "bt709"})).notes, [])

    def test_camera_data_tracks_are_reported(self):
        data = [{"index": 3, "codec_type": "data", "codec_tag_string": "gpmd"},
                {"index": 4, "codec_type": "data", "codec_tag_string": "text"}]
        plan = self.plan(self.info(extra_streams=data))
        self.assertEqual(len(plan.notes), 1)
        self.assertIn("gpmd", plan.notes[0])
        self.assertNotIn("text", plan.notes[0])


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

    def test_follow_without_queue_is_refused(self):
        src = self.touch("a.flac")
        code, _, err = self.call("mp3", "--follow", src)
        self.assertEqual(code, 2)
        self.assertIn("--follow", err)
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


def has_libass():
    done = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True)
    return any(line.split()[1:2] == ["subtitles"] for line in done.stdout.splitlines())


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

    def make_subtitled(self, name, languages=(("eng", "Hello there"), ("fra", "Bonjour"))):
        """An MKV with one text subtitle track per (language, text) pair."""
        args = ["-f", "lavfi", "-i", "testsrc=s=320x240:r=25:d=3", "-f", "lavfi", "-i", "sine=d=3"]
        for number, (language, text) in enumerate(languages):
            srt = self.touch(f"{language}.srt", text=f"1\n00:00:00,000 --> 00:00:03,000\n{text}\n")
            args += ["-i", srt]
        maps = ["-map", "0", "-map", "1"] + sum((["-map", str(i + 2)] for i in range(len(languages))), [])
        meta = sum(([f"-metadata:s:s:{i}", f"language={lang}"] for i, (lang, _) in enumerate(languages)), [])
        target = self.path(name)
        ffmpeg(*args, *maps, "-c:v", "libx264", "-c:a", "aac", "-c:s", "srt", *meta, target)
        return target

    def subtitle_tracks(self, path):
        return [(s["codec_name"], s.get("tags", {}).get("language"))
                for s in self.streams(path)["streams"] if s["codec_type"] == "subtitle"]

    def frame_hash(self, path, seconds=1.0):
        done = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(seconds), "-i", path, "-frames:v", "1",
                               "-f", "md5", "-"], capture_output=True, text=True, check=True)
        return done.stdout.strip()

    def test_text_subtitles_are_kept_in_the_mp4_with_their_languages(self):
        src = self.make_subtitled("movie.mkv")
        done = self.run_cli("h264", src)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.subtitle_tracks(self.path("movie.mp4")),
                         [("mov_text", "eng"), ("mov_text", "fra")])
        self.assertNotIn("note:", done.stdout)

    def test_subtitles_none_drops_them(self):
        src = self.make_subtitled("movie.mkv")
        done = self.run_cli("h264", "--subtitles", "none", src)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.subtitle_tracks(self.path("movie.mp4")), [])

    def test_mkv_container_keeps_the_original_subtitle_format(self):
        src = self.make_subtitled("movie.mkv")
        done = self.run_cli("h264", "--container", "mkv", "--out", self.path("out"), src)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.subtitle_tracks(self.path("out", "movie.mkv")), [("subrip", "eng"), ("subrip", "fra")])

    def test_mkv_container_does_not_pick_up_its_own_output_format_from_folders(self):
        self.make_subtitled("movie.mkv")
        shutil.copy(self.path("movie.mkv"), self.path("other.mp4"))
        done = self.run_cli("h264", "--container", "mkv", "-n", self.tmp)
        self.assertIn("1 planned", done.stdout)

    @unittest.skipUnless(has_libass(), "this ffmpeg has no subtitles filter (libass)")
    def test_burning_hardcodes_the_chosen_track_into_the_picture(self):
        src = self.make_subtitled("movie.mkv")
        self.run_cli("h264", "--subtitles", "none", "--out", self.path("plain"), src)
        done = self.run_cli("h264", "--burn-subtitles", "fra", "--out", self.path("burned"), src)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(self.subtitle_tracks(self.path("burned", "movie.mp4")), [])
        self.assertNotEqual(self.frame_hash(self.path("plain", "movie.mp4")),
                            self.frame_hash(self.path("burned", "movie.mp4")))

    @unittest.skipUnless(has_libass(), "this ffmpeg has no subtitles filter (libass)")
    def test_burning_a_different_track_gives_a_different_picture(self):
        src = self.make_subtitled("movie.mkv", languages=(("eng", "A completely different sentence"), ("fra", "Court")))
        self.run_cli("h264", "--burn-subtitles", "eng", "--out", self.path("a"), src)
        self.run_cli("h264", "--burn-subtitles", "fra", "--out", self.path("b"), src)
        self.assertNotEqual(self.frame_hash(self.path("a", "movie.mp4")), self.frame_hash(self.path("b", "movie.mp4")))

    def test_burning_a_missing_language_fails_cleanly_and_leaves_nothing(self):
        src = self.make_subtitled("movie.mkv")
        done = self.run_cli("h264", "--burn-subtitles", "deu", src)
        self.assertEqual(done.returncode, 1)
        self.assertIn("no subtitle track matches 'deu' (tracks: eng, fra)", done.stdout)
        self.assertFalse(os.path.exists(self.path("movie.mp4")))
        self.assertEqual([f for f in os.listdir(self.tmp) if "partial" in f], [])

    def test_dry_run_of_a_broken_file_reports_failure(self):
        bad = self.touch("broken.mkv", text="not video")
        done = self.run_cli("h264", "-n", bad)
        self.assertEqual(done.returncode, 1)
        self.assertIn("failed", done.stdout)

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


def tags_of(path):
    return {k.lower(): v for k, v in
            ffprobe_json(path, "-show_format")["format"].get("tags", {}).items()}


def stream_kinds(path):
    return [(s["codec_type"], s["codec_name"], bool(s.get("disposition", {}).get("attached_pic")))
            for s in ffprobe_json(path, "-show_streams", "-show_entries",
                                  "stream=index,codec_type,codec_name:stream_disposition=attached_pic")["streams"]]


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
class MetadataPreservationTests(TempDirTestCase):
    """Real files carrying real metadata, converted and compared."""

    def run_cli(self, *argv):
        return subprocess.run([sys.executable, ENTRY, *argv], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)

    def make_cover(self, name="cover.jpg"):
        target = self.path(name)
        ffmpeg("-f", "lavfi", "-i", "color=c=red:s=96x96", "-frames:v", "1", target)
        return target

    def has_cover(self, path):
        return any(pic for _, _, pic in stream_kinds(path))

    # audio ----------------------------------------------------------------

    def make_flac(self, cover=True):
        target = self.path("song.flac")
        args = ["-f", "lavfi", "-i", "sine=d=1"]
        maps = ["-map", "0"]
        if cover:
            args += ["-i", self.make_cover()]
            maps += ["-map", "1"]
        meta = {"title": "Test Song", "artist": "Some Band", "album": "The Album", "album_artist": "Various",
                "composer": "J. Composer", "genre": "Rock", "date": "2019", "track": "3", "tracktotal": "12",
                "disc": "1", "disctotal": "2", "isrc": "USRC17607839", "bpm": "128", "copyright": "(c) X",
                "publisher": "Big Label", "custom_field": "my custom value"}
        flags = sum((["-metadata", f"{k}={v}"] for k, v in meta.items()), [])
        extra = ["-c:v", "copy", "-disposition:v", "attached_pic"] if cover else []
        ffmpeg(*args, *maps, "-c:a", "flac", *extra, *flags, target)
        os.utime(target, (1_425_463_872, 1_425_463_872))
        return target

    def test_flac_to_mp3_keeps_the_tags_the_cover_and_the_date(self):
        src = self.make_flac()
        done = self.run_cli("mp3", src)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        out = self.path("song.mp3")
        tags = tags_of(out)
        for name, value in (("title", "Test Song"), ("artist", "Some Band"), ("album", "The Album"),
                            ("album_artist", "Various"), ("composer", "J. Composer"), ("genre", "Rock"),
                            ("copyright", "(c) X"), ("publisher", "Big Label")):
            self.assertEqual(tags.get(name), value, name)
        self.assertEqual(tags["track"], "3/12")
        self.assertEqual(tags["disc"], "1/2")
        self.assertEqual(tags["tsrc"], "USRC17607839")
        self.assertEqual(tags["tbpm"], "128")
        self.assertEqual(tags["custom_field"], "my custom value")
        for stray in ("tracktotal", "disctotal", "isrc", "bpm"):
            self.assertNotIn(stray, tags)
        self.assertTrue(self.has_cover(out), "the cover picture must be carried over")
        self.assertEqual(int(os.stat(out).st_mtime), 1_425_463_872)

    def test_a_file_without_a_cover_gets_none_invented(self):
        src = self.make_flac(cover=False)
        self.assertEqual(self.run_cli("mp3", src).returncode, 0)
        self.assertFalse(self.has_cover(self.path("song.mp3")))

    def test_no_preserve_times_uses_the_current_time(self):
        src = self.make_flac(cover=False)
        self.run_cli("mp3", "--no-preserve-times", src)
        self.assertGreater(int(os.stat(self.path("song.mp3")).st_mtime), 1_500_000_000)

    # video ----------------------------------------------------------------

    def make_mkv(self, cover=True):
        target = self.path("movie.mkv")
        chapters = self.touch("ch.txt", text=";FFMETADATA1\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=1000\n"
                              "title=One\n[CHAPTER]\nTIMEBASE=1/1000\nSTART=1000\nEND=2000\ntitle=Two\n")
        args = ["-f", "lavfi", "-i", "testsrc=s=320x240:r=25:d=2", "-f", "lavfi", "-i", "sine=d=2", "-i", chapters]
        meta = {"title": "My Movie", "description": "A long synopsis.", "genre": "Drama", "actor": "Someone",
                "director": "A. Director", "custom_tag": "kept?"}
        flags = sum((["-metadata", f"{k}={v}"] for k, v in meta.items()), [])
        stream_meta = ["-metadata:s:a:0", "title=Director commentary", "-metadata:s:a:0", "language=eng"]
        attach = []
        if cover:
            attach = ["-attach", self.make_cover(), "-metadata:s:t", "mimetype=image/jpeg",
                      "-metadata:s:t", "filename=cover.jpg"]
        ffmpeg(*args, "-map", "0", "-map", "1", "-map_metadata", "2", "-c:v", "libx264", "-c:a", "aac",
               *flags, *stream_meta, *attach, target)
        os.utime(target, (1_404_201_600, 1_404_201_600))
        return target

    def test_mkv_output_keeps_everything(self):
        src = self.make_mkv()
        done = self.run_cli("h264", "--container", "mkv", "--out", self.path("out"), src)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        out = self.path("out", "movie.mkv")
        tags = tags_of(out)
        for name, value in (("title", "My Movie"), ("actor", "Someone"), ("director", "A. Director"),
                            ("custom_tag", "kept?"), ("description", "A long synopsis.")):
            self.assertEqual(tags.get(name), value, name)
        self.assertTrue(self.has_cover(out), "the cover attachment must survive")
        info = ffprobe_json(out, "-show_streams", "-show_chapters")
        self.assertEqual([c["tags"]["title"] for c in info["chapters"]], ["One", "Two"])
        audio = [s for s in info["streams"] if s["codec_type"] == "audio"][0]
        self.assertEqual(audio["tags"]["title"], "Director commentary")
        self.assertEqual(int(os.stat(out).st_mtime), 1_404_201_600)
        self.assertNotIn("note:", done.stdout)

    def test_mkv_keeps_embedded_fonts_with_styled_subtitles_and_drops_them_with_the_subtitles(self):
        ass = self.touch("s.ass", text="[Script Info]\nScriptType: v4.00+\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize\n"
                         "Style: Default,Custom Font,24\n[Events]\nFormat: Layer, Start, End, Style, Text\n"
                         "Dialogue: 0,0:00:00.00,0:00:02.00,Default,Styled\n")
        font = self.touch("custom.ttf", text="not a real font, just bytes")
        src = self.path("styled.mkv")
        ffmpeg("-f", "lavfi", "-i", "testsrc=s=320x240:r=25:d=2", "-i", ass, "-map", "0", "-map", "1",
               "-c:v", "libx264", "-c:s", "ass", "-attach", font, "-metadata:s:t", "mimetype=application/x-truetype-font", src)
        self.assertEqual(self.run_cli("h264", "--container", "mkv", "--out", self.path("kept"), src).returncode, 0)
        kept = ffprobe_json(self.path("kept", "styled.mkv"), "-show_streams")["streams"]
        fonts = [s for s in kept if s["codec_type"] == "attachment"]
        self.assertEqual([f["tags"]["filename"] for f in fonts], ["custom.ttf"])
        self.assertEqual(fonts[0]["tags"]["mimetype"], "application/x-truetype-font")
        self.assertEqual(self.run_cli("h264", "--container", "mkv", "--subtitles", "none", "--out",
                                      self.path("dropped"), src).returncode, 0)
        dropped = ffprobe_json(self.path("dropped", "styled.mkv"), "-show_streams")["streams"]
        self.assertEqual([s["codec_type"] for s in dropped if s["codec_type"] in ("attachment", "subtitle")], [])

    def test_mp4_auto_keeps_the_cover_and_standard_tags_and_reports_the_extras(self):
        src = self.make_mkv()
        done = self.run_cli("h264", src)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        out = self.path("movie.mp4")
        tags = tags_of(out)
        self.assertEqual((tags["title"], tags["genre"], tags["description"]), ("My Movie", "Drama", "A long synopsis."))
        self.assertTrue(self.has_cover(out))
        self.assertNotIn("actor", tags)
        self.assertIn("actor", done.stdout)
        self.assertIn("were left out", done.stdout)
        self.assertEqual(int(os.stat(out).st_mtime), 1_404_201_600)

    def test_mp4_tags_all_keeps_every_tag_and_reports_the_lost_cover(self):
        src = self.make_mkv()
        done = self.run_cli("h264", "--tags", "all", "--out", self.path("all"), src)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        out = self.path("all", "movie.mp4")
        tags = tags_of(out)
        self.assertEqual((tags["actor"], tags["director"], tags["custom_tag"]), ("Someone", "A. Director", "kept?"))
        self.assertFalse(self.has_cover(out))
        self.assertIn("cover picture(s) cannot be stored alongside QuickTime metadata", done.stdout)

    def test_mp4_with_no_cover_keeps_all_tags_automatically(self):
        src = self.make_mkv(cover=False)
        done = self.run_cli("h264", src)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(tags_of(self.path("movie.mp4"))["custom_tag"], "kept?")
        self.assertIn("QuickTime metadata", done.stdout)

    def test_chapters_survive_into_the_mp4(self):
        src = self.make_mkv()
        self.run_cli("h264", src)
        chapters = ffprobe_json(self.path("movie.mp4"), "-show_chapters")["chapters"]
        self.assertEqual([c["tags"]["title"] for c in chapters], ["One", "Two"])

    @unittest.skipUnless(HAVE_MEDIAINFO, "mediainfo not installed (MP4 track titles are not visible to ffprobe)")
    def test_mp4_keeps_track_titles(self):
        src = self.make_mkv(cover=False)
        self.run_cli("h264", src)
        done = subprocess.run(["mediainfo", "--Inform=Audio;%Title%", self.path("movie.mp4")],
                              capture_output=True, text=True)
        self.assertIn("Director commentary", done.stdout)

    def test_iphone_style_quicktime_tags_survive_into_the_mp4(self):
        src = self.path("phone.mov")
        ffmpeg("-f", "lavfi", "-i", "testsrc=s=320x240:r=25:d=2", "-f", "lavfi", "-i", "sine=d=2",
               "-c:v", "libx264", "-c:a", "aac", "-movflags", "use_metadata_tags",
               "-metadata", "com.apple.quicktime.location.ISO6709=+37.3349-122.0090+025.000/",
               "-metadata", "com.apple.quicktime.make=Apple", "-metadata", "com.apple.quicktime.model=iPhone 14 Pro",
               "-metadata", "com.apple.quicktime.creationdate=2019-06-15T10:30:00-0700", src)
        done = self.run_cli("h264", src)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        tags = tags_of(self.path("phone.mp4"))
        self.assertEqual(tags["com.apple.quicktime.location.iso6709"], "+37.3349-122.0090+025.000/")
        self.assertEqual(tags["com.apple.quicktime.make"], "Apple")
        self.assertEqual(tags["com.apple.quicktime.model"], "iPhone 14 Pro")
        self.assertEqual(tags["com.apple.quicktime.creationdate"], "2019-06-15T10:30:00-0700")

    def test_the_recording_date_survives(self):
        src = self.path("dated.mkv")
        ffmpeg("-f", "lavfi", "-i", "testsrc=s=320x240:r=25:d=1", "-c:v", "libx264",
               "-metadata", "creation_time=2019-06-15T10:30:00Z", src)
        self.run_cli("h264", src)
        self.assertTrue(tags_of(self.path("dated.mp4"))["creation_time"].startswith("2019-06-15T10:30:00"))

    # audiobooks ------------------------------------------------------------

    def make_book(self, embedded_cover=True, folder_image=False):
        book = self.path("Jane Doe - Sample Book (Bob Reader)")
        os.makedirs(book)
        meta = ["-metadata", "album=Sample Book", "-metadata", "artist=Jane Doe", "-metadata", "date=2018",
                "-metadata", "comment=A great listen", "-metadata", "copyright=(c) 2018 Jane",
                "-metadata", "language=eng"]
        args = ["-f", "lavfi", "-i", "sine=frequency=400:d=1"]
        maps = ["-map", "0"]
        extra = []
        if embedded_cover:
            args += ["-i", self.make_cover()]
            maps += ["-map", "1"]
            extra = ["-c:v", "copy", "-disposition:v", "attached_pic"]
        ffmpeg(*args, *maps, "-c:a", "libmp3lame", *extra, "-id3v2_version", "3", *meta,
               os.path.join(book, "1 - One.mp3"))
        ffmpeg("-f", "lavfi", "-i", "sine=frequency=500:d=1", "-c:a", "libmp3lame", os.path.join(book, "2 - Two.mp3"))
        if folder_image:
            shutil.copy(self.make_cover("folder.jpg"), os.path.join(book, "folder.jpg"))
        for name in os.listdir(book):
            os.utime(os.path.join(book, name), (1_525_510_800, 1_525_510_800))
        return book

    def test_an_audiobook_keeps_the_cover_the_book_tags_and_the_date(self):
        book = self.make_book()
        done = self.run_cli("m4b", "--out", self.path("out"), book)
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        out = self.path("out", "Jane Doe - Sample Book.m4b")
        tags = tags_of(out)
        self.assertEqual((tags["date"], tags["comment"], tags["copyright"]), ("2018", "A great listen", "(c) 2018 Jane"))
        self.assertEqual((tags["title"], tags["artist"], tags["composer"]), ("Sample Book", "Jane Doe", "Bob Reader"))
        self.assertTrue(self.has_cover(out))
        audio = [s for s in ffprobe_json(out, "-show_streams")["streams"] if s["codec_type"] == "audio"][0]
        self.assertEqual(audio["tags"]["language"], "eng")
        self.assertEqual(int(os.stat(out).st_mtime), 1_525_510_800)

    def test_an_audiobook_uses_a_folder_image_when_no_cover_is_embedded(self):
        book = self.make_book(embedded_cover=False, folder_image=True)
        self.assertEqual(self.run_cli("m4b", "--out", self.path("out"), book).returncode, 0)
        self.assertTrue(self.has_cover(self.path("out", "Jane Doe - Sample Book.m4b")))

    def test_an_audiobook_without_any_cover_gets_none(self):
        book = self.make_book(embedded_cover=False)
        self.assertEqual(self.run_cli("m4b", "--out", self.path("out"), book).returncode, 0)
        self.assertFalse(self.has_cover(self.path("out", "Jane Doe - Sample Book.m4b")))


@unittest.skipUnless(HAVE_MAGICK and HAVE_EXIFTOOL, "ImageMagick and exiftool are needed")
class ImageMetadataTests(TempDirTestCase):
    """A photo with camera, GPS, XMP and IPTC data, converted to each format."""

    WANTED = ("Make", "Model", "DateTimeOriginal", "Artist", "Copyright", "ImageDescription",
              "GPSLatitude", "GPSLongitude", "Title", "Creator", "Rating")

    def make_photo(self):
        target = self.path("photo.jpg")
        subprocess.run(imagemagick() + ["-size", "60x40", "gradient:orange-blue", target], check=True)
        subprocess.run(["exiftool", "-q", "-overwrite_original", "-Make=Canon", "-Model=EOS R5",
                        "-DateTimeOriginal=2019:06:15 10:30:00", "-Artist=Jane", "-Copyright=(c) 2019 Jane",
                        "-ImageDescription=A nice view", "-GPSLatitude=37.3349", "-GPSLatitudeRef=N",
                        "-GPSLongitude=122.0090", "-GPSLongitudeRef=W", "-XMP-dc:Title=XMP Title",
                        "-XMP-dc:Creator=Jane", "-XMP-xmp:Rating=5", "-IPTC:Keywords=holiday",
                        "-IPTC:Caption-Abstract=IPTC caption", "-Orientation=6", "-n", target], check=True)
        os.utime(target, (1_560_594_600, 1_560_594_600))
        return target

    def names_in(self, path):
        done = subprocess.run(["exiftool", "-a", "-G0", "-j", path], capture_output=True, text=True)
        return {key.split(":", 1)[1] for key in json.loads(done.stdout)[0] if ":" in key}

    def convert(self, fmt, *extra):
        return subprocess.run([sys.executable, ENTRY, fmt, "--out", self.path(fmt), *extra, self.path("photo.jpg")],
                              capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def test_jpg_and_png_keep_all_the_photo_metadata_and_the_date(self):
        self.make_photo()
        for fmt in ("jpg", "png"):
            done = self.convert(fmt)
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
            out = self.path(fmt, f"photo.{fmt}")
            present = self.names_in(out)
            missing = [name for name in self.WANTED + ("Keywords", "Caption-Abstract") if name not in present]
            self.assertEqual(missing, [], f"{fmt} lost {missing}")
            self.assertEqual(int(os.stat(out).st_mtime), 1_560_594_600)
            self.assertNotIn("note:", done.stdout)

    def test_webp_keeps_exif_and_xmp_and_reports_that_iptc_was_left_out(self):
        self.make_photo()
        done = self.convert("webp")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        present = self.names_in(self.path("webp", "photo.webp"))
        self.assertEqual([n for n in self.WANTED if n not in present], [])
        self.assertNotIn("Keywords", present)
        self.assertIn("IPTC data", done.stdout)

    def test_rotation_is_applied_and_the_orientation_tag_reset(self):
        self.make_photo()
        self.convert("png")
        done = subprocess.run(["exiftool", "-s3", "-n", "-Orientation", self.path("png", "photo.png")],
                              capture_output=True, text=True)
        self.assertIn(done.stdout.strip(), ("1", ""))


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
