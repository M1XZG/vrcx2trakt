from vrcx2trakt import match


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
