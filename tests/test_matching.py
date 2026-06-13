"""Tests for the torrent title-matching logic in app.py.

This is the fiddliest, most regression-prone code in the project (we keep
touching it: Gintama, Boruto, Kaï, season coherence, episode ordering). The
cases below are real ones that previously broke. Pure stdlib unittest, no
dependencies — run with:  python -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import (  # noqa: E402
    manual_title_match,
    check_title_match,
    season_compatible,
    extract_season_number,
    episode_matches,
    is_french_subbed,
    parse_episode_number,
)


class ManualTitleMatch(unittest.TestCase):
    """Recall-oriented match used for the manual search box."""

    def test_accepts_same_franchise_specials_and_kai(self):
        self.assertTrue(manual_title_match(
            "gintama", "GINTAMA - Mr. Ginpachi's Zany Class S01E09 VOSTFR 1080p"))
        self.assertTrue(manual_title_match(
            "gintama", "[Triggerforce] Gintama Kai 04 VOSTFR"))

    def test_accepts_sequel_when_leading(self):
        self.assertTrue(manual_title_match("naruto", "[Group] Naruto Shippuden 130 VOSTFR"))

    def test_rejects_word_in_the_middle(self):
        # "Naruto" appears, but the title is a different series (leads with Boruto).
        self.assertFalse(manual_title_match(
            "naruto", "Boruto Naruto Next Generations S01E293 VOSTFR"))

    def test_multiword_query_is_distinct(self):
        self.assertTrue(manual_title_match("one piece", "One Piece 1085 VOSTFR"))
        self.assertFalse(manual_title_match("one piece", "One Punch Man VOSTFR"))


class CheckTitleMatch(unittest.TestCase):
    """Strict match used for automatic episode fetching."""

    def test_rejects_sequel_extension(self):
        # Searching "Naruto" must not return "Naruto Shippuden".
        self.assertFalse(check_title_match("naruto", "Naruto Shippuden 5 VOSTFR", query_season=1))

    def test_accepts_plain_series(self):
        self.assertTrue(check_title_match("naruto", "Naruto 5 VOSTFR", query_season=1))


class SeasonHandling(unittest.TestCase):
    def test_extract_season_number(self):
        self.assertEqual(extract_season_number("Fire Force S02 VOSTFR"), 2)
        self.assertEqual(extract_season_number("Enen no Shouboutai: Ni no Shou"), 2)
        self.assertEqual(extract_season_number("Anime Season 3"), 3)
        self.assertIsNone(extract_season_number("Naruto"))

    def test_season_compatible(self):
        # Season 1 query should not accept a season 3 release.
        self.assertFalse(season_compatible("Fire Force", "Fire Force S03 VOSTFR", query_season=1))
        self.assertTrue(season_compatible("Fire Force", "Fire Force S01 VOSTFR", query_season=1))


class FrenchSubbed(unittest.TestCase):
    def test_accepts_vostfr_and_fre_tag(self):
        self.assertTrue(is_french_subbed("naruto shippuden vostfr 1080p"))
        self.assertTrue(is_french_subbed("gintama [multiple subtitle] [eng][fre]"))

    def test_rejects_non_french(self):
        self.assertFalse(is_french_subbed("naruto english dub only"))
        self.assertFalse(is_french_subbed("one piece raw jp"))


class EpisodeParsing(unittest.TestCase):
    def test_episode_matches(self):
        self.assertTrue(episode_matches("Anime - 05 VOSTFR", 5))
        self.assertFalse(episode_matches("Anime - 05 VOSTFR", 6))
        self.assertTrue(episode_matches("Anime 01-12 Batch", 7))  # batch covers it

    def test_parse_episode_number(self):
        self.assertEqual(parse_episode_number("Anime - 05.mkv"), 5)
        self.assertEqual(parse_episode_number("[Grp] Anime S01E12.mkv"), 12)
        self.assertIsNone(parse_episode_number("Movie.mkv"))


if __name__ == "__main__":
    unittest.main()
