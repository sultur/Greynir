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
from typing import Dict, Optional, Union, List, cast, Set


from typing_extensions import TypedDict, Literal, NotRequired
from urllib.parse import urlencode as urlencode
from requests.exceptions import HTTPError
from datetime import datetime, timedelta

from utility import read_api_key
from query import Query, ClientDataDict
from queries import POST_json, PUT, GET_json, HTTPRequestSpecial


class SpotifyError(Exception):
    "Raised when there is an error communicating with the Spotify API."

    pass


class _SpotifyResultObject(TypedDict):
    name: str
    context_uri: str
    url: str
    offset: Optional[Union[Dict[str, int], Dict[str, str]]]
    by_artist: Optional[str]
    object_type: Literal["track", "album", "artist", "playlist"]


class _SpotifyObjectDict(TypedDict):
    name: str
    uri: str
    id: str
    album: Dict[str, str]
    external_urls: Dict[str, str]
    artists: List[Dict[str, str]]


class _SpotifySearchResponseObjects(TypedDict):
    album: NotRequired[_SpotifyObjectDict]
    track: NotRequired[_SpotifyObjectDict]
    artist: NotRequired[_SpotifyObjectDict]
    playlist: NotRequired[_SpotifyObjectDict]


class _SpotifyIntermediateDict(TypedDict):
    items: List[_SpotifySearchResponseObjects]


class _SpotifySearchResponse(TypedDict):
    tracks: _SpotifyIntermediateDict
    albums: _SpotifyIntermediateDict
    artists: _SpotifyIntermediateDict
    playlists: _SpotifyIntermediateDict


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

# TODO: Find a better way to get a song url for an artist. Currently, the most popular track
# is found and played off album. See Siri's "play music by ARTIST_NAME on Spotify". Might be impossible
# TODO: Fix the feedback properties (returning name of artist, album etc.) Perhaps by
# returning a type out of the play function and then using that type in the module to choose a response.
# TODO: Decide the architecture of the search function, which ones should
# be inner functions, which functions should be joined, etc.
# TODO: Store last played song in the client data and use that in case playback is resumed
# when it is empty. Altough, it might be better to just handle it with a "Veldu lag,
# tónlistarmann, plötu eða lagalista." response from Embla.


