from app.config import SODERMANLAND, Region
from app.services.grid import clamp_resolution_for_max_cells, generate_grid


def test_generate_grid_covers_bounding_box():
    points = generate_grid(SODERMANLAND, resolution_deg=0.1)

    assert points
    lats = [lat for lat, _ in points]
    lons = [lon for _, lon in points]

    assert min(lats) >= SODERMANLAND.min_lat
    assert max(lats) <= SODERMANLAND.max_lat + 0.1
    assert min(lons) >= SODERMANLAND.min_lon
    assert max(lons) <= SODERMANLAND.max_lon + 0.1


def test_generate_grid_resolution_affects_density():
    coarse = generate_grid(SODERMANLAND, resolution_deg=0.2)
    fine = generate_grid(SODERMANLAND, resolution_deg=0.05)

    assert len(fine) > len(coarse)


def test_clamp_resolution_for_max_cells_keeps_fine_resolution_for_small_bbox():
    small_region = Region(name="liten yta", min_lat=59.0, max_lat=59.05, min_lon=17.0, max_lon=17.05)
    resolution = clamp_resolution_for_max_cells(small_region, resolution_deg=0.004, max_cells=1200)

    assert resolution == 0.004


def test_clamp_resolution_for_max_cells_coarsens_for_large_bbox():
    huge_region = Region(name="jättestor yta", min_lat=55.0, max_lat=69.0, min_lon=11.0, max_lon=24.0)
    resolution = clamp_resolution_for_max_cells(huge_region, resolution_deg=0.004, max_cells=1200)

    points = generate_grid(huge_region, resolution)
    assert resolution > 0.004
    assert len(points) <= 1200
