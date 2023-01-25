"""

    Greynir: Natural language processing for Icelandic

    Smartspeaker query response module

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

    This query module handles queries related to the control of smartspeakers.

"""

# TODO: make the objects of sentences more modular, so that the same structure doesn't need to be written for each action
# TODO: ditto the previous comment. make the initial non-terminals general and go into specifics at the terminal level instead.
# TODO: substituion klósett, baðherbergi hugmyndÆ senda lista i javascript og profa i röð
# TODO: Embla stores old javascript code cached which has caused errors
# TODO: Cut down javascript sent to Embla
# TODO: Two specified groups or lights.
# TODO: No specified location
# TODO: Fix scene issues

from typing import Any, Dict, Sequence, cast, Optional

import logging
import random

from query import Query, QueryStateDict
from queries import read_grammar_file
from queries.extras.sonos import SonosClient, SonosDeviceData, SonosError
from tree import NonterminalNode, ParamList, Result, Node

# Dictionary of radio stations and their stream urls
_RADIO_STREAMS: Dict[str, str] = {
    "Rás 1": "http://netradio.ruv.is/ras1.mp3",
    "Rás 2": "http://netradio.ruv.is/ras2.mp3",
    "Rondó": "http://netradio.ruv.is/rondo.mp3",
    "Bylgjan": "https://live.visir.is/hls-radio/bylgjan/playlist.m3u8",
    "Léttbylgjan": "https://live.visir.is/hls-radio/lettbylgjan/playlist.m3u8",
    "Gullbylgjan": "https://live.visir.is/hls-radio/gullbylgjan/playlist.m3u8",
    "80s Bylgjan": "https://live.visir.is/hls-radio/80s/chunklist_DVR.m3u8",
    "Íslenska Bylgjan": "https://live.visir.is/hls-radio/islenska/chunklist_DVR.m3u8",
    "FM957": "https://live.visir.is/hls-radio/fm957/playlist.m3u8",
    "Útvarp Saga": "https://stream.utvarpsaga.is/Hljodver",
    "K100": "https://k100streymi.mbl.is/beint/k100/tracks-v1a1/rewind-3600.m3u8",
    "X977": "https://live.visir.is/hls-radio/x977/playlist.m3u8",
    "Retro": "https://k100straumar.mbl.is/retromobile",
    "KissFM": "http://stream3.radio.is:443/kissfm",
    "Útvarp 101": "https://stream.101.live/audio/101/chunklist.m3u8",
    "Apparatið": "https://live.visir.is/hls-radio/apparatid/chunklist_DVR.m3u8",
    "FM Extra": "https://live.visir.is/hls-radio/fmextra/chunklist_DVR.m3u8",
    "Útvarp Suðurland": "http://ice-11.spilarinn.is/tsudurlandfm",
    "Flashback": "http://stream.radio.is:443/flashback",
    "70s Flashback": "http://stream3.radio.is:443/70flashback",
    "80s Flashback": "http://stream3.radio.is:443/80flashback",
    "90s Flashback": "http://stream3.radio.is:443/90flashback",
}


_SPEAKER_QTYPE = "Smartspeakers"

TOPIC_LEMMAS: Sequence[str] = [
    "tónlist",
    "spila",
    "útvarp",
    "útvarpsstöð",
    "hækka",
    "lækka",
    "stoppa",
    "stöðva",
]


def help_text(lemma: str) -> str:
    """Help text to return when query.py is unable to parse a query but
    one of the above lemmas is found in it"""
    return "Ég skil þig ef þú segir til dæmis: {0}.".format(
        random.choice(
            (
                "Hækkaðu í tónlistinni",
                "Kveiktu á tónlist",
            )
        )
    )


# This module wants to handle parse trees for queries
HANDLE_TREE = True

# The grammar nonterminals this module wants to handle
QUERY_NONTERMINALS = {"QSpeaker"}

# The context-free grammar for the queries recognized by this plug-in module
GRAMMAR = read_grammar_file("smartspeakers")


def QSpeaker(node: Node, params: ParamList, result: Result) -> None:
    result.qtype = _SPEAKER_QTYPE


def QSpeakerResume(node: Node, params: ParamList, result: Result) -> None:
    result.qkey = "turn_on"


def QSpeakerPause(node: Node, params: ParamList, result: Result) -> None:
    result.qkey = "turn_off"


# def QSpeakerSkipVerb(node: Node, params: ParamList, result: Result) -> None:
#     result.qkey = "next_song"


def QSpeakerNewPlay(node: Node, params: ParamList, result: Result) -> None:
    result.qkey = "turn_on"


def QSpeakerNewPause(node: Node, params: ParamList, result: Result) -> None:
    result.qkey = "turn_off"


