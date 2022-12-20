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
import flask  # type: ignore
import requests
from datetime import datetime, timedelta

from utility import read_api_key
from queries import query_json_api
from query import Query, ClientDataDict

# TODO: How does it work to throw an error here? We don't want the function
# to be able to return None. Instead, it should throw an error. This
# would allow for us do try except type things when calling this
# function. Instead of the if response is None crap
def post_to_json_api(
    url: str,
    *,
    form_data: Optional[str] = None,
    # json_data: Optional[str] = None,
    # headers: Optional[Dict[str, str]] = None,
    headers: Dict[str, str],
) -> Union[None, List[Any], Dict[str, Any]]:
    """Send a POST request to the URL, expecting a JSON response which is
    parsed and returned as a Python data structure."""

    # Send request
    try:
        r = requests.post(url, data=form_data, headers=headers)
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


class TooManyHouseholdsError(Exception):
    """Raised when the user has more than one household."""

    ...


class GroupNotFoundError(KeyError):
    """Raised when a group is not found."""

    ...


class _SonosData(TypedDict):
    last_group_id: str
    last_radio_url: str


class _SonosCreds(TypedDict):
    code: str
    timestamp: str
    access_token: str
    refresh_token: str


class SonosDeviceData(TypedDict):
    credentials: _SonosCreds
    data: _SonosData


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
# TODO - Data as another whatever
# TODO - expires_in seconds for checking if token is expired
# TODO - Api call error handling
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
        self._last_group_id: str
        self._radio_name: Optional[str] = radio_name
        self._last_radio_url: str
        self._timestamp: str
        self._access_token: str
        self._refresh_token: str
        self._households: List[_SonosHouseholdDict]
        self._groups: Dict[str, str]
        self._household_id: str
        # self._players: Dict[str, str]
        self._group_id: str
        self._player_id: str

        c = self._device_data["credentials"]
        self._code: str = c["code"]
        try:
            self._access_token = c["access_token"]
            self._refresh_token = c["refresh_token"]
            self._timestamp = c["timestamp"]
            self._check_token_expiration()
        except KeyError:
            self._create_token()

        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }
        self._set_households()
        self._group_api_call()
        self._last_radio_url = self._device_data["data"].get(
            "last_radio_url", "http://netradio.ruv.is:80/ras1.mp3"
        )
        self._store_data_and_credentials()

    def _check_token_expiration(self) -> None:
        """
        Checks if access token is expired,
        and calls a function to refresh it if necessary.
        """
        # FIXME: This hotfix is needed right now, and has been always. It shouldn't be.
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
            "credentials": {
                "code": self._code,
                "timestamp": self._timestamp,
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
            },
            "data": self._device_data["data"],
        }
        self._store_data(sonos_dict)

    def _refresh_expired_token(self) -> None:
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

    def _create_token(self) -> None:
        """
        Creates a token given a code
        """
        host = str(flask.request.host)  # type: ignore
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

    def _group_api_call(self) -> None:
        """
        A wrapper which calls the group API endpoint and fills in data from there
        """
        url = f"{_HOUSEHOLDS_ENDPOINT}/{self._household_id}/groups"

        response = cast(_SonosGroupResponse, query_json_api(url, headers=self._headers))

        self._set_groups(response)
        # self._set_players(response)
        self._set_player_id(response)

    def _set_groups(self, response: _SonosGroupResponse) -> None:
        """
        Sets the groups and finds target group ID
        """
        cleaned_groups_dict = self._create_groupdict_for_db(response["groups"])

        self._groups = cleaned_groups_dict

        if self._group_name is not None:
            # First check whether the user's response (given in Icelandic)
            # is listed in the groups, in case they customized the Sonos app (presumably rare).
            # Otherwise, translate to English and check that.
            group_id = self._groups.get(
                self._group_name.casefold(),
                self._groups.get(self._translate_group_name().casefold()),
            )
            if group_id is None:
                raise GroupNotFoundError(self._group_name)
            self._group_id = group_id
        else:
            try:
                self._group_id = self._last_group_id
            except AttributeError:
                self._group_id = next(iter(self._groups.values()))
        self._last_group_id = self._group_id

    # def _set_players(self, response: _SonosGroupResponse) -> None:
    #     """
    #     Sets the players
    #     """
    #     cleaned_players_dict = self._create_playerdict_for_db(response["players"])

    #     self._players = cleaned_players_dict

    def _set_player_id(self, response: _SonosGroupResponse) -> None:
        """
        Sets the player ID, by finding the coordinator id of the group id
        """
        groups = response["groups"]

        group_dict = next(
            filter(lambda group: group["id"] == self._group_id, groups), None
        )
        assert group_dict is not None

        self._player_id = group_dict["coordinatorId"]

    def _translate_group_name(self) -> str:
        """
        Translates the group name to the correct group name
        """
        assert self._group_name is not None
        return _ICE_TO_ENG_DICT.get(self._group_name, self._group_name)

    def _create_cred_dict(self) -> _SonosCreds:
        cred_dict: _SonosCreds = {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "code": self._code,
            "timestamp": self._timestamp,
        }
        return cred_dict

    def _create_data_dict(self) -> _SonosData:
        data_dict: _SonosData = {
            "last_radio_url": self._last_radio_url,
            "last_group_id": self._group_id,
        }
        return data_dict

    def _store_data_and_credentials(self) -> None:
        cred_dict = self._create_cred_dict()
        data_dict = self._create_data_dict()
        sonos_dict: SonosDeviceData = {
            "credentials": cred_dict,
            "data": data_dict,
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
    # Fix this by throwing an error in the post to json bullshit :)
    def _create_or_join_session(self, recursion: bool = False) -> str:
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/playbackSession/joinOrCreate"

        payload = json.dumps(
            {"appId": "com.mideind.embla", "appContext": "embla123"}
        )  # FIXME: Use something other than embla123

        response = cast(
            _SonosSessionResponse,
            post_to_json_api(url, form_data=payload, headers=self._headers),
        )
        # FIXME: This shouldn't be included in the final version
        if response is None:

            self.toggle_pause()
            if not recursion:
                session_id = self._create_or_join_session(recursion=True)
            else:
                raise ValueError("Could not create or join session")

        else:
            session_id = response["sessionId"]
        return session_id

    def play_radio_stream(self, radio_url: Optional[str]) -> None:
        session_id = self._create_or_join_session()
        if radio_url is None:
            radio_url = self._last_radio_url

        url = f"{_PLAYBACKSESSIONS_ENDPOINT}/{session_id}/playbackSession/loadStreamUrl"

        payload = json.dumps(
            {
                "streamUrl": radio_url,
                "playOnCompletion": True,
                # "stationMetadata": {"name": f"{radio_name}"},
                "itemId": "StreamItemId",
            }
        )
        post_to_json_api(url, form_data=payload, headers=self._headers)

        data_dict: SonosDeviceData = {
            "credentials": self._device_data["credentials"],
            "data": {
                "last_radio_url": radio_url,
                "last_group_id": self._group_id,
            },
        }
        self._store_data(data_dict)

    def increase_volume(self) -> None:
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/groupVolume/relative"

        payload = json.dumps({"volumeDelta": _VOLUME_INCREMENT})
        post_to_json_api(url, form_data=payload, headers=self._headers)

    def decrease_volume(self) -> None:
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/groupVolume/relative"

        payload = json.dumps({"volumeDelta": -_VOLUME_INCREMENT})
        post_to_json_api(url, form_data=payload, headers=self._headers)

    def toggle_play(self) -> None:
        """
        Toggles play/pause of a group
        """
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/playback/play"

        post_to_json_api(url, headers=self._headers)

    def toggle_pause(self) -> None:
        """
        Toggles play/pause of a group
        """
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/playback/pause"

        post_to_json_api(url, headers=self._headers)

    def play_audio_clip(self, audioclip_url: str) -> None:
        """
        Plays an audioclip from link to .mp3 file
        """
        url = f"{_PLAYER_ENDPOINT}/{self._player_id}/audioClip"

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

    def play_chime(self) -> None:
        url = f"{_PLAYER_ENDPOINT}/{self._player_id}/audioClip"

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

    def next_song(self) -> None:
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/playback/skipToNextTrack"

        post_to_json_api(url, headers=self._headers)

    def prev_song(self) -> None:
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/playback/skipToPreviousTrack"

        post_to_json_api(url, headers=self._headers)
