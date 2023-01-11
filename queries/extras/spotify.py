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
from typing import Dict, Optional, Union, List, Any, cast, Tuple


import logging
from typing_extensions import TypedDict, Literal, NotRequired
from urllib.parse import urlencode as urlencode
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


class _SpotifyResultObject(TypedDict):
    name: str
    context_uri: str
    url: str
    offset: Optional[Dict[str, Union[int, str]]]
    artist: Optional[str]


class _SpotifyTracksObject(TypedDict):
    name: str
    uri: str


class _SpotifyAlbumsObject(TypedDict):
    name: str
    uri: str


class _SpotifyArtistsObject(TypedDict):
    name: str
    uri: str


class _SpotifyPlaylistsObject(TypedDict):
    name: str
    uri: str


class _SpotifyTracksResponseDict(TypedDict):
    items: List[_SpotifyTracksObject]


class _SpotifyAlbumsResponseDict(TypedDict):
    items: List[_SpotifyAlbumsObject]


class _SpotifyArtistsResponseDict(TypedDict):
    items: List[_SpotifyArtistsObject]


class _SpotifyPlaylistsResponseDict(TypedDict):
    items: List[_SpotifyPlaylistsObject]


class _SpotifySearchResponse(TypedDict):
    tracks: _SpotifyTracksResponseDict
    albums: _SpotifyAlbumsResponseDict
    artists: _SpotifyArtistsResponseDict
    playlists: _SpotifyPlaylistsResponseDict


class _SpotifyObjectDict(TypedDict):
    name: str
    uri: str
    id: str
    url: NotRequired[str]


class _SpotifySearchObject(TypedDict):
    album: NotRequired[_SpotifyObjectDict]
    track: NotRequired[_SpotifyObjectDict]
    artist: NotRequired[_SpotifyObjectDict]
    playlist: NotRequired[_SpotifyObjectDict]


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

