# SPDX-FileCopyrightText: Copyright 2026 GlobalFoundries PDK Authors
# SPDX-License-Identifier: Apache License 2.0
"""Dummy metal fill must respect the matching datatype-5 blockage.

Requires pytest, the klayout Python package and the KLayout executable.
Run from the repository root with KLayout on PATH:
    make test-fill

The fill_testing job in .github/workflows/pcells_regression.yml runs the
same target on pull requests and pushes, using KLayout 0.30.12.

The manual's layer table defines Metal1_BLK through Metal5_BLK as
34/5, 36/5, 42/5, 46/5 and 81/5. Each case blocks one metal over the
left half of a 200 um layout. Other metals must retain their control fill,
and the blocked metal must still fill the right half. Existing wires and
dummy metal inside the blockage must remain unchanged.

Both fill branches are covered, with and without *_ignore_active, and
blockages are drawn directly or in a rotated and translated child cell.
"""

import subprocess
from pathlib import Path

import klayout.db as db
import pytest


METALS = (34, 36, 42, 46, 81)
BLOCKED = db.Box(0, 0, 100150, 200000)


def region(layout: db.Layout, metal: int, datatype: int) -> db.Region:
    """Read top's recursive shapes, allowing unrelated unused fill cells."""
    return db.Region(
        layout.cell("top").begin_shapes_rec(layout.layer(metal, datatype))
    )


def fill(
    directory: Path,
    blocked_metal: int | None,
    hierarchical: bool,
    ignore_active: bool,
) -> tuple[db.Layout, db.Layout]:
    """Run the real fill entry point over a layout with existing metal."""
    layout = db.Layout()
    layout.dbu = 0.001
    top = layout.create_cell("top")
    for x, y in ((0, 0), (199000, 0), (0, 199000), (199000, 199000)):
        top.shapes(layout.layer(34, 0)).insert(db.Box(x, y, x + 1000, y + 1000))
    # Exclude FEOL fill so the comparison isolates metal fill.
    top.shapes(layout.layer(111, 5)).insert(db.Box(0, 0, 200000, 200000))
    for metal in METALS:
        top.shapes(layout.layer(metal, 0)).insert(db.Box(20000, 20000, 22000, 40000))
        top.shapes(layout.layer(metal, 4)).insert(db.Box(10000, 10000, 12000, 12000))
    if blocked_metal is not None:
        blockage = layout.layer(blocked_metal, 5)
        if hierarchical:
            child = layout.create_cell("macro")
            child.shapes(blockage).insert(db.Box(0, 0, 200000, 100150))
            top.insert(db.CellInstArray(
                child.cell_index(), db.Trans(db.Trans.R90, 100150, 0)
            ))
        else:
            top.shapes(blockage).insert(BLOCKED)
    source, output = directory / "input.gds", directory / "filled.gds"
    layout.write(str(source))
    script = Path(__file__).resolve().parents[1] / "fill_all.rb"
    command = [
        "klayout", "-b", "-r", str(script),
        "-rd", f"input={source}", "-rd", f"output={output}",
        "-rd", "threads=1", "-rd", "no_scribe_line=true",
    ]
    if ignore_active:
        for index in range(1, 6):
            command += ["-rd", f"Metal{index}_ignore_active=true"]
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    filled = db.Layout()
    filled.read(str(output))
    return layout, filled


@pytest.fixture(
    scope="module", params=[False, True], ids=["normal", "ignore-active"]
)
def control(
    request: pytest.FixtureRequest,
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[bool, dict[int, db.Region]]:
    """No-blockage controls must produce fresh dummy metal on all layers."""
    ignore_active = request.param
    source, filled = fill(
        tmp_path_factory.mktemp("control"), None, False, ignore_active
    )
    generated = {}
    for metal in METALS:
        generated[metal] = region(filled, metal, 4) - region(source, metal, 4)
        assert not (generated[metal] & db.Region(BLOCKED)).is_empty()
    return ignore_active, generated


@pytest.mark.parametrize("metal", METALS)
@pytest.mark.parametrize("hierarchical", [False, True], ids=["flat", "child"])
def test_metal_blockage(
    tmp_path: Path,
    metal: int,
    hierarchical: bool,
    control: tuple[bool, dict[int, db.Region]],
) -> None:
    ignore_active, expected = control
    source, filled = fill(tmp_path, metal, hierarchical, ignore_active)
    for layer in METALS:
        original = region(source, layer, 4)
        actual = region(filled, layer, 4)
        assert (original - actual).is_empty(), "Existing fill was removed"
        assert (region(source, layer, 0) ^ region(filled, layer, 0)).is_empty()
        assert (region(source, layer, 5) ^ region(filled, layer, 5)).is_empty()
        generated = actual - original
        assert not (generated & db.Region(db.Box(120000, 0, 200000, 200000))).is_empty()
        if layer == metal:
            assert (generated & db.Region(BLOCKED)).is_empty(), (
                f"New dummy metal on {metal}/4 overlaps its {metal}/5 blockage"
            )
        else:
            assert (generated ^ expected[layer]).is_empty(), (
                f"A {metal}/5 blockage changed fill on metal {layer}"
            )
