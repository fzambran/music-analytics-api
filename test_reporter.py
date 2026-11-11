"""Integration tests for reporter.py against the real chinook.db."""

import csv
import json
import os
import sqlite3
import sys
from contextlib import closing
from dataclasses import asdict

import pytest

import reporter
from db_routes import CHINOOK_DB_PATH, get_db_connection
from reporter import (
    ArtistStats,
    find_artist_id,
    find_artist_ids_containing,
    get_artist_stats,
    validate_schema,
)


@pytest.fixture
def connection():
    with closing(get_db_connection()) as conn:
        yield conn


@pytest.fixture
def stats_by_id(connection):
    return {item.artist_id: item for item in get_artist_stats(connection)}


@pytest.fixture
def detailed_by_id(connection):
    stats = get_artist_stats(connection, include_albums=True)
    return {item.artist_id: item for item in stats}


def test_one_row_per_artist(connection, stats_by_id):
    (artist_count,) = connection.execute("SELECT COUNT(*) FROM Artist").fetchone()
    assert artist_count == 275
    assert len(stats_by_id) == artist_count


def test_no_metric_is_none(stats_by_id):
    for item in stats_by_id.values():
        assert None not in vars_of(item).values(), item


def test_known_artists(stats_by_id):
    assert stats_by_id[1] == ArtistStats(
        artist_id=1,
        name="AC/DC",
        album_count=2,
        track_count=18,
        total_duration_ms=4853674,
        avg_track_duration_ms=269649,
        revenue=15.84,
        units_sold=16,
        genres=("Rock",),
    )
    assert stats_by_id[90] == ArtistStats(
        artist_id=90,
        name="Iron Maiden",
        album_count=21,
        track_count=213,
        total_duration_ms=71844745,
        avg_track_duration_ms=337299,
        revenue=138.6,
        units_sold=140,
        genres=("Blues", "Heavy Metal", "Metal", "Rock"),
    )


def test_artist_without_albums_has_zeros(stats_by_id):
    item = stats_by_id[25]
    assert (
        item.album_count,
        item.track_count,
        item.total_duration_ms,
        item.avg_track_duration_ms,
        item.revenue,
        item.units_sold,
        item.genres,
    ) == (0, 0, 0, 0, 0.0, 0, ())


def test_totals_match_source_tables(connection, stats_by_id):
    """Totals equal the raw tables, so no join inflated any count."""
    rows = stats_by_id.values()
    (albums,) = connection.execute("SELECT COUNT(*) FROM Album").fetchone()
    (tracks, total_ms) = connection.execute(
        "SELECT COUNT(*), SUM(Milliseconds) FROM Track WHERE AlbumId IS NOT NULL"
    ).fetchone()
    (units,) = connection.execute("SELECT SUM(Quantity) FROM InvoiceLine").fetchone()

    assert albums == 347
    assert sum(item.album_count for item in rows) == albums
    assert sum(item.track_count for item in rows) == tracks
    assert sum(item.total_duration_ms for item in rows) == total_ms
    assert sum(item.units_sold for item in rows) == units
    assert round(sum(item.revenue for item in rows), 2) == 2328.60


def test_revenue_has_at_most_two_decimals(stats_by_id):
    for item in stats_by_id.values():
        assert round(item.revenue, 2) == item.revenue


# Genres


def test_genres_are_sorted_distinct_and_exist(connection, stats_by_id):
    known = {name for (name,) in connection.execute("SELECT Name FROM Genre")}
    for item in stats_by_id.values():
        assert list(item.genres) == sorted(set(item.genres)), item.name
        assert set(item.genres) <= known


def test_only_artists_without_tracks_have_no_genres(stats_by_id):
    for item in stats_by_id.values():
        assert (item.genres == ()) == (item.track_count == 0), item.name


# Per-album detail


def test_albums_are_omitted_by_default(stats_by_id):
    assert all(item.albums is None for item in stats_by_id.values())