# def QSpeakerNewNext(node: Node, params: ParamList, result: Result) -> None:
#     result.qkey = "next_song"


# def QSpeakerNewPrevious(node: Node, params: ParamList, result: Result) -> None:
#     result.qkey = "prev_song"


# def QSpeakerIncreaseVerb(node: Node, params: ParamList, result: Result) -> None:
#     result.qkey = "increase_volume"


# def QSpeakerDecreaseVerb(node: Node, params: ParamList, result: Result) -> None:
#     result.qkey = "decrease_volume"


def QSpeakerIncreaseVolume(node: Node, params: ParamList, result: Result) -> None:
    result.qkey = "increase_volume"


def QSpeakerDecreaseVolume(node: Node, params: ParamList, result: Result) -> None:
    result.qkey = "decrease_volume"


# def QSpeakerMoreOrHigher(node: Node, params: ParamList, result: Result) -> None:
#     result.qkey = "increase_volume"


# def QSpeakerLessOrLower(node: Node, params: ParamList, result: Result) -> None:
#     result.qkey = "decrease_volume"


def QSpeakerTónlist(node: Node, params: ParamList, result: Result) -> None:
    result.target = "music"


def QSpeakerHátalari(node: Node, params: ParamList, result: Result) -> None:
    result.target = "speaker"


def QSpeakerPlayRadio(node: Node, params: ParamList, result: Result) -> None:
    result.target = "radio"
    result.qkey = "radio"


def QSpeakerRoom(node: Node, params: ParamList, result: Result) -> None:
    result.group_name = result._indefinite


def QSpeakerRadioStation(node: Node, params: ParamList, result: Result) -> None:
    child = cast(NonterminalNode, node.child)
    station = child.nt_base.replace("QSpeaker", "").replace("_", " ")
    result.target = "radio"
    result.station = station


def sentence(state: QueryStateDict, result: Result) -> None:
    """Called when sentence processing is complete"""
    q: Query = state["query"]

    if result.get("qtype") != _SPEAKER_QTYPE or not q.client_id:
        q.set_error("E_QUERY_NOT_UNDERSTOOD")
        return

    qk: str = result.qkey
    try:
        q.set_qtype(result.qtype)
        # FIXME: Duplicates here
        cd = q.client_data("sonos")
        if cd is None:
            raise KeyError("No client data")
        speaker_data = cast(SonosDeviceData, cd)
        if speaker_data is None:
            raise KeyError("No speaker data")
        device_data = speaker_data
        if device_data is None:
            raise KeyError("No Sonos data")

        sonos_client = SonosClient(
            device_data,
            q.client_id,
            group_name=result.get("group_name"),
        )

        answer: str
        # FIXME: Need to raise the actual error from sonos.py
        try:
            if qk == "turn_on":
                sonos_client.play()
                answer = "Ég kveikti á tónlist"
            elif qk == "turn_off":
                sonos_client.pause()
                answer = "Ég slökkti á tónlistinni"
            elif qk == "increase_volume":
                sonos_client.increase_volume()
                answer = "Ég hækkaði í tónlistinni"
            elif qk == "decrease_volume":
                sonos_client.decrease_volume()
                answer = "Ég lækkaði í tónlistinni"
            elif qk == "radio":
                station = result.get("station")
                radio_url = _RADIO_STREAMS.get(station)
                sonos_client.play_radio_stream(radio_url)
                answer = "Ég kveikti á útvarpstöðinni"
            elif qk == "next_song":
                sonos_client.next_song()
                answer = "Ég skipti yfir í næsta lag"
            elif qk == "prev_song":
                sonos_client.prev_song()
                answer = "Ég skipti yfir í lagið á undan"
            else:
                logging.warning("Incorrect qkey in speaker module")
                return
        except SonosError as e:
            logging.warning("Error in speaker module: {0}".format(e))
            return

        q.query_is_command()
        q.set_key(qk)
        q.set_beautified_query(
            q.beautified_query.replace("London", "Rondó")
            .replace(" eydís ", " 80s ")
            .replace(" Eydís ", " 80s ")
            .replace(" ljóð", " hljóð")
            .replace("Stofnaðu ", "Stoppaðu ")
            .replace("stofnaðu ", "stoppaðu ")
            .replace("Stoppa í", "Stoppaðu")
            .replace("stoppa í", "stoppaðu")
            .replace("tónlistarmaður", "tónlist")
        )
        q.set_answer(
            dict(answer=answer),
            answer,
            answer.replace("Sonos", "Sónos"),
        )
        return
    except Exception as e:
        logging.warning("Exception answering smartspeaker query: {0}".format(e))
        q.set_error("E_EXCEPTION: {0}".format(e))
        return

    # TODO: Need to add check for if there are no registered devices to an account, probably when initilazing the querydata
