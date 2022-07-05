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


    API routes
    Note: All routes ending with .api are configured not to be cached by nginx

"""

_GROUPS = {
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
    "gangur": "hallway",
    "borðstofa": "Dining Room",
    "gestasvefnherbergi": "Guest Room",
    "gesta svefnherbergi": "Guest Room",
    "gestaherbergi": "Guest Room",
    "gesta herbergi": "Guest Room",
    "leikherbergi": "Playroom",
    "leik herbergi": "Playroom",
    "sundlaug": "Pool",
    "sjónvarpsherbergi": "TV Room",
    "sjóvarps herbergi": "TV Room",
    "ferðahátalari": "Portable",
    "ferða hátalari": "Portable",
    "verönd": "Patio",
    "pallur": "Patio",
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

_RADIO_STEAMS = {
    "rás 1": "	http://netradio.ruv.is/ras1.mp3",
    "rás 2": "http://netradio.ruv.is/ras2.mp3",
    "rondo": "http://netradio.ruv.is/rondo.mp3",
    "rondó": "http://netradio.ruv.is/rondo.mp3",
    "bylgjan": "https://live.visir.is/hls-radio/bylgjan/playlist.m3u8",
    "fm 957": "https://live.visir.is/hls-radio/fm957/playlist.m3u8",
    "fm957": "https://live.visir.is/hls-radio/fm957/playlist.m3u8",
    "fm-957": "https://live.visir.is/hls-radio/fm957/playlist.m3u8",
    "Útvarp Saga": "https://stream.utvarpsaga.is/Hljodver",
    "k-100": "https://k100streymi.mbl.is/beint/k100/tracks-v1a1/rewind-3600.m3u8",
    "k 100": "https://k100streymi.mbl.is/beint/k100/tracks-v1a1/rewind-3600.m3u8",
    "k hundrað": "https://k100streymi.mbl.is/beint/k100/tracks-v1a1/rewind-3600.m3u8",
    "Gullbylgjan": "https://live.visir.is/hls-radio/gullbylgjan/playlist.m3u8",
    "x977": "https://live.visir.is/hls-radio/x977/playlist.m3u8",
    "x 977": "https://live.visir.is/hls-radio/x977/playlist.m3u8",
    "x-977": "https://live.visir.is/hls-radio/x977/playlist.m3u8",
    "x-ið": "https://live.visir.is/hls-radio/x977/playlist.m3u8",
    "x-ið 977": "https://live.visir.is/hls-radio/x977/playlist.m3u8",
    "léttbylgjan": "https://live.visir.is/hls-radio/lettbylgjan/playlist.m3u8",
    "retro": "https://k100straumar.mbl.is/retromobile",
    "kiss fm": "http://stream3.radio.is:443/kissfm",
    "flassbakk": "http://stream.radio.is:443/flashback",
    "flassbakk fm": "http://stream.radio.is:443/flashback",
    "útvarp 101": "https://stream.101.live/audio/101/chunklist.m3u8",
    "útvarp hundrað og einn": "https://stream.101.live/audio/101/chunklist.m3u8",
}


import requests
from datetime import datetime, timedelta
import flask
import random

from util import read_api_key
from queries import query_json_api, post_to_json_api
from query import Query

import json


class SonosClient:
    def __init__(self, device_data, client_id, query=None, radio_name=None):
        self._client_id = client_id
        self._device_data = device_data
        self._query = query
        self._radio_name = radio_name
        self._sonos_encoded_credentials = read_api_key("SonosEncodedCredentials")
        self._code = self._device_data["sonos"]["credentials"]["code"]
        print("code :", self._code)
        self._timestamp = datetime.now()
        print("device data :", self._device_data)
        try:
            self._access_token = self._device_data["sonos"]["credentials"][
                "access_token"
            ]
            self._refresh_token = self._device_data["sonos"]["credentials"][
                "refresh_token"
            ]
        except KeyError:
            self._create_token()
        self._check_token_expiration()
        self._households = self._get_households()
        self._household_id = self._households[0]["id"]
        self._groups = self._get_groups()
        self._players = self._get_players()
        self.store_sonos_data_and_credentials()

    def _check_token_expiration(self):
        """
        Checks if access token is expired, and calls a function to refresh it if necessary.
        """
        try:
            timestamp = self._device_data["sonos"]["credentials"]["timestamp"]
        except KeyError:
            print("No timestamp found for Sonos token.")
            return
        timestamp = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S.%f")
        if (datetime.now() - timestamp) > timedelta(hours=24):
            self._update_sonos_token()

    def _update_sonos_token(self):
        """
        Updates the access token
        """
        print("update sonos token")
        self._sonos_encoded_credentials = read_api_key("SonosEncodedCredentials")
        self._access_token = self._refresh_expired_token()
        self._access_token = self._access_token["access_token"]
        sonos_dict = {
            "sonos": {
                "credentials": {
                    "access_token": self._access_token,
                    "timestamp": str(datetime.now()),
                }
            }
        }

        self._store_data(sonos_dict)

    def _refresh_expired_token(self):
        """
        Helper function for updating the access token.
        """
        print("_refresh_expired_token")
        url = f"https://api.sonos.com/login/v3/oauth/access?grant_type=refresh_token&refresh_token={self._refresh_token}"
        headers = {"Authorization": f"Basic {self._sonos_encoded_credentials}"}

        response = post_to_json_api(url, headers=headers)

        return response

    def _create_token(self):
        """
        Creates a token given a code
        """
        print("_create_token")
        host = str(flask.request.host)
        url = f"https://api.sonos.com/login/v3/oauth/access?grant_type=authorization_code&code={self._code}&redirect_uri=http://{host}/connect_sonos.api"
        headers = {
            "Authorization": f"Basic {self._sonos_encoded_credentials}",
            "Cookie": "JSESSIONID=F710019AF0A3B7126A8702577C883B5F; AWSELB=69BFEFC914A689BF6DC8E4652748D7B501ED60290D5EA56F2E543ABD7CF357A5F65186AEBCFB059E28075D83A700FD504C030A53CC28683B515BE3DCA3CC587AFAF606E171; AWSELBCORS=69BFEFC914A689BF6DC8E4652748D7B501ED60290D5EA56F2E543ABD7CF357A5F65186AEBCFB059E28075D83A700FD504C030A53CC28683B515BE3DCA3CC587AFAF606E171",
        }

        response = post_to_json_api(url, headers=headers)

        self._access_token = response.get("access_token")
        self._refresh_token = response.get("refresh_token")
        return response

    def toggle_play_pause(self):
        """
        Toggles play/pause of a group
        """
        print("toggle playpause")
        group_id = self._get_group_id()
        print("exited group_id")
        url = f"https://api.ws.sonos.com/control/api/v1/groups/{group_id}/playback/togglePlayPause"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }

        # response = requests.request("POST", url, headers=headers, data=payload)
        response = post_to_json_api(url, headers=headers)
        print("response :", response)

        return response

    def _get_households(self):
        """
        Returns the list of households of the user
        """
        print("get households")
        try:
            return self._device_data["sonos"]["data"]["households"]
        except KeyError:
            url = f"https://api.ws.sonos.com/control/api/v1/households"
            headers = {"Authorization": f"Bearer {self._access_token}"}

            response = query_json_api(url, headers=headers)
            return response["households"]

    def _get_household_id(self):
        """
        Returns the household id for the given query
        """
        url = f"https://api.ws.sonos.com/control/api/v1/households"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }

        response = query_json_api(url, headers)

        return response["households"][0]["id"]

    def _get_groups(self):
        """
        Returns the list of groups of the user
        """
        print("get groups")
        try:
            return self._device_data["sonos"]["data"]["groups"]
        except KeyError:
            for i in range(len(self._households)):
                url = f"https://api.ws.sonos.com/control/api/v1/households/{self._household_id}/groups"
                headers = {"Authorization": f"Bearer {self._access_token}"}

                response = query_json_api(url, headers=headers)
                cleaned_groups_list = self._create_grouplist_for_db(response["groups"])
                return cleaned_groups_list

    def get_groups_and_players(self):
        """
        Returns the list of groups of the user
        """
        print("get groups and players")

        url = f"https://api.ws.sonos.com/control/api/v1/households/{self._household_id}/groups"
        headers = {"Authorization": f"Bearer {self._access_token}"}

        response = query_json_api(url, headers)
        return response.json()
        # return response.json()["groups"]

    def _get_group_id(self):
        """
        Returns the group id for the given query
        """
        print("get group_id")
        try:
            group_id = self._groups[0]["id"]
            return group_id
        except KeyError:
            url = f"https://api.ws.sonos.com/control/api/v1/households/{self._household_id}/groups"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._access_token}",
            }

            response = query_json_api(url, headers)

            return response["groups"][0]["id"]

    def _get_players(self):
        """
        Returns the list of groups of the user
        """
        print("get players")
        try:
            return self._device_data["sonos"]["data"]["players"]
        except KeyError:
            print("keyerror")
            for i in range(len(self._households)):
                url = f"https://api.ws.sonos.com/control/api/v1/households/{self._household_id}/groups"
                headers = {"Authorization": f"Bearer {self._access_token}"}

                response = query_json_api(url, headers)
                cleaned_players_list = self._create_playerlist_for_db(
                    response["players"]
                )
                return cleaned_players_list

    def _get_player_id(self):
        """
        Returns the player id for the given query
        """
        print("get player_id")
        try:
            player_id = self._players[0]["id"]
            return player_id
        except KeyError:
            url = f"https://api.ws.sonos.com/control/api/v1/households/{self._household_id}/groups"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._access_token}",
            }

            response = query_json_api(url, headers)

            return response["players"][0]["id"]

    def _create_sonos_data_dict(self):
        print("_create_sonos_data_dict")
        data_dict = {"households": self._households}
        # groups_list = []
        # players_list = []
        for i in range(len(self._households)):
            groups_raw = self._groups
            players_raw = self._players
            # groups_list += self._create_grouplist_for_db(groups_raw)
            groups_list = self._groups
            players_list = self._players

        data_dict["groups"] = groups_list
        data_dict["players"] = players_list
        return data_dict

    def _create_sonos_cred_dict(self):
        print("_create_sonos_cred_dict")
        cred_dict = {}
        cred_dict.update(
            {
                "access_token": self._access_token,
                "refresh_token": self._refresh_token,
                "timestamp": str(datetime.now()),
            }
        )
        return cred_dict

    def store_sonos_data_and_credentials(self):
        print("store_sonos_data_and_credentials")
        data_dict = self._create_sonos_data_dict()
        cred_dict = self._create_sonos_cred_dict()
        sonos_dict = {}
        sonos_dict["sonos"] = {"credentials": cred_dict, "data": data_dict}
        self._store_data(sonos_dict)

    def _store_data(self, data):
        Query.store_query_data(
            self._client_id, "iot_speakers", data, update_in_place=True
        )

    def _create_grouplist_for_db(self, groups):
        print("create_grouplist_for_db")
        groups_list = []
        for i in range(len(groups)):
            groups_list.append({groups[i]["name"]: groups[i]["id"]})
        return groups_list

    def _create_playerlist_for_db(self, players):
        print("create_playerlist_for_db")
        player_list = []
        for i in range(len(players)):
            player_list.append({players[i]["name"]: players[i]["id"]})
        return player_list

    def set_credentials(self, access_token, refresh_token):
        print("set_credentials")
        self._access_token = access_token
        self._refresh_token = refresh_token
        return

    def set_data(self):
        print("set_data")
        try:
            self._households = self._get_households()
            self._household_id = self._get_household_id()
            self._groups = self._get_groups()
            self._players = self._get_players()
            self._group_id = self._get_group_id()
        except KeyError:
            print("Missing device data for this account")
        return

    def audio_clip(self, audioclip_url):
        """
        Plays an audioclip from link to .mp3 file
        """
        player_id = self._get_player_id()
        url = f"https://api.ws.sonos.com/control/api/v1/players/{player_id}/audioClip"

        payload = json.dumps(
            {
                "name": "Embla",
                "appId": "com.acme.app",
                "streamUrl": f"{audioclip_url}",
                "volume": 50,
                "priority": "HIGH",
                "clipType": "CUSTOM",
            }
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }

        response = post_to_json_api(url, payload, headers)
        return response

    def create_or_join_session(self):
        url = f"https://api.ws.sonos.com/control/api/v1/groups/{self._group_id}/playbackSession/joinOrCreate"

        payload = json.dumps({"appId": "com.mideind.embla", "appContext": "embla123"})
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }

        response = post_to_json_api(url, payload, headers)
        print(response)
        session_id = response.sessionId
        return session_id

    def play_radio_stream(self, query=None):
        session_id = self._create_or_join_session()
        if query == None:
            radio_name, radio_url = random.choice(list(_RADIO_STEAMS.items()))
        else:
            radio_name, radio_url = _RADIO_STEAMS.get(query)

        url = f"https://api.ws.sonos.com/control/api/v1//playbackSessions/{session_id}/playbackSession/loadStreamUrl?"

        payload = json.dumps(
            {
                "streamUrl": f"{radio_url}",
                "playOnCompletion": True,
                "stationMetadata": {"name": f"{radio_name}"},
                "itemId": "StreamItemId",
            }
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }

        response = post_to_json_api(url, payload, headers)

        print(response.text)

    def increase_volume(self):
        group_id = self._get_group_id()
        url = f"https://api.ws.sonos.com/control/api/v1/groups/{group_id}/groupVolume/relative"

        payload = json.dumps({"volumeDelta": 10})
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }

        response = post_to_json_api(url, payload, headers)

        print(response.text)

    def decrease_volume(self):
        group_id = self._get_group_id()
        url = f"https://api.ws.sonos.com/control/api/v1/groups/{group_id}/groupVolume/relative"

        payload = json.dumps({"volumeDelta": -10})
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._access_token}",
        }

        response = post_to_json_api(url, payload, headers)

        print(response.text)


# # TODO: Check whether this should return the ids themselves instead of the json response
# def _get_households(token):
#     """
#     Returns the list of households of the user
#     """
#     url = f"https://api.ws.sonos.com/control/api/v1/households"

