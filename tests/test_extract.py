from vrcx2trakt import extract


def test_parse_popcorn_palace_movie_with_release_date():
    assert extract.parse_video_name("PopcornPalace", "Pinocchio - 1940-02-23") == (
        "Pinocchio",
        1940,
        "movie",
        None,
    )


def test_parse_movie_and_chill_movie_with_year():
    assert extract.parse_video_name("Movie&Chill", "The Matrix (1999)") == (
        "The Matrix",
        1999,
        "movie",
        None,
    )


def test_parse_lsmedia_movie_with_year():
    title, year, media_type, episode = extract.parse_video_name(
        "LSMedia", "Spirited Away (2001)"
    )

    assert title == "Spirited Away"
    assert year == 2001
    assert media_type == "movie"
    assert episode is None


def test_parse_episode_sxe_style():
    title, year, media_type, episode = extract.parse_video_name(
        "PopcornPalace", "86 EIGHTY-SIX - S1E3"
    )

    assert title == "86 EIGHTY-SIX"
    assert year is None
    assert media_type == "episode"
    assert episode == {"show": "86 EIGHTY-SIX", "season": 1, "episode": 3}


def test_parse_episode_season_episode_style():
    title, year, media_type, episode = extract.parse_video_name(
        "PopcornPalace", "The IT Crowd Season: 1 Episode: 6"
    )

    assert title == "The IT Crowd"
    assert year is None
    assert media_type == "episode"
    assert episode == {"show": "The IT Crowd", "season": 1, "episode": 6}


def test_strip_quality_tags_and_clean_spaces():
    assert extract.strip_quality_tags("Dune 2021 1080p") == "Dune 2021"
    assert extract.strip_quality_tags("Movie [4K]") == "Movie"
    assert extract.clean_spaces("  Dune   Part   Two  ") == "Dune Part Two"


def test_parse_unknown_youtube_like_title_without_year():
    assert extract.parse_video_name("PopcornPalace", "lofi beats live stream") == (
        "lofi beats live stream",
        None,
        "unknown",
        None,
    )


def test_watched_date_from_iso_timestamp():
    assert extract.watched_date("2026-06-25T22:06:44.000Z") == "2026-06-25"


def test_collapse_rows_deduplicates_same_source_title_year_and_date():
    rows = [
        (
            1,
            "2026-06-25T22:10:00.000Z",
            "Pinocchio - 1940-02-23",
            "PopcornPalace",
            "wrld_unknown:123",
        ),
        (
            2,
            "2026-06-25T22:06:44.000Z",
            "Pinocchio - 1940-02-23",
            "PopcornPalace",
            "wrld_unknown:456",
        ),
    ]

    candidates, raw_counts = extract.collapse_rows(rows, {}, {})

    assert raw_counts["PopcornPalace"] == 2
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["parsed_title"] == "Pinocchio"
    assert candidate["parsed_year"] == 1940
    assert candidate["watched_date"] == "2026-06-25"
    assert candidate["watched_at"] == "2026-06-25T22:06:44.000Z"
    assert candidate["play_count"] == 2
    assert candidate["row_ids"] == [1, 2]
