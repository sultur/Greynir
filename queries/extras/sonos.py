"""

    Greynir: Natural language processing for Icelandic

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


    Class which encapsulates communication with the Sonos API.

"""
from typing import Dict, Optional, Union, List, Any, cast, Mapping

import logging
import json
from typing_extensions import TypedDict, Required
import flask
import requests
from datetime import datetime, timedelta

from utility import read_api_key
from queries import query_json_api
from query import Query, ClientDataDict


def post_to_json_api(
    url: str,
    *,
    form_data: Optional[Any] = None,
    json_data: Optional[Any] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Union[None, List[Any], Dict[str, Any]]:
    """Send a POST request to the URL, expecting a JSON response which is
    parsed and returned as a Python data structure."""

    # Send request
    try:
        r = requests.post(url, data=form_data, json=json_data, headers=headers)
    except Exception as e:
        logging.warning(str(e))
        return None

    # Verify that status is OK
    if r.status_code not in range(200, 300):
        logging.warning("Received status {0} from API server".format(r.status_code))
        return None

    # Parse json API response
    try:
        res = json.loads(r.text)
        return res
    except Exception as e:
        logging.warning("Error parsing JSON API response: {0}".format(e))
    return None


# Translate various icelandic room names to
# preset room names available in the Sonos app
_ICE_TO_ENG_DICT: Mapping[str, str] = {
    "fjölskylduherbergi": "Family Room",
    "fjölskyldu herbergi": "Family Room",
    "stofa": "Living Room",
    "eldhús": "Kitchen",
    "bað": "Bathroom",
    "klósett": "Bathroom",
    "svefnherbergi": "Bedroom",
    "svefn herbergi": "Bedroom",
    "herbergi": "Bedroom",
    "skrifstofa": "Office",
    "bílskúr": "Garage",
    "skúr": "Garage",
    "garður": "Garden",
    "gangur": "Hallway",
    "borðstofa": "Dining Room",
    "gestasvefnherbergi": "Guest Room",
    "gesta svefnherbergi": "Guest Room",
    "gestaherbergi": "Guest Room",
    "gesta herbergi": "Guest Room",
    "leikherbergi": "Playroom",
    "leik herbergi": "Playroom",
    "sundlaug": "Pool",
    "laug": "Pool",
    "sjónvarpsherbergi": "TV Room",
    "sjóvarps herbergi": "TV Room",
    "ferðahátalari": "Portable",
    "ferða hátalari": "Portable",
    "verönd": "Patio",
    "pallur": "Patio",
    "altan": "Patio",
    "sjónvarpsherbergi": "Media Room",
    "sjónvarps herbergi": "Media Room",
    "hjónaherbergi": "Main Bedroom",
    "hjóna herbergi": "Main Bedroom",
    "anddyri": "Foyer",
    "forstofa": "Foyer",
    "inngangur": "Foyer",
    "húsbóndaherbergi": "Den",
    "húsbónda herbergi": "Den",
    "hosiló": "Den",
    "bókasafn": "Library",
    "bókaherbergi": "Library",
    "bóka herbergi": "Library",
}

class _HouseholdError(Exception):
    

#FIXME: Ugly when I've included this
class _Data(TypedDict):
    last_radio_url: str


class _Creds(TypedDict):
    code: str
    timestamp: str
    access_token: str
    refresh_token: str


class _SonosSpeakerData(TypedDict):
    credentials: _Creds
    data: _Data


class SonosDeviceData(TypedDict):
    sonos: _SonosSpeakerData


class _SonosAuthResponse(TypedDict):
    access_token: str
    token_type: str
    refresh_token: str
    expires_in: int
    scope: str


class _SonosHouseholdDict(TypedDict, total=False):
    id: Required[str]
    name: Optional[str]


class _SonosHouseholdResponse(TypedDict):
    households: List[_SonosHouseholdDict]


class _SonosGroupDict(TypedDict):
    coordinatorId: str
    id: str
    name: str
    playbackState: str
    playerIds: List[str]


class _SonosPlayerDict(TypedDict, total=False):
    apiVersion: str
    devideIds: List[str]
    icon: str
    id: Required[str]
    minApiVersion: str
    name: Required[str]
    softwareVersion: str
    webSocketUrl: str
    capabilities: List[str]


class _SonosGroupResponse(TypedDict):
    groups: List[_SonosGroupDict]
    players: List[_SonosPlayerDict]


class _SonosSessionResponse(TypedDict, total=False):
    sessionState: str
    sessionId: Required[str]
    sessionCreated: bool
    customData: Optional[str]


_OAUTH_ACCESS_ENDPOINT = "https://api.sonos.com/login/v3/oauth/access"
_API_ENDPOINT = "https://api.ws.sonos.com/control/api/v1"
_HOUSEHOLDS_ENDPOINT = f"{_API_ENDPOINT}/households"
_GROUP_ENDPOINT = f"{_API_ENDPOINT}/groups"
_PLAYER_ENDPOINT = f"{_API_ENDPOINT}/players"
_PLAYBACKSESSIONS_ENDPOINT = f"{_API_ENDPOINT}/playbackSessions"
_VOLUME_INCREMENT = 20

# TODO - Decide what should happen if user does not designate a speaker but owns multiple speakers
# TODO - Testing and proper error handling
# TODO - Implement a cleaner create_or_join_session function that doesn't rely on recursion
# TODO - Failsafe for responses from playback, volume endpoints.
# TODO - Resolve players issue, whether that information needs to be accessed
# TODO - Add some error when households exceed one
class SonosClient:
    _encoded_credentials: str = read_api_key("SonosEncodedCredentials")

    def __init__(
        self,
        device_data: SonosDeviceData,
        client_id: str,
        group_name: Optional[str] = None,
        radio_name: Optional[str] = None,
    ):
        self._client_id: str = client_id
        self._device_data = device_data
        self._group_name: Optional[str] = group_name
        self._radio_name: Optional[str] = radio_name
        self._code: str = self._device_data["sonos"]["credentials"]["code"]
        self._last_radio_url: str = self._device_data["sonos"]["data"]["last_radio_url"]
        self._timestamp: str
        self._access_token: str
        self._refresh_token: str
        self._households: List[_SonosHouseholdDict]
        self._groups: Dict[str, str]
        self._household_id: str
        self._players: Dict[str, str]
        self._group_id: str
        try:
            self._access_token = self._device_data["sonos"]["credentials"][
                "access_token"
            ]
            self._refresh_token = self._device_data["sonos"]["credentials"][
                "refresh_token"
            ]
            self._timestamp = self._device_data["sonos"]["credentials"]["timestamp"]
            self._check_token_expiration()
        except (KeyError, TypeError):
            self._create_token()
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }
        self._set_households()
        self._set_groups_and_players()
        self._store_data_and_credentials()
        print(self._get_player_id())

    # TODO: expires_in seconds
    def _check_token_expiration(self) -> None:
        """
        Checks if access token is expired,
        and calls a function to refresh it if necessary.
        """
        self._update_sonos_token()
        timestamp = datetime.strptime(self._timestamp, "%Y-%m-%d %H:%M:%S.%f")
        if (datetime.now() - timestamp) > timedelta(hours=24):
            self._update_sonos_token()

    def _update_sonos_token(self) -> None:
        """
        Updates the access token.
        """
        self._refresh_expired_token()

        sonos_dict: SonosDeviceData = {
            "sonos": {
                "credentials": {
                    "code": self._code,
                    "timestamp": self._timestamp,
                    "access_token": self._access_token,
                    "refresh_token": self._refresh_token,
                },
                "data": {"last_radio_url": self._last_radio_url},
            }
        }

        self._store_data(sonos_dict)

    # FIXME: No need to return anything
    def _refresh_expired_token(self) -> Union[None, List[Any], Dict[str, Any]]:
        """
        Helper function for updating the access token.
        """
        r = requests.post(
            _OAUTH_ACCESS_ENDPOINT,
            params={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            },
            headers={"Authorization": f"Basic {self._encoded_credentials}"},
        )
        response: _SonosAuthResponse = r.json()

        self._access_token = response["access_token"]
        self._timestamp = str(datetime.now())

    # FIXME: No need to return anything
    def _create_token(self) -> Union[None, List[Any], Dict[str, Any]]:
        """
        Creates a token given a code
        """
        host = str(flask.request.host)
        r = requests.post(
            _OAUTH_ACCESS_ENDPOINT,
            params={
                "grant_type": "authorization_code",
                "code": self._code,
                "redirect_uri": f"http://{host}/connect_sonos.api",
            },
            headers={"Authorization": f"Basic {self._encoded_credentials}"},
        )
        response: _SonosAuthResponse = r.json()
        self._access_token = response.get("access_token")
        self._refresh_token = response.get("refresh_token")
        self._timestamp = str(datetime.now())

    def _set_households(self) -> None:
        """
        Sets the households, and household ID for the user
        """
        response = cast(
            _SonosHouseholdResponse,
            requests.get(_HOUSEHOLDS_ENDPOINT, headers=self._headers).json(),
        )
        self._households = response["households"]
        self._household_id = self._households[0]["id"]

    def _set_groups_and_players(self) -> None:
        """
        Sets the groups and players and the group ID
        """
        url = f"{_HOUSEHOLDS_ENDPOINT}/{self._household_id}/groups"

        response = cast(_SonosGroupResponse, query_json_api(url, headers=self._headers))

        cleaned_groups_dict = self._create_groupdict_for_db(response["groups"])
        cleaned_players_dict = self._create_playerdict_for_db(response["players"])

        self._groups = cleaned_groups_dict
        self._players = cleaned_players_dict

        # TODO: Add a check for if the group name is not in the dict
        # and make sure it's not empty
        if self._group_name is not None:
            try:
                group_id = self._groups[self._group_name.casefold()]
            except:
                group_id = self._groups.get(self._translate_group_name().casefold())
            if group_id:
                self._group_id = group_id
        else:
            self._group_id = next(iter(self._groups.values()))

    def _get_player_id(self) -> str:
        """
        Gets the player ID for the group
        """
        # FIXME: This is still stupid
        player_id = list(self._players.values())[0]
        return player_id

    def _translate_group_name(self) -> str:
        """
        Translates the group name to the correct group name
        """
        assert self._group_name is not None
        return _ICE_TO_ENG_DICT.get(self._group_name, self._group_name)

    def _create_cred_dict(self) -> _Creds:
        cred_dict: _Creds = {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "code": self._code,
            "timestamp": self._timestamp,
        }
        return cred_dict

    def _store_data_and_credentials(self) -> None:
        cred_dict = self._create_cred_dict()
        sonos_dict: SonosDeviceData = {
            "sonos": {
                "credentials": cred_dict,
                "data": {"last_radio_url": self._last_radio_url},
            }
        }
        self._store_data(sonos_dict)

    def _store_data(self, data: SonosDeviceData) -> None:
        new_dict: ClientDataDict = {"iot_speakers": cast(Dict[str, str], data)}
        Query.store_query_data(self._client_id, "iot", new_dict, update_in_place=True)

    def _create_groupdict_for_db(self, groups: List[_SonosGroupDict]) -> Dict[str, str]:
        groups_dict: Dict[str, str] = {}
        for i in range(len(groups)):
            groups_dict[groups[i]["name"].casefold()] = groups[i]["id"]
        return groups_dict

    def _create_playerdict_for_db(
        self, players: List[_SonosPlayerDict]
    ) -> Dict[str, str]:
        players_dict: Dict[str, str] = {}
        for i in range(len(players)):
            players_dict[players[i]["name"].casefold()] = players[i]["id"]
        return players_dict

    # TODO: Come back to this. Add handling for when another app controls a session.
    def _create_or_join_session(self, recursion: bool = False) -> str:
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/playbackSession/joinOrCreate"

        payload = json.dumps(
            {"appId": "com.mideind.embla", "appContext": "embla123"}
        )  # FIXME: Use something else than embla123

        response = cast(
            _SonosSessionResponse,
            post_to_json_api(url, form_data=payload, headers=self._headers),
        )
        # FIXME: This shouldn't be included in the final version
        # I think it isn't called, ever. I think joinOrCreateSession
        # is built with this in mind.
        if response is None:

            self.toggle_pause()
            if not recursion:
                session_id = self._create_or_join_session(recursion=True)
            # FIXME: This is stupid. It shouldn't return None without
            # throwing an error of some kind. The user would be lost if
            # they would endlessly try to play something and it would never work
            else:
                raise ValueError("Could not create or join session")

        else:
            session_id = response["sessionId"]
        return session_id

    def play_radio_stream(self, radio_url: Optional[str]) -> Optional[str]:
        session_id = self._create_or_join_session()
        if radio_url is None:
            try:
                print("trying")
                radio_url = self._device_data["sonos"]["data"]["last_radio_url"]
                print(self._device_data)
            except KeyError:
                print("failing")
                radio_url = "http://netradio.ruv.is/rondo.mp3"

        url = f"{_PLAYBACKSESSIONS_ENDPOINT}/{session_id}/playbackSession/loadStreamUrl"

        payload = json.dumps(
            {
                "streamUrl": radio_url,
                "playOnCompletion": True,
                # "stationMetadata": {"name": f"{radio_name}"},
                "itemId": "StreamItemId",
            }
        )

        response = post_to_json_api(url, form_data=payload, headers=self._headers)
        # FIXME: This error should be raised elsewhere.
        if response is None:
            return "Group not found"
        data_dict: SonosDeviceData = {"sonos": {"credentials": self._device_data["sonos"]["credentials"], "data": {"last_radio_url": radio_url}}}
        self._store_data(data_dict)

    def increase_volume(self) -> None:
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/groupVolume/relative"

        payload = json.dumps({"volumeDelta": _VOLUME_INCREMENT})
        post_to_json_api(url, form_data=payload, headers=self._headers)

    def decrease_volume(self) -> None:
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/groupVolume/relative"

        payload = json.dumps({"volumeDelta": -_VOLUME_INCREMENT})
        post_to_json_api(url, form_data=payload, headers=self._headers)

    # FIXME: No need to return anything.
    def toggle_play(self) -> Union[None, List[Any], Dict[str, Any]]:
        """
        Toggles play/pause of a group
        """
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/playback/play"

        post_to_json_api(url, headers=self._headers)

    # FIXME: No need to return anything.
    def toggle_pause(self) -> Union[None, List[Any], Dict[str, Any]]:
        """
        Toggles play/pause of a group
        """
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/playback/pause"

        post_to_json_api(url, headers=self._headers)

    # FIXME: No need to return anything.
    def play_audio_clip(
        self, audioclip_url: str
    ) -> Union[None, List[Any], Dict[str, Any]]:
        """
        Plays an audioclip from link to .mp3 file
        """
        player_id = self._get_player_id()
        url = f"{_PLAYER_ENDPOINT}/{player_id}/audioClip"

        payload = json.dumps(
            {
                "name": "Embla",
                "appId": "com.acme.app",
                "streamUrl": f"{audioclip_url}",
                "volume": 30,
                "priority": "HIGH",
                "clipType": "CUSTOM",
            }
        )

        post_to_json_api(url, form_data=payload, headers=self._headers)

    # FIXME: No need to return anything.
    def play_chime(self) -> Union[None, List[Any], Dict[str, Any]]:
        player_id = self._get_player_id()
        url = f"{_PLAYER_ENDPOINT}/{player_id}/audioClip"

        payload = json.dumps(
            {
                "name": "Embla",
                "appId": "com.acme.app",
                "volume": 30,
                "priority": "HIGH",
                "clipType": "CHIME",
            }
        )

        post_to_json_api(url, form_data=payload, headers=self._headers)

    # FIXME: No need to return anything.
    def next_song(self) -> Union[None, List[Any], Dict[str, Any]]:
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/playback/skipToNextTrack"

        response = post_to_json_api(url, headers=self._headers)
        return response

    # FIXME: No need to return anything.
    def prev_song(self) -> Union[None, List[Any], Dict[str, Any]]:
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/playback/skipToPreviousTrack"

        response = post_to_json_api(url, headers=self._headers)
        return response
