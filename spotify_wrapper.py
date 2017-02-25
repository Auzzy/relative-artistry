import functools
import jmespath

ALBUM_ID_PATH = jmespath.compile("items[?length(@.artists)==`1`].id")
RELATED_ARTIST_ID_PATH = jmespath.compile("artists[*].id")
SEARCH_ARTIST_ID_PATH_FORMAT = "artists.items[?name=='{artist_name}'].{{id: id, popularity: popularity}}"
TRACK_ID_PATH = jmespath.compile("items[*].id")
DEFAULT_NEXT_PATH = jmespath.compile("next")
SEARCH_ARTIST_NEXT_PATH = jmespath.compile("artists.next")

MAX_PLAYLIST_SIZE = 11000
MAX_TRACKS_ADDED = 100
RESULT_LIMIT = 50

class SpotifyWrapper(object):
    def __init__(self, spotify_client):
        self._spotify_client = spotify_client

    @staticmethod
    def _collect(op, request_key, value_path, next_path=DEFAULT_NEXT_PATH, halt=lambda values: False):
        values = []
        offset = 0
        while True:
            result = op(request_key, limit=RESULT_LIMIT, offset=offset)
            values += value_path.search(result)
            next = next_path.search(result)
            if halt(values) or not next:
                break
    
            offset += len(values)
        return values
    
    def album_track_ids(self, album_id):
        return SpotifyWrapper._collect(self._spotify_client.album_tracks, album_id, TRACK_ID_PATH)
    
    def artist_album_ids(self, artist_id, country=None):
        full_album_op = functools.partial(self._spotify_client.artist_albums, album_type="album", country=country)
        return SpotifyWrapper._collect(full_album_op, artist_id, ALBUM_ID_PATH)

    def search_artist_ids(self, artist_name):
        search_id_path = jmespath.compile(SEARCH_ARTIST_ID_PATH_FORMAT.format(artist_name=artist_name))
        artist_search_op = functools.partial(self._spotify_client.search, type="artist")
        return SpotifyWrapper._collect(artist_search_op, artist_name, search_id_path, SEARCH_ARTIST_NEXT_PATH, halt=lambda values: values)

    def related_artist_ids(self, artist_id):
        related_artist_response = self._spotify_client.artist_related_artists(artist_id)
        return RELATED_ARTIST_ID_PATH.search(related_artist_response)

    def get_artist(self, artist_uri):
        artist_response = self._spotify_client.artist(artist_uri)
        return artist_response["id"], artist_response["name"]

    def artist(self, artist_id):
        return self._spotify_client.artist(artist_id)

    def create_playlist(self, name, username, track_ids=[], is_public=False):
        responses = []
        while track_ids:
            playlist_track_ids, track_ids = track_ids[:MAX_PLAYLIST_SIZE], track_ids[MAX_PLAYLIST_SIZE:]
            response = self._spotify_client.user_playlist_create(username, name, public=is_public)
            while playlist_track_ids:
                playlist_track_ids = self.playlist_add_tracks(username, response["id"], playlist_track_ids)
            responses.append(response)
        return responses

    def playlist_add_tracks(self, username, id, track_ids):
        self._spotify_client.user_playlist_add_tracks(username, id, track_ids[:MAX_TRACKS_ADDED])
        return track_ids[MAX_TRACKS_ADDED:]

    def playlist_edit(self, id, username, name=None, is_public=None, collaborative=None):
        return self._spotify_client.user_playlist_change_details(id, username, name=name)

    def get_current_user(self):
        current_user = self._spotify_client.me()
        current_user["username"] = current_user["id"]
        return current_user

    @staticmethod
    def is_artist_uri(artist):
        return artist.startswith("spotify:artist:")