from vrcx2trakt.trakt_client import TraktClient


def test_resolve_episode_uses_exact_show_year_and_episode_title():
    client = object.__new__(TraktClient)

    def request(method, path, **kwargs):
        if path == "/search/show":
            return [
                {
                    "show": {
                        "title": "Grounded for Life",
                        "year": 2001,
                        "ids": {"trakt": 4707, "slug": "grounded-for-life"},
                    }
                },
                {
                    "show": {
                        "title": "For Life",
                        "year": 2020,
                        "ids": {"trakt": 166378, "slug": "for-life-2020-166378"},
                    }
                },
                {
                    "show": {
                        "title": "For Life",
                        "year": 2020,
                        "ids": {"trakt": 148103, "slug": "for-life"},
                    }
                },
            ]
        if path == "/shows/for-life-2020-166378/seasons/1/episodes/1":
            return {
                "season": 1,
                "number": 1,
                "title": "Episode 1",
                "ids": {"trakt": 999},
            }
        if path == "/shows/for-life/seasons/1/episodes/1":
            return {
                "season": 1,
                "number": 1,
                "title": "Pilot",
                "ids": {"trakt": 3822237},
            }
        raise AssertionError(path)

    client._request = request

    resolved = client.resolve_episode(
        "For Life",
        1,
        1,
        year=2020,
        episode_title="Pilot",
    )

    assert resolved["show_trakt_id"] == 148103
    assert resolved["episode_trakt_id"] == 3822237
    assert resolved["episode_title"] == "Pilot"
