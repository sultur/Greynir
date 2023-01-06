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
from typing_extensions import TypedDict, Literal, NotRequired
from urllib.parse import urlencode as urlencode
import json
import requests
from requests.exceptions import HTTPError
from datetime import datetime, timedelta

from utility import read_api_key
from queries import query_json_api
from query import Query, ClientDataDict

JSON_T = Union[None, str, int, float, bool, Dict[str, "JSON_T"], List["JSON_T"]]


def GET_json(
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Send a GET request to the URL, expecting a JSON response which is
    parsed and returned as a Python data structure."""

    # Send request
    try:
        r = requests.get(url, params=params, headers=headers)
    except Exception as e:
        logging.warning(str(e))
        raise e

    r.raise_for_status()

    try:
        res = cast(Dict[str, Any], r.json())
        return res
    except Exception as e:
        logging.warning(f"Error parsing JSON API response: {e}")
        raise e


def POST_json(
    url: str,
    *,
    json_data: JSON_T = None,
    data: Any = None,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Send a POST request to the URL, expecting a JSON response which is
    parsed and returned as a Python data structure."""

    # Send request
    try:
        r = requests.post(url, json=json_data, data=data, headers=headers)
    except Exception as e:
        logging.warning(str(e))
        raise e

    r.raise_for_status()

    try:
        res = cast(Dict[str, Any], r.json())
        return res
    except Exception as e:
        logging.warning(f"Error parsing JSON API response: {e}")
        raise e


def PUT_json(
    url: str,
    *,
    json_data: JSON_T = None,
    data: Any = None,
    headers: Optional[Dict[str, str]] = None,
) -> None:
    """Send a POST request to the URL, expecting a JSON response which is
    parsed and returned as a Python data structure."""

    # Send request
    try:
        r = requests.put(url, json=json_data, data=data, headers=headers)
    except Exception as e:
        logging.warning(str(e))
        raise e

    r.raise_for_status()


class SpotifyError(Exception):
    "Raised when there is an error communicating with the Spotify API."

    pass


class APIError(Exception):
    "Raised when there is an error communicating with the API."

    pass


class _SpotifyObjectDict(TypedDict):
    name: Optional[str]
    uri: NotRequired[str]
    id: NotRequired[str]
    url: NotRequired[str]


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
        request_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": f"http://{host}/connect_spotify.api",
        }
        try:
            resp = POST_json(
                _OAUTH_ACCESS_ENDPOINT,
                data=request_data,
                headers={
                    "Authorization": f"Basic {cls._encoded_credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        except Exception as e:
            raise SpotifyError(f"Error creating token: {e}")

        r = cast(_SpotifyAuthResponse, resp)
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
        album_name: Optional[str] = None,
        track_name: Optional[str] = None,
        album_or_track_name: Optional[str] = None,
        artist_name: Optional[str] = None,
    ):
        self._client_id: str = client_id
        self._device_data: SpotifyDeviceData = device_data
        self._track: _SpotifyObjectDict = {"name": track_name}
        self._album: _SpotifyObjectDict = {"name": album_name}
        self._artist: _SpotifyObjectDict = {"name": artist_name}
        self._album_or_track_name = album_or_track_name
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

        if self._album_or_track_name is not None:
            self._get_album_or_track()
        elif self._album["name"] is not None:
            self._search_spotify(
                q=self._album["name"], artist=self._artist["name"], object_type="album"
            )
        elif self._track["name"] is not None:
            self._search_spotify(
                q=self._track["name"], artist=self._artist["name"], object_type="track"
            )
        else:
            raise SpotifyError("No track or album name provided.")

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
        request_data = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
        }

        try:
            resp = POST_json(
                _OAUTH_ACCESS_ENDPOINT,
                data=request_data,
                headers={
                    "Authorization": f"Basic {self._encoded_credentials}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        except Exception as e:
            raise SpotifyError(f"Error refreshing token: {e}")

        r = cast(_SpotifyAuthResponse, resp)

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

    #     response = post_to_json_api(url, form_data=payload, headers=self._headers)
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

    # def _get_album_or_track(self) -> None:

    def _search_spotify(
        self,
        q: str,
        object_type: Literal["album", "artist", "track"],
        # album: Optional[str] = None,
        artist: Optional[str] = None,
    ) -> None:
        """
        Search Spotify for an album, artist, or track and
        update the instance variables accordingly.
        """
        # Restricting the search results in issues with, e.g., artists associated with a song that are not the main artist. "Jumpman by Future"
        # if album is not None:
        #     q += f" album:{album}"
        # if artist is not None:
        #     q += f" artist:{artist}"
        url = f"{_API_ENDPOINT}/search"
        if artist is not None:
            q += f" {self._artist['name']}"
        params = {
            "type": object_type,
            "q": q,
            "limit": "1",
        }

        key = f"{object_type}s"

        try:
            response = GET_json(url, headers=self._headers, params=params)
        except Exception as e:
            raise SpotifyError(f"Error during search GET request to Spotify: {e}")

        try:
            result_object = response[key]["items"][0]
        except IndexError:
            raise SpotifyError(
                f"Could not find {object_type} matching search criteria on Spotify."
            )

        try:
            if object_type == "track":
                result_dict = {
                    "name": result_object["name"],
                    "uri": result_object["uri"],
                    "url": result_object["external_urls"]["spotify"],
                }
                self._track.update(result_dict)
                self._album["uri"] = result_object["album"]["uri"]
            elif object_type == "album":
                result_dict = {
                    "name": result_object["name"],
                    "uri": result_object["uri"],
                    "id": result_object["id"],
                }
                self._album.update(result_dict)
                self._get_first_track_on_album()
        except KeyError:
            raise SpotifyError(f"Spotify search result object malformed.")

    def _get_first_track_on_album(self) -> None:
        """
        Find the url of the first track on an album.
        """
        url = f"{_API_ENDPOINT}/albums/{self._album['id']}/tracks"
        params = {"limit": "1"}
        try:
            response = GET_json(url, headers=self._headers, params=params)
        except Exception as e:
            raise SpotifyError(
                f"Error in GET request for first album track to Spotify: {e}"
            )

        try:
            self._track["url"] = response["items"][0]["external_urls"]["spotify"]
        except IndexError:
            # FIXME: Can this happen?
            # FIXME: Clean if it does.
            raise SpotifyError("Error retrieving first track on album from Spotify.")

    def play(self) -> None:
        url = f"{_API_ENDPOINT}/me/player/play"
        # FIXME: Kind of embarrassing, tbhhh. Shouldn't rely on the existence of a variable.
        offset: Dict[str, str]
        if self._track["name"] is not None:
            offset = {"uri": self._track["uri"]}
        elif self._album["name"] is not None:
            offset = {"position": "0"}
        # FIXME: Shouldn't include this
        else:
            raise SpotifyError("No track or album specified to play on Spotify.")
        payload = {
            "context_uri": self._album["uri"],
            "offset": offset,
        }

        try:
            PUT_json(url, json_data=payload, headers=self._headers)
        except HTTPError as e:
            raise SpotifyError(f"Error in PUT request playing album on Spotify: {e}")

    @property
    def album_name(self) -> str:
        return self._album["name"]

    @property
    def track_name(self) -> str:
        return self._track["name"]

    @property
    def track_url(self) -> str:
        return self._track["url"]
