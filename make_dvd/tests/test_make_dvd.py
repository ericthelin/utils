#!/usr/bin/env python3
"""Unit tests for make_dvd.py planning and authoring logic.

Run directly (python3 tests/test_make_dvd.py) or via tests/run_tests.sh.
"""

import importlib.util
import os
import unittest

TOOL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("make_dvd", os.path.join(TOOL_DIR, "make_dvd.py"))
make_dvd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_dvd)


def info(index, duration=600, has_audio=True):
    return {"index": index, "path": f"/x/movie_{index}.mkv", "mpg": f"/w/title{index}.mpg",
            "duration": duration, "has_audio": has_audio}


class PlanningTests(unittest.TestCase):
    def test_short_content_is_capped_at_max_bitrate(self):
        self.assertEqual(make_dvd.video_kbps(600, make_dvd.DISC_BYTES["dvd5"]), make_dvd.MAX_VIDEO_KBPS)

    def test_long_content_fits_disc(self):
        seconds = 3 * 3600
        kbps = make_dvd.video_kbps(seconds, make_dvd.DISC_BYTES["dvd5"])
        total_bytes = (kbps + make_dvd.AUDIO_KBPS) * 1000 / 8 * seconds
        self.assertLess(total_bytes, make_dvd.DISC_BYTES["dvd5"])
        self.assertLess(kbps, make_dvd.MAX_VIDEO_KBPS)

    def test_dvd9_allows_higher_bitrate_than_dvd5(self):
        seconds = 4 * 3600
        self.assertGreater(make_dvd.video_kbps(seconds, make_dvd.DISC_BYTES["dvd9"]),
                           make_dvd.video_kbps(seconds, make_dvd.DISC_BYTES["dvd5"]))

    def test_pick_standard(self):
        self.assertEqual(make_dvd.pick_standard(25.0), "pal")
        self.assertEqual(make_dvd.pick_standard(29.97), "ntsc")
        self.assertEqual(make_dvd.pick_standard(23.976), "ntsc")

    def test_pick_aspect_prefers_widescreen_if_any_wide(self):
        self.assertEqual(make_dvd.pick_aspect([1.33, 1.78]), "16:9")
        self.assertEqual(make_dvd.pick_aspect([1.33, 1.25]), "4:3")

    def test_parse_probe_applies_sample_aspect_ratio(self):
        data = {"format": {"duration": "12.5"}, "streams": [
            {"codec_type": "video", "width": 720, "height": 480,
             "sample_aspect_ratio": "32:27", "r_frame_rate": "30000/1001"}]}
        parsed = make_dvd.parse_probe(data, "a.avi")
        self.assertAlmostEqual(parsed["dar"], 16 / 9, places=2)
        self.assertFalse(parsed["has_audio"])

    def test_parse_probe_reads_chapters(self):
        data = {"format": {"duration": "60"}, "streams": [{"codec_type": "video", "width": 4, "height": 3}],
                "chapters": [{"start_time": "0.000000"}, {"start_time": "30.5"}]}
        self.assertEqual(make_dvd.parse_probe(data, "a.mkv")["chapters"], [0.0, 30.5])

    def test_parse_probe_rejects_audio_only(self):
        with self.assertRaises(ValueError):
            make_dvd.parse_probe({"format": {"duration": "1"}, "streams": [{"codec_type": "audio"}]}, "a.mp3")


