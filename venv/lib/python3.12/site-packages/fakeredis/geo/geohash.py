#  Note: the alphabet in geohash differs from the common base32
#  alphabet described in IETF's RFC 4648
#  (http://tools.ietf.org/html/rfc4648)
from typing import Tuple

base32 = "0123456789bcdefghjkmnpqrstuvwxyz"
decodemap = {base32[i]: i for i in range(len(base32))}


def geo_decode(geohash: str) -> Tuple[float, float, float, float]:
    """
    Decode the geohash to its exact values, including the error margins of the result.  Returns four float values:
    latitude, longitude, the plus/minus error for latitude (as a positive number) and the plus/minus error for longitude
    (as a positive number).
    """
    lat_interval, lon_interval = (-90.0, 90.0), (-180.0, 180.0)
    lat_err, lon_err = 90.0, 180.0
    is_longitude = True
    for c in geohash:
        cd = decodemap[c]
        for mask in [16, 8, 4, 2, 1]:
            if is_longitude:  # adds longitude info
                lon_err /= 2
                if cd & mask:
                    lon_interval = (
                        (lon_interval[0] + lon_interval[1]) / 2,
                        lon_interval[1],
                    )
                else:
                    lon_interval = (
                        lon_interval[0],
                        (lon_interval[0] + lon_interval[1]) / 2,
                    )
            else:  # adds latitude info
                lat_err /= 2
                if cd & mask:
                    lat_interval = (
                        (lat_interval[0] + lat_interval[1]) / 2,
                        lat_interval[1],
                    )
                else:
                    lat_interval = (
                        lat_interval[0],
                        (lat_interval[0] + lat_interval[1]) / 2,
                    )
            is_longitude = not is_longitude
    lat = (lat_interval[0] + lat_interval[1]) / 2
    lon = (lon_interval[0] + lon_interval[1]) / 2
    return lat, lon, lat_err, lon_err


def geo_encode(latitude: float, longitude: float, precision: int = 12) -> str:
    """
    Encode a position given in float arguments latitude, longitude to a geohash which will have the character count
    precision.
    """
    lat_interval, lon_interval = (-90.0, 90.0), (-180.0, 180.0)
    geohash, bits = [], [16, 8, 4, 2, 1]  # type: ignore
    bit, ch = 0, 0
    is_longitude = True

    def next_interval(curr: float, interval: Tuple[float, float], ch: int) -> Tuple[Tuple[float, float], int]:
        mid = (interval[0] + interval[1]) / 2
        if curr > mid:
            ch |= bits[bit]
            return (mid, interval[1]), ch
        else:
            return (interval[0], mid), ch

    while len(geohash) < precision:
        if is_longitude:
            lon_interval, ch = next_interval(longitude, lon_interval, ch)
        else:
            lat_interval, ch = next_interval(latitude, lat_interval, ch)
        is_longitude = not is_longitude
        if bit < 4:
            bit += 1
        else:
            geohash += base32[ch]
            bit = 0
            ch = 0
    return "".join(geohash)
