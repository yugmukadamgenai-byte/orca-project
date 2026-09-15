"""SAR search-zone generation for ORCA."""

from shapely.geometry import Point


def create_search_zone(latitude, longitude, radius_km):
    """Create an approximate circular search zone around a predicted position."""

    latitude_km = 111.0
    longitude_km = 111.0 * __import__("math").cos(
        __import__("math").radians(latitude)
    )

    radius_lat = radius_km / latitude_km
    radius_lon = radius_km / longitude_km

    point = Point(longitude, latitude)

    zone = Point(
        point.x / radius_lon,
        point.y / radius_lat,
    ).buffer(1.0, resolution=32)

    coordinates = [
        [
            (
                round(x * radius_lon, 6),
                round(y * radius_lat, 6),
            )
            for x, y in zone.exterior.coords
        ]
    ]

    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": coordinates,
        },
        "properties": {
            "radius_km": radius_km,
        },
    }