class FormattingTests(unittest.TestCase):
    def test_chapter_marks_every_five_minutes_without_source_chapters(self):
        self.assertEqual(make_dvd.chapter_marks(20 * 60), "0,5:00,10:00,15:00")
        self.assertEqual(make_dvd.chapter_marks(30), "0")
        self.assertEqual(make_dvd.chapter_times(35 * 60, [0.0])[1], "5 min")

    def test_source_chapters_are_used(self):
        times, origin = make_dvd.chapter_times(3600, [0.0, 300.4, 1200.0, 3000.0])
        self.assertEqual((times, origin), ([0, 300, 1200, 3000], "source"))
        self.assertEqual(make_dvd.chapter_marks(3600, [0.0, 300.0]), "0,5:00")

    def test_source_chapters_too_close_are_dropped(self):
        times, _ = make_dvd.chapter_times(3600, [0, 5, 600, 604, 1800, 3595])
        self.assertEqual(times, [0, 600, 1800])

    def test_too_many_source_chapters_are_thinned_to_dvd_limit(self):
        times, origin = make_dvd.chapter_times(6 * 3600, [i * 60.0 for i in range(300)])
        self.assertLessEqual(len(times), make_dvd.MAX_CHAPTERS)
        self.assertEqual(origin, "source")

    def test_chapter_marks_use_hours(self):
        self.assertIn("1:00:00", make_dvd.chapter_marks(2 * 3600))

    def test_title_label_cleans_and_truncates(self):
        self.assertEqual(make_dvd.title_label("/a/My_Movie.mkv"), "My Movie")
        self.assertEqual(len(make_dvd.title_label("/a/" + "x" * 100 + ".mkv")), 42)

    def test_iso_label_is_iso9660_safe(self):
        self.assertEqual(make_dvd.iso_label("My Movie: 2!"), "MY_MOVIE__2_")

    def test_menu_boxes_fit_and_do_not_overlap(self):
        boxes = make_dvd.menu_boxes(10, 480)
        self.assertEqual(len(boxes), 10)
        self.assertLessEqual(boxes[-1][3], 480)
        for upper, lower in zip(boxes, boxes[1:]):
            self.assertLess(upper[3], lower[1])


class ProgressTests(unittest.TestCase):
    def test_format_duration(self):
        self.assertEqual(make_dvd.format_duration(75), "1:15")
        self.assertEqual(make_dvd.format_duration(3725), "1:02:05")

    def test_render_bar_clamps(self):
        self.assertEqual(make_dvd.render_bar(0.5, 10), "[#####-----]")
        self.assertEqual(make_dvd.render_bar(2, 4), "[####]")
        self.assertEqual(make_dvd.render_bar(-1, 4), "[----]")

    def test_progress_line_fits_columns(self):
        line = make_dvd.progress_line(0.42, "encoding 2/3", 83, 112, "14:32", 80)
        self.assertLess(len(line), 80)
        self.assertIn("42.0%", line)
        self.assertIn("ETA 1:52", line)

    def test_progress_line_without_eta(self):
        self.assertIn("ETA --:--", make_dvd.progress_line(0, "x", 0, None, None, 100))

    def test_eta_tracks_observed_rate(self):
        now = [0.0]
        progress = make_dvd.Progress(100, stream=open(os.devnull, "w"), clock=lambda: now[0], wall=lambda: 0)
        self.assertIsNone(progress.eta_seconds())
        now[0] = 10.0
        progress.update(25, "x")
        self.assertAlmostEqual(progress.eta_seconds(), 30.0)
        now[0] = 20.0
        progress.update(80, "x")
        self.assertAlmostEqual(progress.eta_seconds(), 5.0)

    def test_finish_stage_advances_by_reserved_fraction(self):
        progress = make_dvd.Progress(103, stream=open(os.devnull, "w"))
        progress.finish_stage("author", "x")
        self.assertAlmostEqual(progress.done, 103 * 0.03 / 1.05)


