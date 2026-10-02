"""Test-only fixed UTC minute coordination; no provider calls."""
from datetime import datetime, timezone


def in_fresh_minute(*, prepare, now, sleep, burst):
    """Return one measured burst, retrying once ONLY on observed rollover.

    `now` must read the gateway's clock, not the host's. `prepare` resets
    counters on every attempt. Exceptions from the burst are never retried.
    """
    for attempt in range(2):
        prepare()
        for poll in range(3):
            before = now()
            if before % 60 <= 10:
                break
            assert poll < 2, "Could not observe an early UTC window"
            sleep(61 - before % 60)
        result = burst()
        after = now()
        print(
            f"RPM attempt {attempt + 1}: gateway UTC "
            f"{datetime.fromtimestamp(before, timezone.utc).isoformat()} -> "
            f"{datetime.fromtimestamp(after, timezone.utc).isoformat()}; "
            f"result={result!r}"
        )
        assert after >= before, "Gateway UTC clock moved backwards"
        if int(before // 60) == int(after // 60):
            return result
        # Not a limiter failure retry: this measurement spans distinct keys.
    raise AssertionError("Both RPM measurements crossed UTC minute boundaries")
