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


def test_centre_charges_before_any_connection_fires():
    """The grid wakes, then the centre charges, then it fires — in order."""
    frames = [frame.plain for frame in logo_frames()]

    first_charged = next(
        index for index, frame in enumerate(frames) if "O" in frame or "●" in frame
    )
    first_fired = next(
        index for index, frame in enumerate(frames) if "\\" in frame or "/" in frame
    )

    assert first_charged < first_fired
    # Once charged, the centre stays charged for the rest of the animation.
    assert all("O" in frame or "●" in frame for frame in frames[first_charged:])


def test_nodes_flicker_through_other_glyphs_while_waking():
    """The wake-up is a glyph churn, not just a fade."""
    waking = {"·", "∘", "◦", "*", "+", "."}
    frames = [frame.plain for frame in logo_frames()]

    assert any(waking & set(frame) for frame in frames), (
        "no frame used the waking glyphs, so nothing visibly changes"
    )


def test_animation_is_deterministic():
    """A seeded animation means every launch looks the same."""
    assert [f.plain for f in logo_frames()] == [f.plain for f in logo_frames()]
