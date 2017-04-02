import argparse
import collections
import functools
import itertools
import logging
import operator
import os

import spotipy
import spotipy.util
from ordered_set import OrderedSet

import smartlogger
import spotify_wrapper
import search_selectors


DEFAULT_DEPTH = 1
DEFAULT_PLAYLIST_NAME = "<artist>'s Relatives"

CACHE_NAME = "access-tokens"
MAX_VERBOSITY_LEVEL = 2
SCOPES = ["user-read-private", "playlist-modify-private"]
VERBOSITY_MAP = {
    -1: logging.CRITICAL,
    0: logging.INFO + 5,
    1: logging.INFO,
    2: logging.DEBUG
}
SELECTORS = collections.OrderedDict([
    ("most-popular", search_selectors.MostPopular),
    ("most-followed", search_selectors.MostFollowed),
    ("halt", search_selectors.Halt)
])
LOWER_FIRST = lambda string: (string[0].lower() + string[1:])
SELECTOR_HELP_STRS = ["{0} {1}".format(key, LOWER_FIRST(value.DESCRIPTION)[:-1]) for key, value in SELECTORS.items()]

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("seed_artist",
            help=("The artist's exact name or Spotify URI. (e.g. spotify:artist:0OdUWJ0sBjDrqHygGUXeCF)."))

    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("-v", "--verbose", action="count",
            help=("The verbosity level. If given once, prints out a high-level summary after a couple key operations. "
            "If given twice or more, prints out a more detailed report after each operation."))
    output_group.add_argument("-s", "--silent", action="store_true", help=("Don't output anything to standard out."))

    parser.add_argument("-d", "--max-depth", type=int, default=DEFAULT_DEPTH,
            help=("Depth to traverse the related artist list. I recommend this not exceed 3, as it will start taking a "
            "long time and producing very large (and unrelated) playlists. (default: %(default)s)"))
    parser.add_argument("--include-root", action="store_true",
            help=("Toggles inclusion of the seed artist in the playlist. (default: %(default)s)"))
    parser.add_argument("--search-selector", default="halt", choices=SELECTORS.keys(),
            help=("Strategy for selecting an artist when multiple are found matching the seed artist. "
            "{0} (default: %(default)s)")
                .format(", ".join(SELECTOR_HELP_STRS[:-1] + [" and " + SELECTOR_HELP_STRS[-1]])))
    parser.add_argument("-n", "--playlist-name", default=DEFAULT_PLAYLIST_NAME,
            help=("Playlist name format. Use <artist> to substitute the seed artist's name."))
    parser.add_argument("-e", "--exclude-artist", action="append", default=[],
            help=("Artist name or Spotify URI. Exclude this artist from the list of relatives. Repeat this argument to "
            "exclude multiple artists."))
    parser.add_argument("--exclude-from-parent",
            help=("An artist name or Spotify URI. Walk this artist's related artists tree until the seed artist is "
            "encountered. All artists between them, including artists on the same level, are excluded from the "
            "playlist."))

    return vars(parser.parse_args())

def get_client():
    token = os.getenv("AUTH_TOKEN")
    if not token:
        scope_str = " ".join(SCOPES)
        token = spotipy.util.prompt_for_user_token(CACHE_NAME, scope_str)
    if not token:
        raise Exception("Failed to retrieve an access token.")
    return spotipy.Spotify(auth=token)

