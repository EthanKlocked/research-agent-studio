"""Deterministic coverage for the offline proxy test's accounting window."""
import pytest

from rpm_window import in_fresh_minute


def exercise(times, result=object(), error=None):
    clock = iter(times)
    calls = []

    def burst():
        calls.append("burst")
        if error:
            raise error
        return result

    value = in_fresh_minute(
        prepare=lambda: calls.append("prepare"),
        now=lambda: next(clock),
        sleep=lambda seconds: calls.append(("sleep", seconds)),
        burst=burst,
    )
    return value, calls


def test_waits_for_early_window_and_preserves_result():
    value, calls = exercise([119.5, 120.5, 122], result=[200] * 31)
    # Even an incorrect threshold result is returned, never silently retried.
    assert value == [200] * 31
    assert calls == ["prepare", ("sleep", 1.5), "burst"]


def test_retries_only_observed_rollover_with_fresh_counters():
    value, calls = exercise([120.5, 180.1, 181, 182], result="measured")
    assert value == "measured"
    assert calls == ["prepare", "burst", "prepare", "burst"]


def test_rollover_retries_are_bounded():
    with pytest.raises(AssertionError, match="crossed UTC minute"):
        exercise([120.5, 180.1, 180.5, 240.1])


def test_burst_failure_is_not_retried():
    with pytest.raises(AssertionError, match="real limiter failure"):
        exercise([120.5], error=AssertionError("real limiter failure"))


def test_wait_for_early_window_is_bounded():
    with pytest.raises(AssertionError, match="early UTC window"):
        exercise([119.5, 179.5, 239.5])


def test_clock_moving_backwards_fails():
    with pytest.raises(AssertionError, match="backwards"):
        exercise([120.5, 119.5])