def test_album_detail_adds_up_to_artist_totals(stats_by_id, detailed_by_id):
    """For every artist, its albums sum exactly to the artist row."""
    for artist_id, item in detailed_by_id.items():
        albums = item.albums
        assert len(albums) == item.album_count
        assert sum(album.track_count for album in albums) == item.track_count
        assert sum(a.total_duration_ms for a in albums) == item.total_duration_ms
        assert sum(album.units_sold for album in albums) == item.units_sold
        assert round(sum(album.revenue for album in albums), 2) == item.revenue
        # The detail does not change the summary fields.
        summary = stats_by_id[artist_id]
        assert vars_of(item) == vars_of(summary)


def test_album_detail_for_acdc(detailed_by_id):
    assert [(a.album_id, a.title, a.track_count) for a in detailed_by_id[1].albums] == [
        (1, "For Those About To Rock We Salute You", 10),
        (4, "Let There Be Rock", 8),
    ]


def test_album_detail_sorted_by_title(detailed_by_id):
    for item in detailed_by_id.values():
        titles = [album.title for album in item.albums]
        assert titles == sorted(titles), item.name


def test_album_detail_empty_for_artist_without_albums(detailed_by_id):
    assert detailed_by_id[25].albums == ()


# Sorting and filtering


def test_default_sort_is_revenue_desc_with_id_tiebreak(connection):
    stats = get_artist_stats(connection)
    assert stats[0].artist_id == 90
    keys = [(-item.revenue, item.artist_id) for item in stats]
    assert keys == sorted(keys)


def test_top_three_by_revenue(connection):
    assert [item.artist_id for item in get_artist_stats(connection, top=3)] == [
        90,
        150,
        50,
    ]


def test_top_with_detail_only_loads_selected_artists(connection):
    stats = get_artist_stats(connection, top=2, include_albums=True)
    assert [item.artist_id for item in stats] == [90, 150]
    assert [len(item.albums) for item in stats] == [21, 10]


def test_sort_by_name_is_case_insensitive(connection):
    def ascii_casefold(name: str) -> str:
        return "".join(char.lower() if char.isascii() else char for char in name)

    names = [item.name for item in get_artist_stats(connection, sort_by="name")]
    assert names == sorted(names, key=ascii_casefold)
    assert names.index("Aaron Copland & London Symphony Orchestra") < names.index(
        "AC/DC"
    )


@pytest.mark.parametrize("sort_by", ["album_count", "track_count", "units_sold"])
def test_numeric_sorts_are_descending(connection, sort_by):
    values = [
        getattr(item, sort_by) for item in get_artist_stats(connection, sort_by=sort_by)
    ]
    assert values == sorted(values, reverse=True)


def test_filter_by_artist_id(connection):
    stats = get_artist_stats(connection, artist_id=1)
    assert [item.name for item in stats] == ["AC/DC"]


def test_unknown_artist_returns_empty_list(connection):
    assert get_artist_stats(connection, artist_id=999999) == []
    assert get_artist_stats(connection, artist_id=999999, include_albums=True) == []


def test_invalid_sort_by_raises(connection):
    with pytest.raises(ValueError, match="sort_by"):
        get_artist_stats(connection, sort_by="bogus")


def test_invalid_top_raises(connection):
    with pytest.raises(ValueError, match="top"):
        get_artist_stats(connection, top=0)


# Search by name


@pytest.mark.parametrize(
    ("name", "expected_id"),
    [
        ("AC/DC", 1),
        ("ac/dc", 1),
        ("  Iron Maiden  ", 90),
        ("ANTÔNIO CARLOS JOBIM", 6),  # SQLite LOWER/NOCASE would miss this one
    ],
)
def test_find_artist_id_ignores_case_and_accents_case(connection, name, expected_id):
    assert find_artist_id(connection, name) == expected_id


@pytest.mark.parametrize("name", ["Iron", "Nobody", "", "   "])
def test_find_artist_id_requires_full_match(connection, name):
    assert find_artist_id(connection, name) is None


# CLI


