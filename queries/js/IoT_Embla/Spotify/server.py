from flask import Flask, render_template
import requests
import json


app = Flask(__name__)


@app.route("/")
def spotify():
    return render_template("spotify.html")


@app.route("/play/")
def play(access_token):
    print("play")

    url = "https://api.spotify.com/v1/me/player/play"

    payload = ""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer ${access_token}",
    }

    response = requests.request("PUT", url, headers=headers, data=payload)

    print(response.text)

    return "play"

@app.route("/pause/")
def pause(access_token):
    print("pause")

    url = "https://api.spotify.com/v1/me/player/pause"

    payload = ""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer ${access_token}",
    }

    response = requests.request("PUT", url, headers=headers, data=payload)

    print(response.text)

    return "pause"

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=8001)
