"""Shared simulator action space; these discrete menus are modeling choices."""

from typing import Literal

RATE_ACTIONS_BPS = (-50, -25, 0, 25, 35, 40, 50)
STANCE_ACTIONS = ("withdrawal_of_accommodation", "neutral", "accommodative")
RateActionBps = Literal[-50, -25, 0, 25, 35, 40, 50]
StanceType = Literal["withdrawal_of_accommodation", "neutral", "accommodative"]


def validate_rate_action(value: object) -> int:
    """Reject coercion, nonfinite values, booleans and actions outside the menu."""
    if type(value) is not int or value not in RATE_ACTIONS_BPS:
        raise ValueError(f"Rate action must be an integer in {RATE_ACTIONS_BPS}; received {value!r}")
    return value
