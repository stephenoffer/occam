from decimal import Decimal

POINT_VALUE = Decimal("0.01")


def points_value(points):
    return points * POINT_VALUE
