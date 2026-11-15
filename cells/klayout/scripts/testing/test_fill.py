# SPDX-FileCopyrightText: Copyright 2026 GlobalFoundries PDK Authors
# SPDX-License-Identifier: Apache License 2.0
"""Fill must preserve one top cell even when some fill patterns go unused.

Run from the repository root with KLayout on PATH:
    python -m pytest cells/klayout/scripts/testing/test_fill.py

The 4 um input retains the default scribe-line margin, leaving no room
for fill. The 200 um input omits that margin and has room for COMP and
upper-metal fill, but its solid Metal1 excludes Metal1 fill. Both include
an input subcell named COMP_fill_cell to exercise name collisions.
"""

import subprocess
from pathlib import Path

import klayout.db as db
import pytest


@pytest.mark.parametrize(
    "side,no_scribe_line", [(4, "false"), (200, "true")],
    ids=["no-fill", "mixed-fill"],
)
def test_fill_preserves_top_and_input(
    tmp_path: Path, side: int, no_scribe_line: str
) -> None:
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("top")
    child = layout.create_cell("COMP_fill_cell")
    metal1 = layout.layer(34, 0)
    child.shapes(metal1).insert(db.Box(0, 0, side * 1000, side * 1000))
    top.insert(db.CellInstArray(child.cell_index(), db.Trans()))
    source, output = tmp_path / "input.gds", tmp_path / "filled.gds"
    layout.write(str(source))
    script = Path(__file__).resolve().parents[1] / "fill_all.rb"
    result = subprocess.run(
        [
            "klayout", "-b", "-r", str(script),
            "-rd", f"input={source}",
            "-rd", f"output={output}",
            "-rd", "threads=1",
            "-rd", f"no_scribe_line={no_scribe_line}",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    filled = db.Layout()
    filled.read(str(output))
    assert [cell.name for cell in filled.top_cells()] == ["top"]
    filled_top = filled.top_cell()
    original = filled.cell("COMP_fill_cell")
    assert original is not None
    assert not original.is_top()
    expected = db.Region(top.begin_shapes_rec(metal1))
    actual = db.Region(filled_top.begin_shapes_rec(filled.layer(34, 0)))
    assert (expected ^ actual).is_empty()
    original_geometry = db.Region(original.shapes(filled.layer(34, 0)))
    assert (original_geometry ^ expected).is_empty()

    # The cleanup must retain instantiated patterns when fill is generated.
    comp_fill = db.Region(filled_top.begin_shapes_rec(filled.layer(22, 4)))
    metal_fill = db.Region(filled_top.begin_shapes_rec(filled.layer(42, 4)))
    assert comp_fill.is_empty() == (side == 4)
    assert metal_fill.is_empty() == (side == 4)
    assert db.Region(
        filled_top.begin_shapes_rec(filled.layer(34, 4))
    ).is_empty()
