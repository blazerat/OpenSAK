# tests/unit-tests/test_geocoder_deps.py — real-dependency smoke test (no stubs).
# Catches dependency drift: if reverse_geocoder/pycountry are missing from the
# install, reverse-geocoding crashes only in shipped binaries — fail here instead.

from opensak.geocoder import fast_batch_geocode


def test_geocoding_libs_are_installed():
    import reverse_geocoder  # noqa: F401
    import pycountry  # noqa: F401


def test_fast_batch_geocode_real_lookup():
    # Offline KD-tree lookup over the bundled GeoNames data; near Copenhagen.
    (loc,) = fast_batch_geocode([(55.6, 12.5)])
    assert loc.country == "Denmark"
