import jmespath

class SearchSelector(object):
    def select(self, artists):
        selected_artists = self._select(artists)
        if not selected_artists:
            raise ValueError("I couldn't find any artists who matched the search criteria.")
        elif len(selected_artists) > 1:
            artist_uri_str = ", ".join([artist["uri"] for artist in selected_artists])
            raise ValueError(("I found multiple artists who matched the search criteria, and the selector failed to "
                    "pick one. Artist URIs: {0}").format(artist_uri_str))
        else:
            return selected_artists[0]

class MostPopular(SearchSelector):
    DESCRIPTION = "Selects the artist with the highest popularity score."
    PATH = jmespath.compile("sort_by(@, &popularity)[-1]")

    def _select(self, artists):
        return [MostPopular.PATH.search(artists)]

class MostFollowed(SearchSelector):
    DESCRIPTION = "Selects the artist with the highest total followers."
    PATH = jmespath.compile("sort_by(@, &followers.total)[-1]")

    def _select(self, artists):
        return [MostFollowed.PATH.search(artists)]

class Halt(SearchSelector):
    DESCRIPTION = "Raises an error if more than one artist was found."

    def _select(self, artists):
        return artists