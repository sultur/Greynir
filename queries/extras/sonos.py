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
from typing import Dict, Optional, List, Any, cast, Mapping

import logging
from typing_extensions import TypedDict, Required
import requests
from datetime import datetime, timedelta

from utility import read_api_key
from queries import query_json_api
from query import Query, ClientDataDict

# TODO: Changed the exceptions and bailed on the try-except block
def post_to_json_api(
    url: str,
    *,
    json_data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Send a POST request to the URL, expecting a JSON response which is
    parsed and returned as a Python data structure."""

    # Send request
    try:
        r = requests.post(url, json=json_data, headers=headers)
    except Exception as e:
        logging.warning(str(e))
        raise e

    try:
        res = cast(Dict[str, Any], r.json())
        return res
    except Exception as e:
        logging.warning(f"Error parsing JSON API response: {e}")
        raise e


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


class SonosError(Exception):
    """Raised when there is an error communicating with the Sonos API."""

    ...


class _SonosData(TypedDict, total=False):
    last_group_id: str
    last_radio_url: Required[str]


class _SonosCredentials(TypedDict):
    access_token: str
    refresh_token: str
    timestamp: str
    expires_in: int


class SonosDeviceData(TypedDict):
    credentials: _SonosCredentials
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

# TODO - Failsafe for responses from playback, volume endpoints. i.e. return apprpriate error message to user.
# TODO - Add some error when households exceed one
# TODO - Data as another whatever. (I don't know what I meant here)
# TODO - Fix the r, resp, response inconsistency
class SonosClient:
    _encoded_credentials: str = read_api_key("SonosEncodedCredentials")

    @classmethod
    def create_token(cls, client_id: str, code: str, host: str) -> None:
        """
        Creates a token given a code
        """

        url_params = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": f"http://{host}/connect_sonos.api",
        }
        resp = requests.post(
            _OAUTH_ACCESS_ENDPOINT,
            params=url_params,
            headers={"Authorization": f"Basic {cls._encoded_credentials}"},
        )
        status_code = resp.status_code
        r = resp.json()

        if status_code != 200:
            raise SonosError(f'Error {status_code} while creating token: {r["error"]}')

        r = cast(_SonosAuthResponse, r)
        data: SonosDeviceData = {
            "credentials": {
                "timestamp": str(datetime.now()),
                "expires_in": r["expires_in"],
                "access_token": r["access_token"],
                "refresh_token": r["refresh_token"],
            },
            "data": {"last_radio_url": "http://netradio.ruv.is:80/ras1.mp3"},
        }
        Query.store_query_data(client_id, "sonos", cast(ClientDataDict, data))

    def __init__(
        self,
        device_data: SonosDeviceData,
        client_id: str,
        group_name: Optional[str] = None,
        radio_name: Optional[str] = None,
    ):
        self._client_id: str = client_id
        self._device_data: SonosDeviceData = device_data
        self._group_name: Optional[str] = group_name
        self._last_group_id: str
        self._radio_name: Optional[str] = radio_name
        self._last_radio_url: str = device_data["data"]["last_radio_url"]
        c = self._device_data["credentials"]
        self._access_token: str = c["access_token"]
        self._refresh_token: str = c["refresh_token"]
        self._timestamp: str = c["timestamp"]
        self._expires_in: int = c["expires_in"]
        self._households: List[_SonosHouseholdDict]
        self._groups: Dict[str, str]
        self._household_id: str
        self._group_id: str
        self._player_id: str

        self._check_token_expiration()

        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }
        self._set_households()
        self._group_api_call()
        self._store_data_and_credentials()

    def _check_token_expiration(self) -> None:
        """
        Checks if access token is expired,
        and calls a function to refresh it if necessary.
        """
        timestamp = datetime.strptime(self._timestamp, "%Y-%m-%d %H:%M:%S.%f")
        if (datetime.now() - timestamp) > timedelta(seconds=self._expires_in):
            self._refresh_expired_token()

    # TODO - Add error throwing/handling for when the refresh token doesn't work
    def _refresh_expired_token(self) -> None:
        """
        Helper function for updating the access token.
        """
        url_params = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }

        resp = requests.post(
            _OAUTH_ACCESS_ENDPOINT,
            params=url_params,
            headers={"Authorization": f"Basic {self._encoded_credentials}"},
        )
        status_code = resp.status_code
        r = resp.json()

        if status_code != 200:
            raise SonosError(f'Error {status_code} while creating token: {r["error"]}')

        r = cast(_SonosAuthResponse, r)
        self._access_token = r["access_token"]
        self._timestamp = str(datetime.now())

    def _set_households(self) -> None:
        """
        Sets the households, and household ID for the user
        """
        response = cast(
            Optional[_SonosHouseholdResponse],
            query_json_api(_HOUSEHOLDS_ENDPOINT, headers=self._headers),
        )
        self._households = response["households"]
        # Need at least one household.
        # FIXME: Add support for multiple households.
        if len(self._households) == 0:
            raise SonosError(
                "No households found.",
                "Ekki fannst Sonos-kerfi tengt Sonos-aðganginum þínum.",
                "Ekki fannst virk Sonos-tenging.",
            )
        # elif len(self._households) > 1:
        #     raise SonosError("More than one household found.")
        else:
            self._household_id = self._households[0]["id"]

    def _group_api_call(self) -> None:
        """
        A wrapper which calls the group API endpoint and fills in data from there
        """
        url = f"{_HOUSEHOLDS_ENDPOINT}/{self._household_id}/groups"

        response = cast(Optional[_SonosGroupResponse], query_json_api(url, headers=self._headers))

        self._set_groups(response)
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
                raise SonosError(
                    f"Could not find group with name {self._group_name}",
                    f"Fann ekkert Sonos- með nafnið {self._group_name}",
                    "Fann ekki hóp með þessu nafni.",
                )
            self._group_id = group_id
        else:
            # If the user doesn't specify a group name, use the last used group.
            # If there is no such group, use the first group in the list.
            try:
                self._group_id = self._last_group_id
            except AttributeError:
                self._group_id = next(iter(self._groups.values()))
        self._last_group_id = self._group_id

    def _set_player_id(self, response: _SonosGroupResponse) -> None:
        """
        Sets the player ID, by finding the coordinator ID for the selected group
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

    def _create_cred_dict(self) -> _SonosCredentials:
        cred_dict: _SonosCredentials = {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "timestamp": self._timestamp,
            "expires_in": self._expires_in,
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
        Query.store_query_data(self._client_id, "sonos", cast(ClientDataDict, data))

    def _create_groupdict_for_db(self, groups: List[_SonosGroupDict]) -> Dict[str, str]:
        """
        Only store the group name and ID from the Group API response.
        """
        groups_dict: Dict[str, str] = {}
        for i in range(len(groups)):
            groups_dict[groups[i]["name"].casefold()] = groups[i]["id"]
        return groups_dict

    def _create_or_join_session(self) -> str:
        """
        Get the session ID for the current session if Embla controls it, otherwise
        pause the current session and attempt to create a new one.
        """
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/playbackSession/joinOrCreate"

        payload = {"appId": "com.mideind.embla", "appContext": "embla123"}
        # FIXME: Use something other than embla123

        try:
            r = requests.post(url, json=payload, headers=self._headers)
            if r.status_code == 499:
                raise SonosError("Another session in progress.")
            response = cast(
                _SonosSessionResponse,
                r.json(),
            )
            return response["sessionId"]
        except SonosError:
            self.toggle_pause()
            try:
                r = requests.post(url, json=payload, headers=self._headers)
                if r.status_code == 499:
                    raise SonosError("Another session in progress.")
                response = cast(
                    _SonosSessionResponse,
                    r.json(),
                )
                return response["sessionId"]
            except SonosError:
                raise SonosError(
                    "Could neither create nor join session.",
                    "Ekki tókst nálgast Sonos. Ef önnur spilun er í gangi, slökktu á henni og reyndu aftur.",
                    "Ekki tókst að hefja spilun.",
                )

    def play_radio_stream(self, radio_url: Optional[str]) -> None:
        """
        Plays a radio stream on the selected group. If no radio station is
        specified, the last played radio station is played. If this is the first
        time a radio station is played, defaults to "Rás 1" (main station of the
        Icelandic Broadcasting Service).
        """
        session_id = self._create_or_join_session()
        if radio_url is None:
            radio_url = self._last_radio_url

        url = f"{_PLAYBACKSESSIONS_ENDPOINT}/{session_id}/playbackSession/loadStreamUrl"

        payload = {
            "streamUrl": radio_url,
            "playOnCompletion": True,
            # "stationMetadata": {"name": f"{radio_name}"},
            "itemId": "StreamItemId",
        }

        post_to_json_api(url, json_data=payload, headers=self._headers)

        data_dict: SonosDeviceData = {
            "credentials": self._device_data["credentials"],
            "data": {
                "last_radio_url": radio_url,
                "last_group_id": self._group_id,
            },
        }
        self._store_data(data_dict)

    def increase_volume(self) -> None:
        """
        Increases the volume of a group by a fixed increment
        """
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/groupVolume/relative"

        payload = {"volumeDelta": _VOLUME_INCREMENT}
        post_to_json_api(url, json_data=payload, headers=self._headers)

    def decrease_volume(self) -> None:
        """
        Decreases the volume of a group by a fixed increment
        """
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/groupVolume/relative"

        payload = {"volumeDelta": -_VOLUME_INCREMENT}
        post_to_json_api(url, json_data=payload, headers=self._headers)

    def toggle_play(self) -> None:
        """
        Turns on playback for a group
        """
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/playback/play"

        post_to_json_api(url, headers=self._headers)

    def toggle_pause(self) -> None:
        """
        Turns off playback for a group
        """
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/playback/pause"

        post_to_json_api(url, headers=self._headers)

    def play_audio_clip(self, audioclip_url: str) -> None:
        """
        Plays an audioclip from link to .mp3 file
        """
        url = f"{_PLAYER_ENDPOINT}/{self._player_id}/audioClip"

        payload = {
            "name": "Embla",
            "appId": "com.acme.app",
            "streamUrl": f"{audioclip_url}",
            "volume": 30,
            "priority": "HIGH",
            "clipType": "CUSTOM",
        }

        post_to_json_api(url, json_data=payload, headers=self._headers)

    def play_chime(self) -> None:
        """
        Plays a chime provided by Sonos
        """
        url = f"{_PLAYER_ENDPOINT}/{self._player_id}/audioClip"

        payload = {
            "name": "Embla",
            "appId": "com.acme.app",
            "volume": 30,
            "priority": "HIGH",
            "clipType": "CHIME",
        }

        post_to_json_api(url, json_data=payload, headers=self._headers)

    def next_song(self) -> None:
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/playback/skipToNextTrack"

        post_to_json_api(url, headers=self._headers)

    def prev_song(self) -> None:
        url = f"{_GROUP_ENDPOINT}/{self._group_id}/playback/skipToPreviousTrack"

        post_to_json_api(url, headers=self._headers)
