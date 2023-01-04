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
# TODO: Negla nöfnum í nefnifall
"""
with GreynirBin.get_db() as db:
        db.lookup("ordid") #output er tupla, ef seinna elementid er ekki tomur listi tha er thetta islenskt
"""
from typing import cast

import random
import re

from reynir.bindb import GreynirBin

from query import Query
from queries.extras.spotify import SpotifyClient, SpotifyDeviceData
from queries import gen_answer


def help_text(lemma: str) -> str:
    """Help text to return when query.py is unable to parse a query but
    one of the above lemmas is found in it"""
    return "Ég skil þig ef þú segir til dæmis: {0}.".format(
        random.choice(("Spilaðu Þorparann með Pálma Gunnarssyni",))
    )


# The context-free grammar for the queries recognized by this plug-in module

_SPOTIFY_REGEXES = [
    # r"^spilaðu ([\w|\s]+) með ([\w|\s]+) á spotify?$",
    # r"^spilaðu ([\w|\s]+) á spotify$",
    # r"^spilaðu ([\w|\s]+) á spotify",
    r"^spilaðu plötuna (?P<album>[\w|\s]+) með (?P<artist>[\w|\s]+)$",
    r"^spilaðu lagið (?P<song>[\w|\s]+) með (?P<artist>[\w|\s]+)$",
    r"^spilaðu (?P<album_or_song_name>[\w|\s]+) með (?P<artist>[\w|\s]+)$",
    # r"^spilaðu plötuna ([\w|\s]+)$ með ([\w|\s]+)$ á spotify$",
]


def handle_plain_text(q: Query) -> bool:
    """Handle a plain text query requesting Spotify to play a specific song by a specific artist."""

    if not q.client_id:
        return False

    ql = q.query.strip().rstrip("?")

    for rx in _SPOTIFY_REGEXES:
        m = re.search(rx, ql, flags=re.IGNORECASE)
        if m:
            gd = m.groupdict()
            song_name = gd.get("song")
            artist_name = gd.get("artist")
            album_name = gd.get("album")
            album_or_song_name = gd.get("album_or_song_name")
            # with GreynirBin.get_db() as db:
            #     db.lookup("song_name", auto_uppercase=True)
            print("SONG NAME: ", song_name)
            print("ARTIST NAME: ", artist_name)
            print("ALBUM NAME: ", album_name)
            print("ALBUM OR SONG NAME: ", album_or_song_name)
            cd = q.client_data("spotify")
            if cd is None:
                answer = "Það vantar að tengja Spotify aðgang."
                q.set_answer(*gen_answer(answer))
                print("NO DEVICE DATA")
                return True
            else:
                print("DEVICE DATA GOTTEN: ", cd)
            device_data = cast(SpotifyDeviceData, cd)
            spotify_client = SpotifyClient(
                device_data,
                q.client_id,
                song_name=song_name,
                artist_name=artist_name,
                album_name=album_name,
            )
            # FIXME: This song_url hotfix is stupid
            if album_name != None:
                spotify_client.get_album_by_artist()
                song_url = spotify_client.get_first_track_on_album()
                response = spotify_client.play_song_on_device()
                print("RESPONSE :", response)
            else:
                song_url = spotify_client.get_song_by_artist()
                response = spotify_client.play_song_on_device()

            answer = "Ég set það í gang."
            if response is None:
                q.set_url(song_url)
            q.set_answer({"answer": answer}, answer, "")
            return True
    return False