class ArtistRelativesApp(object):
    def __init__(self, spotify_client, current_user, playlist_name_format, max_depth, include_root, selector, logger):
        self.spotify_client = spotify_client
        self.current_user = current_user
        self.playlist_name_format = playlist_name_format
        self.max_depth = max_depth
        self.include_root = include_root
        self.selector = selector
        self.logger = logger

    @staticmethod
    def create(spotify_client, playlist_name_format, max_depth, include_root, selector_name, verbosity):
        client = spotify_wrapper.SpotifyWrapper(spotify_client)
        current_user = client.get_current_user()
        logger = smartlogger.create_logger(VERBOSITY_MAP[verbosity], __file__)
        selector = SELECTORS[selector_name]()
        return ArtistRelativesApp(client, current_user, playlist_name_format, max_depth, include_root, selector, logger)

    def _display_playlist_urls(self, playlist_urls):
        if len(playlist_urls) == 1:
            self.logger.info("Your new playlist can be listened to here:")
        else:
            self.logger.info(
                    "Your new playlist would exceed the maximum playlist length, so multiple playlists were created:")
    
        for playlist_url in playlist_urls:
            self.logger.log(VERBOSITY_MAP[0], playlist_url)

    def _create_playlist(self, artist_name, track_ids, playlist_name_format):
        playlist_base_name = playlist_name_format.replace("<artist>", artist_name)
        responses = self.spotify_client.create_playlist(playlist_base_name, self.current_user["username"], track_ids)

        if len(responses) > 1:
            for index, response in enumerate(responses):
                playlist_name = "{0} (part {1})".format(playlist_base_name, index + 1)
                self.spotify_client.playlist_edit(response["id"], username, name=playlist_name)
        return [response["external_urls"]["spotify"] for response in responses]

    def _gather_tracks(self, related_artist_ids):
        track_ids = []
        for related_artist_id in related_artist_ids:
            album_ids = self.spotify_client.artist_album_ids(related_artist_id, self.current_user["country"])
            related_artist_track_ids = list(itertools.chain.from_iterable(
                self.spotify_client.album_track_ids(album_id) for album_id in album_ids))
            track_ids.extend(related_artist_track_ids)

            self.logger.debug("Found %d tracks across %d album(s) for artist %s.",
                    len(related_artist_track_ids), len(album_ids), related_artist_id)
        return track_ids

    def _walk_relatives(self, root_artist_id, include_root, halt_condition, excluded_artist_ids=set()):
        def _visit_relatives(artist_id):
            visited_artist_ids = OrderedSet([artist_id])
            artist_ids = OrderedSet([artist_id])
            depth = 0
            while not halt_condition(visited_artist_ids, depth):
                self.logger.debug("%d artists on level %d for whom to gather relatives.", len(artist_ids), depth)
                relative_ids = OrderedSet()
                for artist_id in artist_ids:
                    relative_ids.update(self.spotify_client.related_artist_ids(artist_id))
                relative_ids -= visited_artist_ids
                relative_ids -= excluded_artist_ids
                self.logger.debug("After removing relatives either excluded or already visited, %d new relatives found "
                        "on level %d.", len(relative_ids), depth)
                visited_artist_ids.update(relative_ids)

                artist_ids = relative_ids
                depth += 1
            return visited_artist_ids

        relative_ids = _visit_relatives(root_artist_id)
        if not include_root:
            relative_ids -= OrderedSet((root_artist_id,))
        return relative_ids

    def _query_artist_id_by_name(self, artist_name):
        exact_matches = self.spotify_client.search_artist_ids(artist_name)
        if not exact_matches:
            return None

        self.logger.debug("%d match(es) found for %s.", len(exact_matches), artist_name)
        artist_obj = self.selector.select(exact_matches)
        return artist_obj["id"]

    def _load_artist(self, artist):
        if self.spotify_client.is_artist_uri(artist):
            self.logger.debug("Artist URI provided. Loading other info.")
            artist_id, artist_name = self.spotify_client.get_artist(artist)
        else:
            self.logger.debug("Artist name provided. Searching for artist ID (and other info) by name.")
            artist_name = artist
            artist_id = self._query_artist_id_by_name(artist)
            if not artist_id:
                raise ValueError("I'm sorry, I couldn't find an artist whose name was an exact match for \"{0}\". "
                        "Please check the spelling and try again.".format(artist))
        return artist_id, artist_name

    def create_relatives_playlist(self, artist, excluded_artists=[], exclude_from_parent=None):
        artist_id, artist_name = self._load_artist(artist)

        excluded_artist_ids = {self._load_artist(artist)[0] for artist in excluded_artists}
        if exclude_from_parent:
            parent_id, parent_name = self._load_artist(exclude_from_parent)
            self.logger.info("Discovering artists between %s and %s...", parent_name, artist_name)
            excluded_artist_ids = self._walk_relatives(parent_id, True,
                    lambda visited_ids, depth: artist_id in visited_ids)
            self.logger.debug("Discovered %d artists to exclude.", len(excluded_artist_ids))

        self.logger.info("Gathering artists...")
        relative_ids = self._walk_relatives(artist_id, self.include_root,
                lambda visited_ids, depth: depth >= self.max_depth, excluded_artist_ids)

        self.logger.info("Collecting tracks from each artist...")
        track_ids = self._gather_tracks(relative_ids)

        self.logger.info("Found %d tracks across %d artists at most %d step(s) removed from \"%s\".",
                len(track_ids), len(relative_ids), self.max_depth, artist_name)
        self.logger.info("Creating the playlist...")
        playlist_urls = self._create_playlist(artist_name, track_ids, self.playlist_name_format)

        self._display_playlist_urls(playlist_urls)

if __name__ == "__main__":
    args = parse_args()
    args["include_root"] = args["include_root"] or args["max_depth"] == 0
    verbosity = min(args["verbose"] or (-1 if args["silent"] else 0), MAX_VERBOSITY_LEVEL)

    spotify = get_client()
    artist_relatives_app = ArtistRelativesApp.create(spotify, args["playlist_name"], args["max_depth"],
            args["include_root"], args["search_selector"], verbosity)
    artist_relatives_app.create_relatives_playlist(args["seed_artist"], args["exclude_artist"],
            args["exclude_from_parent"])