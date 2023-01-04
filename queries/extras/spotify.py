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


    Class which encapsulates communication with the Spotify API.

"""
from typing import Dict, Optional, Union, List, Any, cast

import logging
from typing_extensions import TypedDict
import json
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


def put_to_json_api(
    url: str, json_data: Optional[Any] = None, headers: Optional[Dict[str, str]] = None
) -> Union[None, List[Any], Dict[str, Any]]:
    """Send a PUT request to the URL, expecting a JSON response which is
    parsed and returned as a Python data structure."""

    # Send request
    try:
        r = requests.put(url, data=json_data, headers=headers)
    except Exception as e:
        logging.warning(str(e))
        return None

    # Verify that status is OK
    if r.status_code not in range(200, 300):
        logging.warning("Received status {0} from API server".format(r.status_code))
        return None

    # Parse json API response
    try:
        if r.text:
            res = json.loads(r.text)
            return res
        return {}
    except Exception as e:
        logging.warning("Error parsing JSON API response: {0}".format(e))
    return None


class SpotifyError(Exception):
    "Raised when there is an error communicating with the Spotify API."

    pass


class _SpotifyData(TypedDict):
    tbd: str


class _SpotifyCredentials(TypedDict):
    access_token: str
    refresh_token: str
    timestamp: str
    expires_in: int


class SpotifyDeviceData(TypedDict):
    credentials: _SpotifyCredentials
    data: _SpotifyData


class _SpotifyAuthResponse(TypedDict):
    access_token: str
    token_type: str
    refresh_token: str
    expires_in: int
    scope: str


_OAUTH_ACCESS_ENDPOINT = "https://accounts.spotify.com/api/token"
_API_ENDPOINT = "https://api.spotify.com/v1"

# TODO Find a better way to play albums
# TODO - Remove debug print statements
# TODO - Testing and proper error handling
class SpotifyClient:
    _encoded_credentials = read_api_key("SpotifyEncodedCredentials")

    # FIXME: Not modular doing this both here and in the sonos class
    @classmethod
    def create_token(cls, client_id: str, code: str, host: str) -> None:
        """
        Create a new access token given a code.
        """
        print("i'm here")

        url_params = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": f"http://{host}/connect_spotify.api",
        }
        resp = requests.post(
            _OAUTH_ACCESS_ENDPOINT,
            params=url_params,
            headers={
                "Authorization": f"Basic {cls._encoded_credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        status_code = resp.status_code
        print("entire", resp)
        print("text ", resp.text)
        print("json ", resp.json())
        r = resp.json()

        if status_code != 200:
            raise SpotifyError(
                f'Error {status_code} while creating token: {r["error"]}'
            )

        r = cast(_SpotifyAuthResponse, r)
        data: SpotifyDeviceData = {
            "credentials": {
                "timestamp": str(datetime.now()),
                "expires_in": r["expires_in"],
                "access_token": r["access_token"],
                "refresh_token": r["refresh_token"],
            },
            "data": {"tbd": "tbd"},
        }
        Query.store_query_data(client_id, "spotify", cast(ClientDataDict, data))

    def __init__(
        self,
        device_data: SpotifyDeviceData,
        client_id: str,
        # FIXME: They cannot all be None
        song_name: Optional[str] = None,
        artist_name: Optional[str] = None,
        album_name: Optional[str] = None,
    ):
        self._client_id: str = client_id
        self._device_data: SpotifyDeviceData = device_data
        self._song_name = song_name
        self._artist_name = artist_name
        self._song_name = song_name
        self._album_name = album_name
        self._song_uri: str
        self._song_url: str
        self._album_url: str
        c = self._device_data["credentials"]
        self._access_token: str = c["access_token"]
        self._refresh_token: str = c["refresh_token"]
        self._timestamp: str = c["timestamp"]
        self._expires_in: int = c["expires_in"]

        self._check_token_expiration()

        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }

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
            raise SpotifyError(
                f'Error {status_code} while creating token: {r["error"]}'
            )

        r = cast(_SpotifyAuthResponse, r)
        self._access_token = r["access_token"]
        self._timestamp = str(datetime.now())

    # def _refresh_expired_token(self) -> None:
    #     """
    #     Helper function for updating the access token.
    #     """

    #     url = f"https://accounts.spotify.com/api/token?grant_type=refresh_token&refresh_token={self._refresh_token}"

    #     payload = {}
    #     headers = {
    #         "Content-Type": "application/x-www-form-urlencoded",
    #         "Authorization": f"Basic {self._encoded_credentials}",
    #     }

    #     response = post_to_json_api(url, form_data=payload, headers=headers)
    #     self._access_token = response.get("access_token")
    #     self._timestamp = str(datetime.now())

    def _create_cred_dict(self) -> _SpotifyCredentials:
        cred_dict: _SpotifyCredentials = {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "timestamp": self._timestamp,
            "expires_in": self._expires_in,
        }
        return cred_dict

    # FIXME: What data could we store, do we need this?
    def _create_data_dict(self) -> _SpotifyData:
        data_dict: _SpotifyData = {
            "tbd": "tbd",
        }
        return data_dict

    def _store_data_and_credentials(self) -> None:
        cred_dict = self._create_cred_dict()
        data_dict = self._create_data_dict()
        sonos_dict: SpotifyDeviceData = {
            "credentials": cred_dict,
            "data": data_dict,
        }
        self._store_data(sonos_dict)

    def _store_data(self, data: SpotifyDeviceData) -> None:
        Query.store_query_data(self._client_id, "spotify", cast(ClientDataDict, data))

    def get_song_by_artist(self) -> Optional[str]:
        song_name = self._song_name.replace(" ", "%20")  # FIXME: URL encode this
        artist_name = self._artist_name.replace(" ", "%20")
        url = f"{_API_ENDPOINT}/search?type=track&q={song_name}+{artist_name}"

        payload = ""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }
        response = query_json_api(url, headers)
        try:
            self._song_url = response["tracks"]["items"][0]["external_urls"]["spotify"]
            self._song_uri = response["tracks"]["items"][0]["uri"]
        except IndexError:
            return

        return self._song_url

    def get_album_by_artist(self) -> Optional[str]:
        album_name = self._album_name.replace(" ", "%20")
        artist_name = self._artist_name.replace(" ", "%20")
        url = f"{_API_ENDPOINT}/search?type=album&q={album_name}+{artist_name}"

        payload = ""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }
        response = query_json_api(url, headers)
        try:
            self._album_id = response["albums"]["items"][0]["id"]
            self._album_url = response["albums"]["items"][0]["external_urls"]["spotify"]
            self._album_uri = response["albums"]["items"][0]["uri"]
        except IndexError:
            return

        return self._album_url

    def get_first_track_on_album(self) -> Optional[str]:
        album_name = self._album_name.replace(" ", "%20")
        artist_name = self._artist_name.replace(" ", "%20")
        url = f"{_API_ENDPOINT}/albums/{self._album_id}/tracks"

        payload = ""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }
        response = query_json_api(url, headers)
        try:
            self._song_uri = response["items"][0]["uri"]
            self._first_album_track_url = response["items"][0]["external_urls"][
                "spotify"
            ]
        except IndexError:
            return

        return self._first_album_track_url

    def play_song_on_device(self) -> Union[None, List[Any], Dict[str, Any]]:
        url = f"{_API_ENDPOINT}/me/player/play"

        payload = json.dumps(
            {
                "context_uri": self._song_uri,
            }
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }

        response = put_to_json_api(url, payload, headers)

        return response

    def play_album_on_device(self) -> Union[None, List[Any], Dict[str, Any]]:
        url = f"{_API_ENDPOINT}/me/player/play"

        payload = json.dumps(
            {
                "context_uri": self._album_uri,
            }
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }

        response = put_to_json_api(url, payload, headers)

        return response