class SpotifyClient:
    _encoded_credentials = read_api_key("SpotifyEncodedCredentials")

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
        Query.store_query_data(
            client_id,
            "spotify",
            cast(ClientDataDict, data),
        )

    def __init__(
        self,
        device_data: SpotifyDeviceData,
        client_id: str,
    ):
        self._client_id: str = client_id
        self._device_data: SpotifyDeviceData = device_data
        self._result_name: str
        self._result_type: str
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

    def _store_data_and_credentials(self) -> None:
        cred_dict: _SpotifyCredentials = {
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "timestamp": self._timestamp,
            "expires_in": self._expires_in,
        }
        data_dict: _SpotifyData = {
            "tbd": "tbd",
        }
        spotify_dict: SpotifyDeviceData = {
            "credentials": cred_dict,
            "data": data_dict,
        }
        Query.store_query_data(
            self._client_id,
            "spotify",
            cast(ClientDataDict, spotify_dict),
        )

    def _search_spotify(
        self,
        *,
        track: Optional[str],
        album: Optional[str],
        track_or_album: Optional[str],
        playlist: Optional[str],
        artist: Optional[str],
        anything: Optional[str],
        t_types: Set[Literal["album", "artist", "track", "playlist"]],
    ) -> _SpotifyResultObject:
        """
        Search Spotify for the desired target type returning the result
        and updating the instance accordingly. If more than one target type
        specified, returns the result whose name has the lowest levenshtein distance
        from the target name.
        """
        if artist is not None and ({"playlist"}.intersection(t_types)):
            raise SpotifyError(f"Cannot search for a playlist by a specific artist.")

        args = (track, album, track_or_album, playlist, artist, anything)
        if all(c is None for c in args):
            raise SpotifyError(f"Must provide at least one search term.")

        url = f"{_API_ENDPOINT}/search"
        # The search is conducted by concatenating the search terms, instead of restricting the search by
        # album, artist, etc. (see Spotify API search docs). This because the user may have selected the incorrect entity
        # (i.e. a saying a featured artist instead of the leading one) and the speech recognition may have been inaccurate.
        params = {
            "type": ",".join(t_types),
            "q": " ".join(w for w in args if w is not None),
            "limit": "1",
            # Spotify overrides the market parameter if the user has an associated market.
            "market": "IS",
        }

        try:
            response = cast(
                _SpotifySearchResponse,
                GET_json(url, headers=self._headers, params=params),
            )
        except Exception as e:
            raise SpotifyError(f"Error during search GET request to Spotify: {e}")

        # Fill a dict with the relevant response objects for each type, if non-empty
        response_objects: _SpotifySearchResponseObjects = {
            t_type: response[f"{t_type}s"]["items"][0]  # type: ignore
            for t_type in t_types
            if response[f"{t_type}s"]["items"]  # type: ignore
        }

        try:
            assert len(response_objects.items())
        except AssertionError:
            raise SpotifyError(
                f"Could not find {' or '.join(t_types)} matching search criteria on Spotify."
            )

        # If more than one type matches the search query, choose the one with the lowest levenshtein distance.
        r_type = (
            self._find_result_type(
                track=track,
                album=album,
                track_or_album=track_or_album,
                playlist=playlist,
                artist=artist,
                anything=anything,
                t_types=t_types,
                resp_obj=response_objects,
            )
            if len(response_objects.items()) > 1
            else list(response_objects.keys())[0]
        )

        # FIXME: These typing errors below
        result_object = self._fill_result_object(
            object_dict=response_objects[r_type], r_type=r_type
        )
        self._result_type = r_type
        self._result_name = result_object["name"]
        self._url = result_object["url"]

        return result_object

    # FIXME: God awful function, needs to incorporated into something else,
    # or something. For example, putting all of these variables into a dict,
    # which would also help clean up _search_spotify
    def _find_result_type(
        self,
        *,
        track: Optional[str],
        album: Optional[str],
        track_or_album: Optional[str],
        playlist: Optional[str],
        artist: Optional[str],
        anything: Optional[str],
        t_types: Set[Literal["album", "artist", "track", "playlist"]],
        resp_obj: _SpotifySearchResponseObjects,
    ) -> Literal["album", "artist", "track", "playlist"]:
        """
        Finds the result type from the target types. The result type is the type of the
        object that the user is most likely to be referring to. This is done by finding
        the type that has the minimum Levenshtein distance from the target name.
        """
        # FIXME: Do this using a dict or by having the desired name as function input
        # The target name is the name of the relevant target identity, this fills in the correct name
        if {"album", "artist", "playlist", "track"} == t_types:
            t_name = anything
        elif {"album", "track"} == t_types:
            t_name = track_or_album
        elif len(t_types) == 1:
            t_name = locals()[next(iter(t_types))]
        else:
            raise SpotifyError(f"Invalid target types in search function: {t_types}")

        # Result type and minimum distance for the levenshtein distance minimization
        r_type: Literal["album", "artist", "track", "playlist"]
        min_dist = float("inf")

        # Conduct the levenshtein distance minimization. We go through the candidate types
        # in a set order to avoid, say, a playlist taking priority over a track with the same name
        for c_type in ["track", "album", "artist", "playlist"]:
            c_obj = resp_obj.get(c_type)
            if c_obj is None:
                continue
            # Candidate name, type and distance (between candidate name and target name)
            c_name = cast(_SpotifyObjectDict, c_obj)["name"]
            c_type = cast(Literal["album", "artist", "track", "playlist"], c_type)
            c_dist = self._levenshtein_distance(c_name.casefold(), t_name.casefold())  # type: ignore
            # Update result type and result name if new minimum distance
            if min_dist == float("inf") or c_dist < min_dist:
                r_type = c_type
                min_dist = c_dist

        assert r_type  # type: ignore
        return r_type

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

    def _fill_result_object(
        self,
        object_dict: _SpotifyObjectDict,
        r_type: Literal["album", "artist", "track", "playlist"],
    ) -> _SpotifyResultObject:
        item_uri = object_dict["uri"]
        id = object_dict["id"]
        """
        Takes as input the dict corresponding to the result type and fills out a
        _SpotifyResultObject accordingly. This is needed because each result type 
        has a different data structure in the Search output from the Spotify API.
        """

        name = object_dict["name"]
        context_uri = object_dict["album"]["uri"] if r_type == "track" else item_uri

        url = (
            object_dict["external_urls"]["spotify"]
            if r_type == "track"
            else self._get_song_url(id=id, r_type=r_type)
        )
        offset = {"uri": item_uri} if r_type == "track" else {"position": 0}
        by_artist = (
            object_dict["artists"][0]["name"] if r_type in ["track", "album"] else None
        )
        result: _SpotifyResultObject = {
            "name": name,
            "context_uri": context_uri,
            "url": url,
            "offset": offset,
            "by_artist": by_artist,
            "object_type": r_type,
        }
        return result

    def _get_song_url(
        self, id: str, r_type: Literal["album", "playlist", "artist"]
    ) -> str:
        """
        Find the url of the first track on an album or playlist, or the top track by an artist
        """
        # Each type has different API endpoints, parameters, and path to the external_url in the response
        type_routes = {
            "album": {
                "url": f"{_API_ENDPOINT}/albums/{id}/tracks",
                "params": {"limit": "1"},
                "resp_path": ["items", 0, "external_urls", "spotify"],
            },
            "playlist": {
                "url": f"{_API_ENDPOINT}/playlists/{id}/tracks",
                "params": {"limit": "1"},
                "resp_path": ["items", 0, "track", "external_urls", "spotify"],
            },
            "artist": {
                "url": f"{_API_ENDPOINT}/artists/{id}/top-tracks",
                "params": {"market": "IS"},
                "resp_path": ["tracks", 0, "external_urls", "spotify"],
            },
        }
        url = type_routes[r_type]["url"]
        params = type_routes[r_type]["params"]
        resp_path = type_routes[r_type]["resp_path"]

        try:
            response = GET_json(url, headers=self._headers, params=params)
        except Exception as e:
            raise SpotifyError(f"Error in GET request in _get_song_url: {e}")

        try:
            # FIXME: Why is there a type error here? The code works.
            # Go to the desired path in the response by iteratively applying the keys in resp_path
            result = response
            for key in resp_path:
                result = result[key]
            return result
        except IndexError:
            raise SpotifyError(
                "Error parsing Spotify response while getting song URL. Perhaps empty object."
            )

    def play(
        self,
        *,
        track: Optional[str],
        album: Optional[str],
        track_or_album: Optional[str],
        playlist: Optional[str],
        artist: Optional[str],
        anything: Optional[str],
        target_types: Set[Literal["album", "artist", "track", "playlist"]],
    ) -> None:
        """
        Searches Spotify for the desired object and plays it.
        """
        search_result = self._search_spotify(
            track=track,
            album=album,
            track_or_album=track_or_album,
            playlist=playlist,
            artist=artist,
            anything=anything,
            t_types=target_types,
        )

        url = f"{_API_ENDPOINT}/me/player/play"
        payload = {
            "context_uri": search_result["context_uri"],
            "offset": search_result["offset"],
        }

        if search_result["object_type"] == "artist":
            # The Spotify play endpoint does not accept an offset for artist contexts.
            del payload["offset"]

        try:
            PUT(url, json_data=payload, headers=self._headers)
        except HTTPError as e:
            raise SpotifyError(f"Error in PUT request playing album on Spotify: {e}")

    @property
    def name(self) -> str:
        return self._result_name

    @property
    def album_name(self) -> str:
        if self._result_type != "album":
            raise SpotifyError("Album not target object of query.")
        return self._result_name

    @property
    def track_name(self) -> str:
        if self._result_type != "track":
            raise SpotifyError("Track not target object of query.")
        return self._result_name

    @property
    def artist_name(self) -> str:
        if self._result_type != "artist":
            raise SpotifyError("Artist not target object of query.")
        return self._result_name

    @property
    def playlist_name(self) -> str:
        if self._result_type != "playlist":
            raise SpotifyError("Playlist not target object of query.")
        return self._result_name

    @property
    def track_url(self) -> str:
        if self._url is None:
            raise SpotifyError("No url found in Spotify class instance.")
        return self._url

    ###############################################################
    # These functions are not used right now. But, here they are. #
    ###############################################################

    def resume_playback(self) -> None:
        """
        Resumes playback on Spotify, if possible.
        """
        url = f"{_API_ENDPOINT}/me/player/play"
        try:
            # Could not reproduce error where there is an active device
            # but no active playback. So unknown status code.
            PUT(url, headers=self._headers, status_code=[404])
        except HTTPRequestSpecial as e:
            raise SpotifyError(
                f"Error in PUT request resuming playback. No active device."
            )
        except HTTPError as e:
            raise SpotifyError(
                f"Error in PUT request resuming playback on Spotify: {e}"
            )

    def pause_playback(self) -> None:
        url = f"{_API_ENDPOINT}/me/player/pause"
        try:
            PUT(url, headers=self._headers, status_code=[403, 404])
        except HTTPRequestSpecial:
            raise SpotifyError(
                f"Error in PUT request pausing playback. No active device (404) or already paused (403)."
            )
        except HTTPError as e:
            raise SpotifyError(f"Error in PUT request pausing playback on Spotify: {e}")
