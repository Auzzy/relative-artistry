import functools

import jmespath
import itertools
import spotipy
import spotipy.util
from ordered_set import OrderedSet

COUNTRY = "US"
MAX_DEPTH = 1
PLAYLIST_NAME = "{artist_name} - Related Artist Tree"
RESULT_LIMIT = 50
SCOPE = "playlist-modify-private"
USERNAME = "metalnut4"

MAX_TRACKS_ADDED = 100

ALBUM_ID_PATH = jmespath.compile("items[?length(@.artists)==`1`].id")
RELATED_ARTIST_ID_PATH = jmespath.compile("artists[*].id")
SEARCH_ARTIST_ID_PATH_FORMAT = "artists.items[?name=='{artist_name}'].id"
TRACK_ID_PATH = jmespath.compile("items[*].id")


def get_client():
    token = spotipy.util.prompt_for_user_token(USERNAME, SCOPE)
    if token:
        return spotipy.Spotify(auth=token)
    else:
        raise Exception("Failed to get token for {0}".format(username))

def _spotify_collect(op, request_key, value_path, halt=lambda values: False):
    values = []
    offset = 0
    while True:
        result = op(request_key, limit=RESULT_LIMIT, offset=offset)
        values += value_path.search(result)
        if halt(values) or not result["next"]:
            break

        offset += len(values)
    return values

def create_playlist(artist_name, track_ids):
    playlist_response = spotify.user_playlist_create(USERNAME, PLAYLIST_NAME.format(artist_name=artist_name), public=False)
    
    # The API only supports adding 100 tracks at a time.
    for offset in range(0, len(track_ids), MAX_TRACKS_ADDED):
        spotify.user_playlist_add_tracks(USERNAME, playlist_response["id"], track_ids[offset:offset + MAX_TRACKS_ADDED])

def get_related_artist_ids(artist_id):
    related_artist_response = spotify.artist_related_artists(artist_id)
    return RELATED_ARTIST_ID_PATH.search(related_artist_response)

def get_track_ids(album_id):
    return _spotify_collect(spotify.album_tracks, album_id, TRACK_ID_PATH)

def get_album_ids(artist_id):
    full_album_op = functools.partial(spotify.artist_albums, album_type="album", country=COUNTRY)
    return _spotify_collect(full_album_op, artist_id, ALBUM_ID_PATH)

def get_all_related_artists(seed_artist_id):
    def _get_related_artists(seed_artist_id, visited_artist_ids, depth=1):
        related_artist_ids = OrderedSet(get_related_artist_ids(seed_artist_id))
    
        # Leaves us with only the related artist IDs we've yet to visit
        related_artist_ids -= visited_artist_ids
        visited_artist_ids.update(related_artist_ids)
        
        if depth < MAX_DEPTH:
            for artist_id in related_artist_ids:
                new_related_artist_ids = _get_related_artists(artist_id, visited_artist_ids, depth + 1)
                visited_artist_ids.update(new_related_artist_ids)
        return visited_artist_ids
    
    visited_artist_ids = OrderedSet((seed_artist_id,))
    return _get_related_artists(seed_artist_id, visited_artist_ids)

def get_artist_id(artist_name):
    search_id_path = jmespath.compile(SEARCH_ARTIST_ID_PATH_FORMAT.format(artist_name=artist_name))
    artist_search_op = functools.partial(spotify.search, type="artist")
    exact_matches = _spotify_collect(artist_search_op, artist_name, search_id_path, halt=lambda values: values)

    if not exact_matches:
        return None
    elif len(exact_matches) > 1:
        # TODO: Need some way to surface when 2 bands have the same name, so the user can choose between them
        pass
    else:
        return exact_matches[0]

artist_name = "16"
if __name__ == "__main__":
    spotify = get_client()
    artist_id = get_artist_id(artist_name)
    related_artist_ids = get_all_related_artists(artist_id)
    track_ids = []
    for related_artist_id in related_artist_ids:
        album_ids = get_album_ids(related_artist_id)
        related_artist_track_ids = itertools.chain.from_iterable(get_track_ids(album_id) for album_id in album_ids)
        track_ids.extend(list(related_artist_track_ids))

    create_playlist(artist_name, track_ids)