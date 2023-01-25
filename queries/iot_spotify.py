"""

    Greynir: Natural language processing for Icelandic

    Example of a plain text query processor module.

    Copyright (C) 2022 Miðeind ehf.

       This program is free software: you can redistribute it and/or modify
       it under the terms of the GNU General Public License as published by
       the Free Software Foundation, either version 3 of the License, or
       (at your option) any later version.
       This program is distributed in the hope that it will be useful,
       but WITHOUT ANY WARRANTY; without even the implied warranty of
       MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
       GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see http://www.gnu.org/licenses/.


    This module is an example of a plug-in query response module
    for the Greynir query subsystem. It handles plain text queries, i.e.
    ones that do not require parsing the query text. For this purpose
    it only needs to implement the handle_plain_text() function, as
    shown below.


"""
# TODO: Make grammar
# TODO: Delete commented out alt code at bottom of file
"""
with GreynirBin.get_db() as db:
        db.lookup("ordid") #output er tupla, ef seinna elementid er ekki tomur listi tha er thetta islenskt
"""
from typing import cast, Optional, Dict, List

import random
from typing_extensions import TypedDict
import re

from reynir import NounPhrase

from query import Query
from queries.extras.spotify import SpotifyClient, SpotifyDeviceData, SpotifyError
from queries import gen_answer


class _SpotifyRegexObject(TypedDict):
    target_types: set[str]
    rx: List[str]


def help_text(lemma: str) -> str:
    """Help text to return when query.py is unable to parse a query but
    one of the above lemmas is found in it"""
    return "Ég skil þig ef þú segir til dæmis: {0}.".format(
        random.choice(("Spilaðu Þorparann með Pálma Gunnarssyni",))
    )


_SPOTIFY_REGEXES: Dict[str, _SpotifyRegexObject] = {
    "track": {
        "target_types": {"track"},
        "rx": [r"^spilaðu lagið (?P<track>[\w|\s]+) með (?P<artist>[\w|\s]+)$"],
    },
    "album": {
        "target_types": {"album"},
        "rx": [r"^spilaðu plötuna (?P<album>[\w|\s]+) með (?P<artist>[\w|\s]+)$"],
    },
    "track_or_album": {
        "target_types": {"track", "album"},
        "rx": [r"^spilaðu (?P<track_or_album>[\w|\s]+) með (?P<artist>[\w|\s]+)$"],
    },
    "playlist": {
        "target_types": {"playlist"},
        "rx": [r"^spilaðu (spilunar|laga)listann (?P<playlist>[\w|\s]+)$"],
    },
    "artist": {
        "target_types": {"artist"},
        "rx": [r"^spilaðu (tónlistar|lista)manninn (?P<artist>[\w|\s]+)$"],
    },
    "anything": {
        "target_types": {"track", "album", "playlist", "artist"},
        "rx": [r"^spilaðu (?P<anything>[\w|\s]+)$"],
    },
}


def handle_plain_text(q: Query) -> bool:
    """Handle a plain text query requesting Spotify to play a specific track by a specific artist."""

    if not q.client_id:
        return False

    ql = q.query.strip().rstrip("?")
    keys = [
        "track",
        "album",
        "track_or_album",
        "playlist",
        "artist",
        "anything",
    ]
    names: Dict[str, Optional[str]] = {key: None for key in keys}
    for key in keys:
        for rx in _SPOTIFY_REGEXES[key]["rx"]:
            m = re.search(rx, ql, flags=re.IGNORECASE)
            if m:
                cd = q.client_data("spotify")
                if cd is None:
                    answer = "Það vantar að tengja Spotify aðgang."
                    q.set_answer(*gen_answer(answer))
                    return True
                gd = m.groupdict()
                names[key] = nominative_or_none(gd.get(key))
                device_data = cast(SpotifyDeviceData, cd)
                spotify_client = SpotifyClient(
                    device_data,
                    q.client_id,
                )
                target_types = _SPOTIFY_REGEXES[key]["target_types"]
                try:
                    spotify_client.play(target_types=target_types, **names)
                except SpotifyError as e:
                    q.set_url(spotify_client.track_url)
                answer = f"Ég kveiki á {spotify_client.track_name or spotify_client.album_name}."
                q.set_answer({"answer": answer}, answer, "")
                return True
    return False


def nominative_or_none(name: Optional[str]) -> Optional[str]:
    """
    Returns the nominative form of a noun phrase, the input string, or None if the input is None.
    """
    return None if name is None else NounPhrase(name).nominative or name


# í stað þess að nota þetta þá er hægt að nota eitthvað svona
# def extract_entities_and_intent(query: str) -> Tuple[str, Dict[str, str]]:
#     entities = {}
#     intent = None

#     def match_song(query: str) -> Tuple[str, Dict[str, str]]:
#         nonlocal entities
#         song_match = re.search(r"(.*)(by)(.*)", query)
#         if song_match:
#             entities["song_name"] =song_match.group(1).strip()
#             entities["artist_name"] =song_match.group(3).strip()
#             return "play_song", entities
#         else:
#             return None, {}

#     def match_artist(query: str) -> Tuple[str, Dict[str, str]]:
#         nonlocal entities
#         artist_match = re.search(r"(.*)(by)(.*)", query)
#         if artist_match:
#             entities["artist_name"] = artist_match.group(3).strip()
#             return "play_artist", entities
#         else:
#             return None, {}

#     def match_ambigious_artist(query: str) -> Tuple[str, Dict[str, str]]:
#         nonlocal entities
#         ambigious_artist_match = re.search(r"(play)(.*)", query)
#         if ambigious_artist_match:
#             entities["artist_name"] = ambigious_artist_match.group(2).strip()
#             return "play_artist", entities
#         else:
#             return None, {}

#     def match_play_pause(query: str) -> Tuple[str, Dict[str, str]]:
#         play_pause_match = re.search(r'(play|pause)', query)
#         if play_pause_match:
#             return play_pause_match.group(1), {}
#         else:
#             return None, {}

#     intents = [match_song, match_artist, match_ambigious_artist, match_play_pause]

#     for match in intents:
#         intent, entities = match(query)
#         if intent:
#             return intent, entities

#     return None, {}