#     payload = {}
#     headers = {"Authorization": f"Bearer {token}"}

#     response = requests.request("GET", url, headers=headers, data=payload)

#     return response.json()


# def _get_groups(household_id, token):
#     """
#     Returns the list of groups of the user
#     """
#     url = f"https://api.ws.sonos.com/control/api/v1/households/{household_id}/groups"

#     payload = {}
#     headers = {"Authorization": f"Bearer {token}"}

#     response = requests.request("GET", url, headers=headers, data=payload)

#     return response


# def _create_token(code, sonos_encoded_credentials, host):
#     """
#     Creates a token given a code
#     """
#     url = f"https://api.sonos.com/login/v3/oauth/access?grant_type=authorization_code&code={code}&redirect_uri=http://{host}/connect_sonos.api"

#     payload = {}
#     headers = {
#         "Authorization": f"Basic {sonos_encoded_credentials}",
#         "Cookie": "JSESSIONID=F710019AF0A3B7126A8702577C883B5F; AWSELB=69BFEFC914A689BF6DC8E4652748D7B501ED60290D5EA56F2E543ABD7CF357A5F65186AEBCFB059E28075D83A700FD504C030A53CC28683B515BE3DCA3CC587AFAF606E171; AWSELBCORS=69BFEFC914A689BF6DC8E4652748D7B501ED60290D5EA56F2E543ABD7CF357A5F65186AEBCFB059E28075D83A700FD504C030A53CC28683B515BE3DCA3CC587AFAF606E171",
#     }

