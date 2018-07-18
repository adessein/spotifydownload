#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
spotifyDownload
Arnaud DESSEIN
https://bitbucket.org/adessein/spotifydownload

** Licence : GPL v3 **

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.

** Credits **

All the SpotifyAPI class and large part of the main code is from
Casey Chu and Erik Westrup. Their work is available on 
https://github.com/caseychu/spotify-backup/blob/master/spotify-backup.py


"""

import argparse
import codecs
import http.client
import http.server
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from urllib.request import urlopen, quote
from bs4 import BeautifulSoup
import youtube_dl
import os

ydl_opts = {
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
        'preferredquality': '192',
    }],
}

baseFolder = "/media/nonolili/Data/Music/Spotify"
playlistsToDownload = ['Disco funk']

class SpotifyAPI:

    # Requires an OAuth token.
    def __init__(self, auth):
        self._auth = auth

    # Gets a resource from the Spotify API and returns the object.
    def get(self, url, params={}, tries=3):
        # Construct the correct URL.
        if not url.startswith('https://api.spotify.com/v1/'):
            url = 'https://api.spotify.com/v1/' + url
        if params:
            url += ('&' if '?' in url else '?') + urllib.parse.urlencode(params)

        # Try the sending off the request a specified number of times before giving up.
        for _ in range(tries):
            try:
                req = urllib.request.Request(url)
                req.add_header('Authorization', 'Bearer ' + self._auth)
                res = urllib.request.urlopen(req)
                reader = codecs.getreader('utf-8')
                return json.load(reader(res))
            except Exception as err:
                log('Couldn\'t load URL: {} ({})'.format(url, err))
                time.sleep(2)
                log('Trying again...')
        sys.exit(1)

    # The Spotify API breaks long lists into multiple pages. This method automatically
    # fetches all pages and joins them, returning in a single list of objects.
    def list(self, url, params={}):
        response = self.get(url, params)
        items = response['items']
        while response['next']:
            response = self.get(response['next'])
            items += response['items']
        return items

    # Pops open a browser window for a user to log in and authorize API access.
    @staticmethod
    def authorize(client_id, scope):
        webbrowser.open('https://accounts.spotify.com/authorize?' + urllib.parse.urlencode({
            'response_type': 'token',
            'client_id': client_id,
            'scope': scope,
            'redirect_uri': 'http://127.0.0.1:{}/redirect'.format(SpotifyAPI._SERVER_PORT)
        }))

        # Start a simple, local HTTP server to listen for the authorization token... (i.e. a hack).
        server = SpotifyAPI._AuthorizationServer('127.0.0.1', SpotifyAPI._SERVER_PORT)
        try:
            while True:
                server.handle_request()
        except SpotifyAPI._Authorization as auth:
            return SpotifyAPI(auth.access_token)

    # The port that the local server listens on. Don't change this,
    # as Spotify only will redirect to certain predefined URLs.
    _SERVER_PORT = 43019

    class _AuthorizationServer(http.server.HTTPServer):
        def __init__(self, host, port):
            http.server.HTTPServer.__init__(self, (host, port), SpotifyAPI._AuthorizationHandler)

        # Disable the default error handling.
        def handle_error(self, request, client_address):
            raise

    class _AuthorizationHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            # The Spotify API has redirected here, but access_token is hidden in the URL fragment.
            # Read it using JavaScript and send it to /token as an actual query string...
            if self.path.startswith('/redirect'):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<script>location.replace("token?" + location.hash.slice(1));</script>')

            # Read access_token and use an exception to kill the server listening...
            elif self.path.startswith('/token?'):
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<script>close()</script>Thanks! You may now close this window.')
                raise SpotifyAPI._Authorization(re.search('access_token=([^&]*)', self.path).group(1))

            else:
                self.send_error(404)

        # Disable the default logging.
        def log_message(self, format, *args):
            pass

    class _Authorization(Exception):
        def __init__(self, access_token):
            self.access_token = access_token

if __name__ == '__main__':
    # Parse arguments.
    parser = argparse.ArgumentParser(description='Exports your Spotify playlists. By default, opens a browser window '
                                               + 'to authorize the Spotify Web API, but you can also manually specify'
                                               + ' an OAuth token with the --token option.')
    parser.add_argument('--token', metavar='OAUTH_TOKEN', help='use a Spotify OAuth token (requires the '
                                               + '`playlist-read-private` permission)')
    parser.add_argument('--format', default='txt', choices=['json', 'txt'], help='output format (default: txt)')
    parser.add_argument('file', help='output filename', nargs='?')
    args = parser.parse_args()

    # Log into the Spotify API.
    if args.token:
        spotify = SpotifyAPI(args.token)
    else:
        spotify = SpotifyAPI.authorize(client_id='5c098bcc800e45d49e476265bc9b6934', scope='playlist-read-private')

    # Get the ID of the logged in user.
    me = spotify.get('me')
    log('Logged in as {display_name} ({id})'.format(**me))

    # List all playlists and all track in each playlist.
    playlists = spotify.list('users/{user_id}/playlists'.format(user_id=me['id']), {'limit': 50})
    for playlist in playlists:
        log('Loading playlist: {name} ({tracks[total]} songs)'.format(**playlist))
        playlist['tracks'] = spotify.list(playlist['tracks']['href'], {'limit': 100})

    # donwload videos and extract audio
    for playlist in playlists:
        if playlist['name'] in playlistsToDownload:
            os.chdir(baseFolder)
            if not os.path.exists(playlist['name']):
                os.makedirs(playlist['name'])
            os.chdir(playlist['name'])
            for track in playlist['tracks']:
                artists = ', '.join([artist['name'] for artist in track['track']['artists']])
                trackName = track['track']['name']
                query = quote(' '.join([artists, trackName]))
                url = "https://www.youtube.com/results?search_query=" + query
                response = urlopen(url)
                html = response.read()
                soup = BeautifulSoup(html, "lxml")
                vids = soup.findAll(attrs={'class':'yt-uix-tile-link'})
                ydl_opts["outtmpl"]= "{:s} - {:s}.%(ext)s".format(artists, trackName)
                with youtube_dl.YoutubeDL(ydl_opts) as ydl:
                    ydl.download(['https://www.youtube.com' + vids[0]['href']])
