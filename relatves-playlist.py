import argparse
import functools
import itertools
import operator

import jmespath
import spotipy
import spotipy.util
from ordered_set import OrderedSet

DEFAULT_COUNTRY = None
DEFAULT_DEPTH = 1

CACHE_NAME = "access-tokens"
MAX_TRACKS_ADDED = 100
PLAYLIST_NAME = "<artist>'s Related Artists"
RESULT_LIMIT = 50
SCOPE = "playlist-modify-private"

ALBUM_ID_PATH = jmespath.compile("items[?length(@.artists)==`1`].id")
RELATED_ARTIST_ID_PATH = jmespath.compile("artists[*].id")
SEARCH_ARTIST_ID_PATH_FORMAT = "artists.items[?name=='{artist_name}'].{{id: id, popularity: popularity}}"
TRACK_ID_PATH = jmespath.compile("items[*].id")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("artist", help=("Either the artist's exact name, or their Spotify URI "
            "(e.g. spotify:artist:0OdUWJ0sBjDrqHygGUXeCF)."))
    parser.add_argument("-d", "--max-depth", type=int, default=DEFAULT_DEPTH,
            help=("The maximum depth to traverse the related artist list. A depth of 0 gets just the artist. It's "
            "recommended that this value not exceed 3, as it will start taking a long time and producing very large "
            "(and unrelated) playlists. (default: %(default)s)"))
    parser.add_argument("-c", "--country", default=DEFAULT_COUNTRY,
            help=("Only add albums available in this country to the playlist. If omitted, all albums will be added to "
            "the playlist regardless of country availability. (default: %(default)s)"))
    parser.add_argument("--include-seed", action="store_true",
            help=("Toggles inclusion of the seed artist in the playlist. (default: %(default)s)"))
    parser.add_argument("--ask", action="store_true",
            help=("By default, if the search finds two artists with the same exact name you specified, it will use "
            "the most popular one as the seed artist. Use this option to have it prompt you to choose instead."))
    parser.add_argument("-n", "--playlist-name", default=PLAYLIST_NAME,
            help=("What to name the resulting playlist. The special variable \"<artist>\" can be used to substitute "
            "this artist's name. (default: %(default)s)"))
    # parser.add_argument("-e", "--exclude-artists", action="append")

    return vars(parser.parse_args())

def get_client():
    token = spotipy.util.prompt_for_user_token(CACHE_NAME, SCOPE)
    if token:
        return spotipy.Spotify(auth=token)
    else:
        raise Exception("Failed to retrieve an access token.")


def create_playlist(artist_name, track_ids, playlist_name_format):
    username = spotify.me()["id"]
    playlist_name = playlist_name_format.replace("<artist>", artist_name)
    playlist_response = spotify.user_playlist_create(username, playlist_name, public=False)

    # The API only supports adding 100 tracks at a time.
    for offset in range(0, len(track_ids), MAX_TRACKS_ADDED):
        spotify.user_playlist_add_tracks(username, playlist_response["id"], track_ids[offset:offset + MAX_TRACKS_ADDED])

    return playlist_response["external_urls"]["spotify"]

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

def get_related_artist_ids(artist_id):
    related_artist_response = spotify.artist_related_artists(artist_id)
    return RELATED_ARTIST_ID_PATH.search(related_artist_response)

def get_track_ids(album_id):
    return _spotify_collect(spotify.album_tracks, album_id, TRACK_ID_PATH)

def get_album_ids(artist_id, country=DEFAULT_COUNTRY):
    full_album_op = functools.partial(spotify.artist_albums, album_type="album", country=country)
    return _spotify_collect(full_album_op, artist_id, ALBUM_ID_PATH)

def get_all_related_artists(seed_artist_id, max_depth, include_seed):
    def _get_related_artists(seed_artist_id, visited_artist_ids, depth=1):
        related_artist_ids = OrderedSet(get_related_artist_ids(seed_artist_id))
    
        # Leaves us with only the related artist IDs we've yet to visit
        related_artist_ids -= visited_artist_ids
        visited_artist_ids.update(related_artist_ids)
        
        if depth < max_depth:
            for artist_id in related_artist_ids:
                new_related_artist_ids = _get_related_artists(artist_id, visited_artist_ids, depth + 1)
                visited_artist_ids.update(new_related_artist_ids)
        return visited_artist_ids

    visited_artist_ids = OrderedSet((seed_artist_id,))
    related_artists = _get_related_artists(seed_artist_id, visited_artist_ids) if max_depth > 0 else visited_artist_ids
    if not include_seed:
        related_artists -= OrderedSet((seed_artist_id,))
    return related_artists

def _prompt_for_artist(artist_ids, artist_name):
    artist_objs = [spotify.artist(artist_id) for artist_id in artist_ids]
    
    print("Found {0} artists with the name \"{1}\".".format(len(artist_ids), artist_name))
    for index, artist_obj in enumerate(artist_objs, 1):
        print("{0}) {1}".format(index, artist_obj["external_urls"]["spotify"]))

    while True:
        artist_index_str = input("Please select one by entering the corresponding number and pressing ENTER: ")
        if artist_index_str.isdigit():
            artist_index = int(artist_index_str)
            if artist_index <= len(artist_obj) and artist_index > 0:
                return artist_objs[artist_index - 1]

def get_artist_id(artist_name, ask):
    search_id_path = jmespath.compile(SEARCH_ARTIST_ID_PATH_FORMAT.format(artist_name=artist_name))
    artist_search_op = functools.partial(spotify.search, type="artist")
    exact_matches = _spotify_collect(artist_search_op, artist_name, search_id_path, halt=lambda values: values)

    if not exact_matches:
        return None
    elif len(exact_matches) > 1:
        if ask:
            return _prompt_for_artist([match["id"] for match in exact_matches], artist_name)["id"]
        else:
            return sorted(exact_matches, key=lambda artist: artist["popularity"], reverse=True)[0]["id"]
    else:
        return exact_matches[0]["id"]

def get_artist(artist_uri):
    artist_response = spotify.artist(artist_uri)
    return artist_response["name"], artist_response["id"]

def is_spotify_artist_uri(artist):
    return artist.startswith("spotify:artist:")


if __name__ == "__main__":
    args = parse_args()
    artist = args["artist"]
    max_depth = args["max_depth"]

    spotify = get_client()

    print("Gathering artists...")
    if is_spotify_artist_uri(artist):
        artist_name, artist_id = get_artist(artist)
    else:
        artist_name = artist
        artist_id = get_artist_id(artist, args["ask"])
        if not artist_id:
            raise ValueError("I'm sorry, I couldn't find an artist on Spotify whose name was an exact match for \"{0}\". "
                    "Please check the spelling and try again.".format(artist))

    related_artist_ids = get_all_related_artists(artist_id, max_depth, args["include_seed"])

    print("Collecting tracks from each artist...")
    track_ids = []
    for related_artist_id in related_artist_ids:
        album_ids = get_album_ids(related_artist_id, args["country"])
        related_artist_track_ids = itertools.chain.from_iterable(get_track_ids(album_id) for album_id in album_ids)
        track_ids.extend(list(related_artist_track_ids))

    print("Found {0} tracks across {1} artists at most {2} steps removed from \"{3}\"."
            .format(len(track_ids), len(related_artist_ids), max_depth, artist_name))
    print("Creating the playlist...")
    playlist_url = create_playlist(artist_name, track_ids, args["playlist_name"])

    print("Your new playlist can be listened to here:")
    print(playlist_url)