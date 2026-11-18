"""Data Models for Music Analytics."""


class Artist:
    """Represents a music artist."""

    def __init__(self, artist_id: int, name: str) -> None:
        self.artist_id = artist_id
        self.name = name
        self.albums: list[Album] = []

    def add_album(self, album: "Album") -> None:
        """Attach album to this artist."""
        self.albums.append(album)

    def album_count(self) -> int:
        """Return how many albums the artist has."""
        return len(self.albums)

    def to_dict(self) -> dict[str, int | str]:
        """Return the JSON form: artist_id, name and album_count."""
        return {
            "artist_id": self.artist_id,
            "name": self.name,
            "album_count": self.album_count(),
        }


class Album:
    """Represents a music album."""

    def __init__(
        self, album_id: int, title: str, artist_id: int, track_count: int = 0
    ) -> None:
        self.album_id = album_id
        self.title = title
        self.artist_id = artist_id
        self.track_count = track_count

    def to_dict(self) -> dict[str, int | str]:
        """Return the JSON form: album_id, title, artist_id and track_count."""
        return {
            "album_id": self.album_id,
            "title": self.title,
            "artist_id": self.artist_id,
            "track_count": self.track_count,
        }


class MusicStore:
    """In-memory store for music data."""

    def __init__(self) -> None:
        self._artists: dict[int, Artist] = {}
        self._albums: dict[int, Album] = {}
        self._load_sample_data()

    def _load_sample_data(self) -> None:
        """Load sample music data."""
        artists_data = [
            (1, "AC/DC"),
            (2, "Accept"),
            (3, "Aerosmith"),
            (4, "Alanis Morissette"),
            (5, "Alice In Chains"),
        ]

        albums_data = [
            (1, "For Those About To Rock", 1, 10),
            (2, "Let There Be Rock", 1, 8),
            (3, "Balls to the Wall", 2, 10),
            (4, "Restless and Wild", 2, 9),
            (5, "Big Ones", 3, 15),
            (6, "Jagged Little Pill", 4, 13),
            (7, "Facelift", 5, 12),
            (8, "Dirt", 5, 13),
        ]

        for artist_id, name in artists_data:
            self._artists[artist_id] = Artist(artist_id, name)

        for album_id, title, artist_id, track_count in albums_data:
            album = Album(album_id, title, artist_id, track_count)
            self._albums[album_id] = album
            if artist_id in self._artists:
                self._artists[artist_id].add_album(album)

    def get_all_artists(self) -> list[Artist]:
        """Return every artist, in insertion order."""
        return list(self._artists.values())

    def get_artist(self, artist_id: int) -> Artist | None:
        """Return the artist with artist_id, or None if it does not exist."""
        return self._artists.get(artist_id)

    def get_all_albums(self) -> list[Album]:
        """Return every album, in insertion order."""
        return list(self._albums.values())

    def search_artists(self, query: str) -> list[Artist]:
        """Return artists whose name contains query (case-insensitive)."""
        query = query.lower()
        return [a for a in self._artists.values() if query in a.name.lower()]


music_store = MusicStore()