class BurnTests(unittest.TestCase):
    BLANK = ("Media current: DVD-R sequential\nMedia status : is blank\n"
             "Media blocks : 0 readable , 2295104 writable , 2295104 overall\n")
    CLOSED = ("Media current: DVD-ROM\nMedia status : is written , is closed\n"
              "Media blocks : 1079787 readable , 0 writable , 1079787 overall\n")

    def test_parse_media_blank(self):
        media = make_dvd.parse_media(self.BLANK)
        self.assertEqual(media["status"], "blank")
        self.assertEqual(media["writable_blocks"], 2295104)
        self.assertEqual(media["profile"], "DVD-R sequential")

    def test_parse_media_closed_and_empty_drive(self):
        self.assertEqual(make_dvd.parse_media(self.CLOSED)["status"], "closed")
        self.assertEqual(make_dvd.parse_media("Drive current: -outdev '/dev/sr0'")["status"], "none")

    def test_parse_media_drive_failure(self):
        media = make_dvd.parse_media("libburn : FAILURE : Cannot access '/dev/sr0' as SG_IO CDROM drive")
        self.assertEqual(media["status"], "error")
        self.assertIn("Cannot access", make_dvd.media_problem(media, 1, "/dev/sr0"))

    def test_media_problem_reports_each_failure(self):
        gib = 2 * 1024 ** 3
        self.assertIsNone(make_dvd.media_problem(make_dvd.parse_media(self.BLANK), gib, "/dev/sr0"))
        self.assertIn("not blank", make_dvd.media_problem(make_dvd.parse_media(self.CLOSED), gib, "/dev/sr0"))
        self.assertIn("No disc", make_dvd.media_problem(make_dvd.parse_media(""), gib, "/dev/sr0"))
        self.assertIn("needs", make_dvd.media_problem(make_dvd.parse_media(self.BLANK), 5 * 1024 ** 3, "/dev/sr0"))

    def test_burn_command_speed_optional(self):
        self.assertIn("speed=8", make_dvd.burn_command("a.iso", "/dev/sr0", 8))
        self.assertFalse([a for a in make_dvd.burn_command("a.iso", "/dev/sr0", 0) if a.startswith("speed=")])
        self.assertEqual(make_dvd.burn_command("a.iso", "/dev/sr0", 8)[-1], "a.iso")

    def test_parse_burn_progress(self):
        self.assertEqual(make_dvd.parse_burn_progress("Track 01:  148 of 2263 MB written (fifo 100%)"), (148, 2263))
        self.assertEqual(make_dvd.parse_burn_progress("xorriso : UPDATE :  5 of 9 MB written"), (5, 9))
        self.assertIsNone(make_dvd.parse_burn_progress("Fixating..."))

    def test_default_output_is_in_cwd_not_source_dir(self):
        self.assertEqual(make_dvd.default_output(["/media/movies/Film (2002).m4v"], "/work"), "/work/Film (2002).iso")
        self.assertEqual(make_dvd.default_output(["/a/x.mkv", "/b/y.mkv"], "/work"), "/work/dvd.iso")


class AuthoringTests(unittest.TestCase):
    def test_menu_xml_autoplays_and_chains_titles(self):
        xml = make_dvd.build_dvdauthor_xml("/d", "ntsc", "16:9", [info(1), info(2)], "/w/menu.mpg", 7)
        self.assertIn('pause="7"', xml)
        self.assertIn("jump title 1;", xml)
        self.assertIn("jump title 2;", xml)
        self.assertIn("call vmgm menu;", xml)
        self.assertEqual(xml.count("<button"), 2)

    def test_no_menu_xml_starts_title_one(self):
        xml = make_dvd.build_dvdauthor_xml("/d", "pal", "4:3", [info(1)], None)
        self.assertIn("<fpc> jump title 1; </fpc>", xml)
        self.assertNotIn("<menus>", xml)
        self.assertNotIn("call vmgm menu", xml)

    def test_spumux_xml_has_button_per_box(self):
        xml = make_dvd.build_spumux_xml(make_dvd.menu_boxes(3, 576))
        self.assertEqual(xml.count("<button"), 3)

    def test_encode_command_adds_silent_audio_when_missing(self):
        cmd = make_dvd.encode_command("in.mkv", "out.mpg", info(1, has_audio=False), "ntsc", "4:3", 5000)
        self.assertIn("anullsrc=r=48000:cl=stereo", cmd)
        self.assertIn("1:a:0", cmd)
        self.assertIn("5000k", cmd)

    def test_encode_command_uses_closed_gops_for_chapter_cells(self):
        cmd = make_dvd.encode_command("in.mkv", "out.mpg", info(1), "ntsc", "16:9", 5000)
        self.assertEqual(cmd[cmd.index("-flags") + 1], "+cgop")
        self.assertEqual(cmd[cmd.index("-sc_threshold") + 1], "1000000000")

    def test_encode_command_maps_source_audio(self):
        cmd = make_dvd.encode_command("in.mkv", "out.mpg", info(1), "pal", "16:9", 5000)
        self.assertIn("0:a:0", cmd)
        self.assertIn("pal-dvd", cmd)


if __name__ == "__main__":
    unittest.main()
