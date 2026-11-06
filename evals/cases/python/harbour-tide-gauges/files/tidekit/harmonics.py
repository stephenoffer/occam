"""Predicted levels from tidal constituents."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Constituent:
    """One harmonic component of a station's tide.

    Attributes
    ----------
    name : str
        Standard constituent name, such as ``"M2"``.
    speed_deg_per_h : float
        Angular speed in degrees per hour.
    amplitude_m : float
        Amplitude at the station, in metres.
    phase_deg : float
        Phase lag at the station, in degrees.
    """

    name: str
    speed_deg_per_h: float
    amplitude_m: float
    phase_deg: float


def predict_level_m(
    constituents: Sequence[Constituent], hours: float, mean_level_m: float = 0.0
) -> float:
    """Predict a station's level by summing its constituents.

    Parameters
    ----------
    constituents : Sequence[Constituent]
        The station's constituents.
    hours : float
        Hours since the station's reference time.
    mean_level_m : float, optional
        Mean water level the tide oscillates around.

    Returns
    -------
    float
        Predicted level, in metres.

    Examples
    --------
    >>> m2 = Constituent("M2", 28.984, 1.2, 0.0)
    >>> predict_level_m([m2], 0.0, mean_level_m=2.0)
    3.2
    """
    return mean_level_m + sum(
        constituent.amplitude_m
        * math.cos(math.radians(constituent.speed_deg_per_h * hours - constituent.phase_deg))
        for constituent in constituents
    )


def principal_constituent(constituents: Sequence[Constituent]) -> Constituent:
    """Return the constituent with the largest amplitude.

    Parameters
    ----------
    constituents : Sequence[Constituent]
        The station's constituents.

    Returns
    -------
    Constituent
        The dominant constituent.

    Examples
    --------
    >>> m2 = Constituent("M2", 28.984, 1.2, 0.0)
    >>> s2 = Constituent("S2", 30.0, 0.3, 0.0)
    >>> principal_constituent([s2, m2]).name
    'M2'
    """
    return max(constituents, key=lambda constituent: constituent.amplitude_m)
