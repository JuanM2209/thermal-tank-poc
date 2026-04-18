"""Unit tests for geometry conversions."""

from __future__ import annotations

import math

import pytest
from geometry import (
    FT3_PER_BBL,
    GAL_PER_FT3,
    Geometry,
    compute,
    footprint_ft2,
    ft3_to_bbl,
    ft3_to_gal,
    parse_geometry,
    volume_ft3_at_level,
)


@pytest.mark.unit
class TestGeometry:
    def test_vertical_cylinder_is_valid(self):
        g = Geometry(height_ft=22.0, diameter_ft=12.0)
        assert g.is_valid()

    def test_rectangular_requires_length_width(self):
        g = Geometry(
            height_ft=10.0, diameter_ft=0.0, shape="rectangular",
            length_ft=5.0, width_ft=3.0,
        )
        assert g.is_valid()
        bad = Geometry(height_ft=10.0, diameter_ft=0.0, shape="rectangular")
        assert not bad.is_valid()

    def test_zero_height_invalid(self):
        assert not Geometry(height_ft=0.0, diameter_ft=5.0).is_valid()

    def test_negative_height_invalid(self):
        assert not Geometry(height_ft=-1.0, diameter_ft=5.0).is_valid()


@pytest.mark.unit
class TestFootprint:
    def test_cylinder_footprint_matches_pi_r_squared(self):
        g = Geometry(height_ft=10.0, diameter_ft=10.0)
        assert math.isclose(footprint_ft2(g), math.pi * 25.0, rel_tol=1e-9)

    def test_rectangular_footprint(self):
        g = Geometry(
            height_ft=10.0, diameter_ft=0.0, shape="rectangular",
            length_ft=4.0, width_ft=3.0,
        )
        assert footprint_ft2(g) == 12.0


@pytest.mark.unit
class TestVolumeAtLevel:
    def test_full_volume_equals_height_times_footprint(self):
        g = Geometry(height_ft=22.0, diameter_ft=12.0)
        full = volume_ft3_at_level(g, 22.0)
        assert math.isclose(full, footprint_ft2(g) * 22.0, rel_tol=1e-9)

    def test_clamps_above_height(self):
        g = Geometry(height_ft=10.0, diameter_ft=10.0)
        assert volume_ft3_at_level(g, 25.0) == volume_ft3_at_level(g, 10.0)

    def test_clamps_below_zero(self):
        g = Geometry(height_ft=10.0, diameter_ft=10.0)
        assert volume_ft3_at_level(g, -5.0) == 0.0


@pytest.mark.unit
class TestUnitConversions:
    def test_ft3_to_bbl_roundtrip(self):
        bbl = ft3_to_bbl(FT3_PER_BBL)
        assert math.isclose(bbl, 1.0, rel_tol=1e-9)

    def test_ft3_to_gal_known_factor(self):
        assert math.isclose(ft3_to_gal(1.0), GAL_PER_FT3, rel_tol=1e-9)


@pytest.mark.unit
class TestCompute:
    def test_empty_tank(self):
        g = Geometry(height_ft=22.0, diameter_ft=12.0)
        r = compute(g, 0.0)
        assert r.level_ft == 0.0
        assert r.level_in == 0.0
        assert r.volume_bbl == 0.0
        assert r.ullage_ft == 22.0

    def test_half_full(self):
        g = Geometry(height_ft=20.0, diameter_ft=10.0)
        r = compute(g, 50.0)
        assert math.isclose(r.level_ft, 10.0, abs_tol=0.01)
        assert math.isclose(r.level_in, 120.0, abs_tol=0.1)
        assert math.isclose(r.ullage_ft, 10.0, abs_tol=0.01)
        expected_ft3 = math.pi * 25.0 * 10.0
        assert math.isclose(r.volume_bbl, expected_ft3 / FT3_PER_BBL, rel_tol=0.01)

    def test_full_tank(self):
        g = Geometry(height_ft=22.0, diameter_ft=12.0)
        r = compute(g, 100.0)
        assert math.isclose(r.level_ft, 22.0, abs_tol=0.01)
        assert r.ullage_ft == 0.0

    def test_percentage_clamped(self):
        g = Geometry(height_ft=10.0, diameter_ft=10.0)
        assert compute(g, 150.0).level_ft == compute(g, 100.0).level_ft
        assert compute(g, -10.0).level_ft == compute(g, 0.0).level_ft

    def test_inches_are_twelve_times_feet(self):
        g = Geometry(height_ft=20.0, diameter_ft=10.0)
        r = compute(g, 50.0)
        assert math.isclose(r.level_in, r.level_ft * 12.0, abs_tol=0.2)


@pytest.mark.unit
class TestParseGeometry:
    def test_parses_valid_dict(self):
        g = parse_geometry({"height_ft": 22, "diameter_ft": 12})
        assert g is not None
        assert g.height_ft == 22.0
        assert g.diameter_ft == 12.0

    def test_rejects_none(self):
        assert parse_geometry(None) is None

    def test_rejects_empty_dict(self):
        assert parse_geometry({}) is None

    def test_rejects_zero_diameter_cylinder(self):
        assert parse_geometry({"height_ft": 10, "diameter_ft": 0}) is None

    def test_rejects_bad_types(self):
        assert parse_geometry({"height_ft": "tall", "diameter_ft": 10}) is None

    def test_preserves_shape(self):
        g = parse_geometry({
            "height_ft": 10, "diameter_ft": 0, "shape": "rectangular",
            "length_ft": 4, "width_ft": 3,
        })
        assert g is not None
        assert g.shape == "rectangular"
