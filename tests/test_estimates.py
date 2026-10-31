import pytest

from raw_to_png.estimates import RemainingTime, duration_message
from raw_to_png.i18n import render


def learned():
    value = RemainingTime()
    value.completed(12, 24_000_000, 1)
    value.completed(12, 24_000_000, 1)
    return value


def test_waits_for_real_results_and_suspends_on_memory_wait():
    value = RemainingTime()
    assert value.estimate(68, [], 4) is None
    value.completed(10, 24_000_000)
    assert value.estimate(67, [], 4) is None
    assert learned().estimate(60, [(1, 24_000_000)], 4, waiting=True) is None


def test_concurrency_and_partial_work_affect_remaining_time():
    value = learned()
    assert value.estimate(8, [], 1) == pytest.approx(96)
    assert value.estimate(8, [], 4) == pytest.approx(24)
    assert value.estimate(0, [(8, 24_000_000)], 4) == pytest.approx(4)
    assert value.estimate(0, [], 4) == 0


def test_handles_backoff_and_mixed_resolutions_without_zero_countdown():
    value = learned()
    # Existing workers finish before a reduced limit admits the next job.
    assert value.estimate(1, [(0, 24_000_000)]*4, 2) == pytest.approx(24)
    assert value.estimate(0, [(0, 48_000_000)], 4) == pytest.approx(23)
    assert value.estimate(0, [(30, 24_000_000)], 4) is None


def test_ignores_invalid_samples_and_accounts_for_serial_launch():
    value = RemainingTime()
    value.completed(0, 24_000_000)
    value.completed(12, 0)
    assert not value.samples
    value.completed(1, 24_000_000, .7)
    value.completed(1, 24_000_000, .7)
    assert value.estimate(10, [], 8) >= 7


@pytest.mark.parametrize('seconds,ru,en', [
    (1, 'менее 10 с', 'less than 10 s'),
    (21, '30 с', '30 s'),
    (100, '2 мин', '2 min'),
    (181, '3 мин 30 с', '3 min 30 s'),
    (3661, '1 ч 2 мин', '1 h 2 min'),
])
def test_duration_is_approximate_and_translatable(seconds, ru, en):
    value = duration_message(seconds)
    assert render(value, 'ru') == ru
    assert render(value, 'en') == en
