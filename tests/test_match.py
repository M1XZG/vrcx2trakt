from vrcx2trakt import extract, match
from vrcx2trakt.trakt_client import TraktClient


def test_food_wars_episode_label_resolves_despite_show_punctuation():
    raw_name = (
        "Food Wars Shokugeki no Soma - The Memory of a Single Dish "
        "- S1E12 - 2015-06-20"
    )
    title, year, media_type, episode = extract.parse_video_name("PopcornPalace", raw_name)
    candidate = {
        "parsed_title": title,
        "parsed_year": year,
        "media_type": media_type,
        "episode": episode,
    }
    client = object.__new__(TraktClient)

    def request(method, path, **kwargs):
        if path == "/search/show":
            return [{
                "show": {
                    "title": "Food Wars! Shokugeki no Soma",
                    "year": 2015,
                    "ids": {"trakt": 94084, "slug": "food-wars-shokugeki-no-soma"},
                }
            }]
        if path == "/shows/food-wars-shokugeki-no-soma/seasons/1/episodes/12":
            return {
                "season": 1,
                "number": 12,
                "title": "The Memory of a Single Dish",
                "ids": {"trakt": 1891267},
            }
        raise AssertionError(path)

    client._request = request

    resolved = match.resolve(client, candidate)

    assert resolved is not None
    assert resolved["trakt_id"] == 1891267
    assert resolved["trakt_title"] == (
        "Food Wars! Shokugeki no Soma S1E12: The Memory of a Single Dish"
    )
    assert match.suggested_include(candidate, resolved) == 1


def test_show_details_preserve_year_and_episode_title():
    assert match.show_details_from_episode("For Life (2020) - Pilot") == (
        "For Life",
        2020,
        "Pilot",
    )


def test_episode_resolution_passes_disambiguating_metadata():
    class Client:
        def resolve_episode(
            self,
            show,
            season,
            episode,
            *,
            year=None,
            episode_title=None,
        ):
            assert (show, season, episode) == ("For Life", 1, 1)
            assert year == 2020
            assert episode_title == "Pilot"
            return {
                "show_title": "For Life",
                "episode_trakt_id": 3822237,
                "season": 1,
                "number": 1,
                "episode_title": "Pilot",
            }

    candidate = {
        "media_type": "episode",
        "episode": {
            "show": "For Life (2020) - Pilot",
            "season": 1,
            "episode": 1,
        },
    }

    resolved = match.resolve(Client(), candidate)

    assert resolved["trakt_id"] == 3822237
    assert resolved["trakt_title"] == "For Life S1E1: Pilot"


def test_episode_cache_key_includes_show_year():
    candidate = {
        "media_type": "episode",
        "episode": {
            "show": "For Life (2020) - Pilot",
            "season": 1,
            "episode": 1,
        },
    }

    assert match.cache_key(candidate) == "ep|For Life|2020|1|1"
