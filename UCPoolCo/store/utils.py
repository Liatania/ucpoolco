from math import radians, sin, cos, sqrt, atan2

def haversine_miles(lat1, lon1, lat2, lon2):
    """
    Calculate distance in miles between two lat/lon coordinates.
    """
    R = 3958.8  # Radius of Earth in miles

    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)

    lat1 = radians(lat1)
    lat2 = radians(lat2)

    a = (
        sin(d_lat / 2) ** 2
        + cos(lat1) * cos(lat2) * sin(d_lon / 2) ** 2
    )
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R * c