def test_cli_json_to_stdout(capsys):
    assert reporter.main(["--format", "json", "--top", "2"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert [row["artist_id"] for row in data] == [90, 150]
    assert list(data[0]) == list(reporter.FIELDS)
    assert data[0]["genres"] == ["Blues", "Heavy Metal", "Metal", "Rock"]


def test_cli_csv_to_file(tmp_path):
    output = tmp_path / "artists.csv"
    assert reporter.main(["--format", "csv", "--output", str(output)]) == 0
    with output.open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert len(rows) == 275
    assert rows[0]["name"] == "Iron Maiden"
    assert rows[0]["revenue"] == "138.60"
    assert rows[0]["genres"] == "Blues; Heavy Metal; Metal; Rock"


def test_cli_search_by_name(capsys):
    assert reporter.main(["--format", "json", "--artist", "iron maiden"]) == 0
    (row,) = json.loads(capsys.readouterr().out)
    assert row["artist_id"] == 90


def test_cli_unknown_artist_name_exits_1(capsys):
    assert reporter.main(["--format", "json", "--artist", "Nobody"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: no se encontró el artista 'Nobody'\n"


def test_cli_json_detail_nests_albums(capsys):
    assert reporter.main(["--format", "json", "--artist-id", "1", "--detail"]) == 0
    (row,) = json.loads(capsys.readouterr().out)
    assert [album["title"] for album in row["albums"]] == [
        "For Those About To Rock We Salute You",
        "Let There Be Rock",
    ]


def test_cli_csv_detail_has_one_row_per_album(tmp_path):
    output = tmp_path / "albums.csv"
    assert reporter.main(["--format", "csv", "--detail", "--output", str(output)]) == 0
    with output.open(encoding="utf-8", newline="") as file:
        reader = csv.DictReader(file)
        rows = list(reader)
    assert tuple(reader.fieldnames) == reporter.ALBUM_FIELDS
    assert len(rows) == 347
    assert {row["album_id"] for row in rows} == {str(i) for i in range(1, 348)}


def test_cli_unknown_artist_exits_1(capsys):
    assert reporter.main(["--format", "json", "--artist-id", "999999"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: no se encontró el artista con ID 999999\n"


@pytest.mark.parametrize(
    "argv",
    [
        ["--format", "xml"],
        ["--format", "json", "--sort-by", "bogus"],
        ["--format", "json", "--top", "0"],
        ["--format", "json", "--artist-id", "-1"],
        ["--format", "json", "--top", "abc"],
        ["--format", "json", "--artist-id", "1", "--artist", "AC/DC"],
        [],
    ],
)
def test_cli_invalid_arguments_exit_2(argv, capsys):
    with pytest.raises(SystemExit) as excinfo:
        reporter.main(argv)
    assert excinfo.value.code == 2


def test_cli_explicit_db_path(capsys):
    argv = ["--format", "json", "--top", "1", "--db", str(CHINOOK_DB_PATH)]
    assert reporter.main(argv) == 0
    assert json.loads(capsys.readouterr().out)[0]["artist_id"] == 90


def test_cli_missing_database_exits_1(tmp_path, capsys):
    missing = tmp_path / "missing.db"
    assert reporter.main(["--format", "json", "--db", str(missing)]) == 1
    assert "no se pudo abrir la base de datos" in capsys.readouterr().err
    assert not missing.exists()  # read-only mode never creates the file


def test_cli_corrupt_database_exits_1(tmp_path, capsys):
    corrupt = tmp_path / "corrupt.db"
    corrupt.write_bytes(b"this is not a sqlite database" * 100)
    assert reporter.main(["--format", "json", "--db", str(corrupt)]) == 1
    err = capsys.readouterr().err
    assert "no se pudo abrir la base de datos" in err
    assert "no es una base Chinook" not in err


def test_cli_creates_missing_output_directories(tmp_path):
    output = tmp_path / "reports" / "2026" / "artists.json"
    assert reporter.main(["--format", "json", "--output", str(output)]) == 0
    assert len(json.loads(output.read_text(encoding="utf-8"))) == 275


def test_cli_output_is_a_directory_exits_1(tmp_path, capsys):
    assert reporter.main(["--format", "json", "--output", str(tmp_path)]) == 1
    assert "no se pudo escribir" in capsys.readouterr().err


def test_cli_output_parent_is_a_file_exits_1(tmp_path, capsys):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")
    output = blocker / "artists.json"
    assert reporter.main(["--format", "json", "--output", str(output)]) == 1
    assert "no se pudo escribir" in capsys.readouterr().err


def vars_of(item: ArtistStats) -> dict:
    """Summary field values of an ArtistStats (slots dataclasses have no __dict__)."""
    return {name: getattr(item, name) for name in reporter.FIELDS}


def test_real_chinook_db_passes_schema_validation(connection):
    validate_schema(connection)


def test_cli_empty_sqlite_file_is_not_chinook(tmp_path, capsys):
    """A zero-byte file is a valid, empty SQLite database for SQLite."""
    empty = tmp_path / "empty.db"
    empty.touch()
    assert reporter.main(["--format", "json", "--db", str(empty)]) == 1
    assert "no es una base Chinook válida" in capsys.readouterr().err


# Partial search


@pytest.mark.parametrize(
    ("text", "expected_ids"),
    [
        ("jobim", [6]),
        ("JOBIM", [6]),
        ("  Iron Maiden  ", [90]),
        ("NAÇÃO", [18, 191]),  # non-ASCII folding: both "... Nação Zumbi" artists
    ],
)
def test_find_artist_ids_containing(connection, text, expected_ids):
    assert find_artist_ids_containing(connection, text) == expected_ids


def test_find_artist_ids_containing_returns_every_match_in_id_order(connection):
    ids = find_artist_ids_containing(connection, "orchestra")
    names = {
        artist_id: name
        for artist_id, name in connection.execute("SELECT ArtistId, Name FROM Artist")
    }
    expected = sorted(i for i, name in names.items() if "orchestra" in name.casefold())
    assert len(expected) > 5
    assert ids == expected


@pytest.mark.parametrize("text", ["", "   ", "zzz-no-artist", "/-/", "' & '"])
def test_find_artist_ids_containing_no_match(connection, text):
    assert find_artist_ids_containing(connection, text) == []


@pytest.mark.parametrize(
    ("text", "expected_names"),
    [
        ("acdc", ["AC/DC"]),  # punctuation ignored
        ("AC-DC", ["AC/DC"]),
        ("guns n roses", ["Guns N' Roses"]),  # spaces and apostrophe ignored
        ("gunsnroses", ["Guns N' Roses"]),
        ("antonio carlos", ["Antônio Carlos Jobim"]),  # accents ignored
        ("nacao", ["Chico Science & Nação Zumbi", "Nação Zumbi"]),
    ],
)
def test_artist_contains_ignores_accents_spaces_and_punctuation(
    connection, text, expected_names
):
    names = dict(connection.execute("SELECT ArtistId, Name FROM Artist"))
    ids = find_artist_ids_containing(connection, text)
    assert [names[artist_id] for artist_id in ids] == expected_names


@pytest.mark.parametrize("name", ["acdc", "AC-DC", "antonio carlos jobim"])
def test_exact_search_is_not_normalized(connection, name):
    """--artist keeps requiring the name as written, apart from case."""
    assert find_artist_id(connection, name) is None


def test_cli_artist_contains_normalized(capsys):
    assert reporter.main(["--format", "json", "--artist-contains", "acdc"]) == 0
    assert [row["name"] for row in json.loads(capsys.readouterr().out)] == ["AC/DC"]


def test_cli_artist_exact_is_not_normalized(capsys):
    assert reporter.main(["--format", "json", "--artist", "acdc"]) == 1
    assert capsys.readouterr().err == "error: no se encontró el artista 'acdc'\n"


def test_get_artist_stats_filters_by_several_ids(connection):
    stats = get_artist_stats(connection, artist_ids=[1, 90, 999999])
    assert [item.artist_id for item in stats] == [90, 1]  # sorted by revenue


def test_get_artist_stats_top_applies_after_the_id_filter(connection):
    stats = get_artist_stats(connection, artist_ids=[1, 50, 90, 150], top=2)
    assert [item.artist_id for item in stats] == [90, 150]


def test_get_artist_stats_empty_id_list_returns_empty(connection):
    assert get_artist_stats(connection, artist_ids=[]) == []


def test_get_artist_stats_rejects_artist_id_and_artist_ids(connection):
    with pytest.raises(ValueError, match="artist_id"):
        get_artist_stats(connection, artist_id=1, artist_ids=[1])


def test_cli_artist_contains_returns_all_matches(capsys):
    assert reporter.main(["--format", "json", "--artist-contains", "iron"]) == 0
    names = [row["name"] for row in json.loads(capsys.readouterr().out)]
    assert "Iron Maiden" in names
    assert all("iron" in name.casefold() for name in names)


def test_cli_artist_contains_with_sort_and_top(capsys):
    argv = ["--format", "json", "--artist-contains", "a", "--sort-by", "name"]
    assert reporter.main([*argv, "--top", "3"]) == 0
    names = [row["name"] for row in json.loads(capsys.readouterr().out)]
    assert len(names) == 3
    assert names == sorted(names, key=str.casefold)


def test_cli_artist_contains_without_matches_exits_1(capsys):
    assert reporter.main(["--format", "json", "--artist-contains", "zzz"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "error: ningún artista contiene 'zzz' en el nombre\n"


# Spanish error messages


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (
            ["--format", "xml"],
            "error: argumento --format: valor inválido: 'xml' (opciones: json, csv)",
        ),
        (
            ["--format", "json", "--top", "abc"],
            "error: argumento --top: 'abc' no es un número entero",
        ),
        (
            ["--format", "json", "--top", "0"],
            "error: argumento --top: '0' debe ser mayor o igual que 1",
        ),
        (["--format", "json", "--top"], "error: argumento --top: se esperaba un valor"),
        (
            ["--format", "json", "--artist-contains", " "],
            "error: argumento --artist-contains: el texto de búsqueda no puede estar vacío",
        ),
        (
            ["--format", "json", "--artist-contains", "/-/"],
            (
                "error: argumento --artist-contains: '/-/' debe contener al menos"
                " una letra o un número"
            ),
        ),
        (
            ["--format", "json", "--artist-id", "1", "--artist", "AC/DC"],
            "error: argumento --artist: no se puede combinar con --artist-id",
        ),
        ([], "error: faltan argumentos obligatorios: --format"),
        (["--format", "json", "--bogus"], "error: argumentos no reconocidos: --bogus"),
    ],
)
def test_cli_usage_errors_are_in_spanish(argv, expected, capsys):
    with pytest.raises(SystemExit) as excinfo:
        reporter.main(argv)
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert err.startswith("uso: ")
    assert err.rstrip("\n").splitlines()[-1] == expected


def test_untranslated_argparse_messages_are_kept():
    assert reporter._translate_argparse_message("something new") == "something new"
    assert (
        reporter._translate_argparse_message("argument --x: something new")
        == "argumento --x: something new"
    )


# JSON layout and round trip


def test_cli_json_uses_two_space_indent_and_final_newline(capsys):
    assert reporter.main(["--format", "json", "--top", "2", "--detail"]) == 0
    out = capsys.readouterr().out
    assert out == json.dumps(json.loads(out), ensure_ascii=False, indent=2) + "\n"
    lines = out.splitlines()
    assert lines[0] == "["
    assert lines[1] == "  {"
    assert lines[2].startswith('    "artist_id": ')


@pytest.mark.parametrize("detail", [False, True])
def test_cli_json_round_trips_to_the_same_stats(connection, capsys, detail):
    """The whole JSON output equals the dataclasses it was built from."""
    stats = get_artist_stats(connection, include_albums=detail)
    expected = []
    for item in stats:
        row = asdict(item)
        if not detail:
            del row["albums"]
        expected.append(row)
    # Tuples become JSON lists; normalize the expected side the same way.
    expected = json.loads(json.dumps(expected))

    argv = ["--format", "json", *(["--detail"] if detail else [])]
    assert reporter.main(argv) == 0
    assert json.loads(capsys.readouterr().out) == expected


# Output file handling


def test_cli_overwrites_existing_output_file(tmp_path):
    output = tmp_path / "artists.json"
    assert reporter.main(["--format", "json", "--output", str(output)]) == 0
    assert len(json.loads(output.read_text(encoding="utf-8"))) == 275

    argv = ["--format", "json", "--top", "1", "--output", str(output)]
    assert reporter.main(argv) == 0
    data = json.loads(output.read_text(encoding="utf-8"))  # no leftovers from run 1
    assert [row["artist_id"] for row in data] == [90]


@pytest.fixture
def db_without_chinook_schema(tmp_path):
    path = tmp_path / "other.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE Unrelated (x)")
    return path


@pytest.mark.parametrize(
    "extra_argv",
    [
        ["--artist-id", "999999"],
        ["--artist", "Nobody"],
        ["--artist-contains", "zzz"],
        ["--db", "{missing_db}"],
        ["--db", "{bad_schema_db}"],
    ],
)
def test_cli_error_leaves_no_output_file(
    tmp_path, db_without_chinook_schema, capsys, extra_argv
):
    output = tmp_path / "reports" / "artists.json"
    replacements = {
        "{missing_db}": str(tmp_path / "missing.db"),
        "{bad_schema_db}": str(db_without_chinook_schema),
    }
    extra_argv = [replacements.get(arg, arg) for arg in extra_argv]

    argv = ["--format", "json", "--output", str(output), *extra_argv]
    assert reporter.main(argv) == 1
    assert capsys.readouterr().err.startswith("error: ")
    assert not output.exists()
    assert not output.parent.exists()  # directories are only created on success


needs_permissions = pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0,
    reason="POSIX permissions are not enforced on Windows or for root",
)


@needs_permissions
def test_cli_read_only_output_file_exits_1(tmp_path, capsys):
    output = tmp_path / "artists.json"
    output.write_text("previous report", encoding="utf-8")
    output.chmod(0o444)
    try:
        assert reporter.main(["--format", "json", "--output", str(output)]) == 1
        assert "no se pudo escribir" in capsys.readouterr().err
        assert output.read_text(encoding="utf-8") == "previous report"
    finally:
        output.chmod(0o644)


@needs_permissions
def test_cli_read_only_output_directory_exits_1(tmp_path, capsys):
    directory = tmp_path / "locked"
    directory.mkdir()
    directory.chmod(0o555)
    try:
        output = directory / "artists.json"
        assert reporter.main(["--format", "json", "--output", str(output)]) == 1
        assert "no se pudo escribir" in capsys.readouterr().err
        assert not output.exists()
    finally:
        directory.chmod(0o755)


# Connection lifecycle in main()


@pytest.fixture
def opened_connections(monkeypatch):
    """Spy on reporter.get_db_connection; the real function still opens the db."""
    opened = []
    real = reporter.get_db_connection

    def spy(path=None):
        connection = real(path)
        opened.append(connection)
        return connection

    monkeypatch.setattr(reporter, "get_db_connection", spy)
    return opened


def assert_closed(connection: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


@pytest.mark.parametrize(
    ("extra_argv", "exit_code"),
    [
        (["--top", "1"], 0),
        (["--artist-id", "999999"], 1),
        (["--artist", "Nobody"], 1),
        (["--artist-contains", "zzz"], 1),
        (["--db", "{bad_schema_db}"], 1),
    ],
)
def test_cli_closes_the_connection(
    opened_connections, db_without_chinook_schema, capsys, extra_argv, exit_code
):
    extra_argv = [
        str(db_without_chinook_schema) if arg == "{bad_schema_db}" else arg
        for arg in extra_argv
    ]
    assert reporter.main(["--format", "json", *extra_argv]) == exit_code
    (connection,) = opened_connections
    assert_closed(connection)