_object_types = ("track", "album", "track_or_album", "playlist", "artist", "anything")

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
    ):
        self._client_id: str = client_id
        self._device_data: SpotifyDeviceData = device_data
        self._name: str
        self._object_type: str
        self._url: str
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
        *,
        track: Optional[str],
        album: Optional[str],
        track_or_album: Optional[str],
        playlist: Optional[str],
        artist: Optional[str],
        anything: Optional[str],
        object_types: Tuple[Literal["album", "artist", "track", "playlist"], ...],
    ) -> _SpotifyResultObject:
        """
        Search Spotify for an album, artist, playlist or track returning the result
        and updating the instance accordingly.
        """
        args = (track, album, track_or_album, playlist, artist, anything)
        assert any(c is not None for c in args)
        if artist is not None and ({"playlist"}.intersection(object_types)):
            raise SpotifyError(f"Cannot search for a playlist by a specific artist.")
        url = f"{_API_ENDPOINT}/search"
        # join the object types with a comma separating them
        object_type_string = ",".join(object_types)
        print(f"object_type_string = {object_type_string}")
        params = {
            "type": ",".join(object_types),
            "q": " ".join(w for w in args if w is not None),
            "limit": "1",
        }

        print(f"params = {params}")
        try:
            response = cast(
                _SpotifySearchResponse,
                GET_json(url, headers=self._headers, params=params),
            )
        except Exception as e:
            raise SpotifyError(f"Error during search GET request to Spotify: {e}")

        search_object: _SpotifySearchObject = {}
        for ot in object_types:
            # FIXME: Ask Logi what to do here
            items = response[f"{ot}s"]["items"]
            if items:
                search_object[ot] = items[0]
        if not search_object:
            raise SpotifyError(
                f"Could not find {' or '.join(object_types)} matching search criteria on Spotify."
            )

        # For each result object, use levenshtein distance to match the name to the query string and return the type of the best match as the string correct_type and the resulting object as the _SpotifySearchResult correct_object
        correct_type, correct_name, best_distance = None, None, float("inf")
        # FIXME: Temporary. Both below and above
        query_string = " ".join(w for w in args if w is not None)

        for object_type, obj in search_object.items():
            # FIXME: Would rather avoid this cast statement
            candidate_name = cast(_SpotifyObjectDict, obj)["name"]
            candidate_distance = self._levenshtein_distance(
                candidate_name, query_string
            )
            if correct_type is None or candidate_distance < best_distance:
                correct_type, correct_name, best_distance = (
                    object_type,
                    candidate_name,
                    candidate_distance,
                )
            print(f"candidate_name = {candidate_name}")
            print(f"candidate_distance = {candidate_distance}")
            print(f"correct_type = {correct_type}")
            print(f"correct_name = {correct_name}")
            print(f"best_distance = {best_distance}")

        # FIXME: These typing errors below
        correct_object = self._fill_result_object(
            search_object[correct_type], correct_type
        )
        self._object_type = correct_type
        print("Did I even make it here?")
        self._name = correct_name
        self._url = correct_object["url"]
        return correct_object

    def _fill_result_object(
        self,
        search_object: _SpotifyObjectDict,
        object_type: Literal["album", "artist", "track", "playlist"],
    ) -> _SpotifyResultObject:
        item_uri = search_object["uri"]
        id = search_object["id"]

        name = search_object["name"]
        context_uri = (
            search_object["album"]["uri"] if object_type is "track" else item_uri
        )
        url = (
            search_object["external_urls"]["spotify"]
            if object_type is "track"
            else self._get_song_url(id=id, object_type=object_type)
        )
        offset = {"uri": item_uri} if object_type is "track" else {"position": 0}
        artist = (
            search_object["artists"][0]["name"]
            if object_type in ["track", "artist"]
            else None
        )
        result: _SpotifyResultObject = {
            "name": name,
            "context_uri": context_uri,
            "url": url,
            "offset": offset,
            "artist": artist,
        }
        return result

    def _get_song_url(
        self, id: str, object_type: Literal["album", "playlist", "artist"]
    ) -> str:
        """
        Find the url of the first track on an album, playlist or by an artist
        """
        if object_type == "album":
            url = f"{_API_ENDPOINT}/albums/{id}/tracks"
        elif object_type == "playlist":
            url = f"{_API_ENDPOINT}/playlists/{id}/tracks"
        params = {"limit": "1"}
        try:
            response = GET_json(url, headers=self._headers, params=params)
        except Exception as e:
            raise SpotifyError(
                f"Error in GET request for first album track to Spotify: {e}"
            )

        try:
            return response["items"][0]["external_urls"]["spotify"]
        except IndexError:
            # FIXME: Can this happen?
            # FIXME: Clean if it does.
            raise SpotifyError("Error retrieving first track on album from Spotify.")

    def play(
        self,
        *,
        track: Optional[str],
        album: Optional[str],
        track_or_album: Optional[str],
        playlist: Optional[str],
        artist: Optional[str],
        anything: Optional[str],
        object_types: Tuple[Literal["album", "artist", "track", "playlist"], ...],
    ) -> None:
        """
        Searches Spotify for the desired object and plays it.
        """
        print("attempted to play")
        search_result = self._search_spotify(
            track=track,
            album=album,
            track_or_album=track_or_album,
            playlist=playlist,
            artist=artist,
            anything=anything,
            object_types=object_types,
        )
        print(f"search_result = {search_result}")

        url = f"{_API_ENDPOINT}/me/player/play"
        payload = {
            "context_uri": search_result["context_uri"],
        }
        if "offset" in search_result:
            payload["offset"] = search_result["offset"]

        try:
            PUT_json(url, json_data=payload, headers=self._headers)
        except HTTPError as e:
            raise SpotifyError(f"Error in PUT request playing album on Spotify: {e}")

    @property
    def album_name(self) -> str:
        if self._object_type != "album":
            raise SpotifyError("Album not target object of query.")
        return self._name

    @property
    def track_name(self) -> str:
        print(self._name)
        if self._object_type != "track":
            raise SpotifyError("Track not target object of query.")
        return self._name

    @property
    def artist_name(self) -> str:
        if self._object_type != "artist":
            raise SpotifyError("Artist not target object of query.")
        return self._name

    @property
    def playlist_name(self) -> str:
        if self._object_type != "playlist":
            raise SpotifyError("Playlist not target object of query.")
        return self._name

    @property
    def track_url(self) -> str:
        if self._url is None:
            raise SpotifyError("No url found in Spotify class instanec.")
        return self._url

    def _levenshtein_distance(self, a: str, b: str) -> int:
        """
        Calculate the Levenstein distance between two strings.
        """
        if len(a) < len(b):
            return self._levenshtein_distance(b, a)
        if len(b) == 0:
            return len(a)
        previous_row = range(len(b) + 1)
        for i, c1 in enumerate(a):
            current_row = [i + 1]
            for j, c2 in enumerate(b):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        return previous_row[-1]