#     response = requests.request("POST", url, headers=headers, data=payload)

#     return response


# def refresh_token(sonos_encoded_credentials, refresh_token):
#     """
#     Refreshes token
#     """
#     url = f"https://api.sonos.com/login/v3/oauth/access?grant_type=refresh_token&refresh_token={refresh_token}"

#     payload = {}
#     headers = {"Authorization": f"Basic {sonos_encoded_credentials}"}

#     response = requests.request("POST", url, headers=headers, data=payload)

#     return response


# def audio_clip(audioclip_url, player_id, token):
#     """
#     Plays an audioclip from link to .mp3 file
#     """
#     import requests
#     import json

#     url = f"https://api.ws.sonos.com/control/api/v1/players/{player_id}/audioClip"

#     payload = json.dumps(
#         {
#             "name": "Embla",
#             "appId": "com.acme.app",
#             "streamUrl": f"{audioclip_url}",
#             "volume": 50,
#             "priority": "HIGH",
#             "clipType": "CUSTOM",
#         }
#     )
#     headers = {
#         "Content-Type": "application/json",
#         "Authorization": f"Bearer {token}",
#     }

#     response = requests.request("POST", url, headers=headers, data=payload)


# def _update_sonos_token(q, device_data):
#     print("update sonos token")
#     sonos_encoded_credentials = read_api_key("SonosEncodedCredentials")
#     refresh_token_str = device_data["sonos"]["credentials"]["refresh_token"]
#     access_token = refresh_token(sonos_encoded_credentials, refresh_token_str).json()
#     access_token = access_token["access_token"]
#     sonos_dict = {
#         "sonos": {
#             "credentials": {
#                 "access_token": access_token,
#                 "timestamp": str(datetime.now()),
#             }
#         }
#     }
#     q.set_client_data("iot_speakers", sonos_dict, update_in_place=True)