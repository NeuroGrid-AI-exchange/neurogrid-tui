from nrgrd.widgets.logo import create_logo, logo_frames


def test_final_frame_matches_create_logo():
    """The animation must settle on exactly the static logo."""
    assert logo_frames()[-1].plain == create_logo().plain


def test_logo_rows_are_aligned():
    rows = create_logo().plain.split("\n")

    assert len(rows) == 7
    # Every row places the emblem at the same column.
    emblem_starts = {row.index("o") for row in rows if "o" in row}
    assert len(emblem_starts) == 1


def test_animation_reveals_connections_progressively():
    frames = logo_frames()
    connection_counts = [
        sum(frame.plain.count(glyph) for glyph in ("\\", "/", "-"))
        for frame in frames
    ]

    assert connection_counts[0] == 0, "the first frame shows bare nodes"
    assert connection_counts == sorted(connection_counts), "connections only appear"
    assert connection_counts[-1] > connection_counts[0]


def test_centre_node_charges_before_firing():
    frames = logo_frames()

    assert "O" not in frames[0].plain
    assert all("O" in frame.plain for frame in frames[1:])
