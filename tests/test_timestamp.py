"""
Unit tests per rt.core.timestamp
"""

import pytest
from rt.core.timestamp import parse_timestamp, format_timestamp, parse_interval, validate_interval


def test_parse_timestamp_mm_ss():
    assert parse_timestamp("00:14") == 14.0
    assert parse_timestamp("02:30") == 150.0
    assert parse_timestamp("59:59") == 3599.0
    assert parse_timestamp("*00:14*") == 14.0


def test_parse_timestamp_h_mm_ss():
    assert parse_timestamp("01:14:59") == 4499.0
    assert parse_timestamp("1:00:00") == 3600.0
    assert parse_timestamp("2:15:30") == 8130.0


def test_parse_timestamp_with_milliseconds():
    assert parse_timestamp("00:02.720") == 2.72
    assert parse_timestamp("01:00:05.500") == 3605.5


def test_parse_timestamp_invalid():
    with pytest.raises(ValueError):
        parse_timestamp("")
    with pytest.raises(ValueError):
        parse_timestamp("invalid")
    with pytest.raises(ValueError):
        parse_timestamp("00:65")
    with pytest.raises(ValueError):
        parse_timestamp("-01:10")
    with pytest.raises(ValueError):
        parse_timestamp("1:2:3:4")


def test_format_timestamp():
    assert format_timestamp(14.0) == "00:14"
    assert format_timestamp(150.0) == "02:30"
    assert format_timestamp(3599.0) == "59:59"
    assert format_timestamp(3600.0) == "1:00:00"
    assert format_timestamp(4499.0) == "1:14:59"
    assert format_timestamp(4499.0, include_hours_always=True) == "01:14:59"


def test_format_timestamp_negative():
    with pytest.raises(ValueError):
        format_timestamp(-5.0)


def test_parse_interval():
    start, end = parse_interval("00:02-00:12")
    assert start == 2.0
    assert end == 12.0

    start, end = parse_interval("01:14:00 - 01:15:30")
    assert start == 4440.0
    assert end == 4530.0

    start, end = parse_interval("*00:02-00:06*")
    assert start == 2.0
    assert end == 6.0


def test_parse_interval_invalid():
    # start >= end
    with pytest.raises(ValueError):
        parse_interval("00:12-00:02")
    with pytest.raises(ValueError):
        parse_interval("00:10-00:10")
    with pytest.raises(ValueError):
        parse_interval("invalid-interval")
