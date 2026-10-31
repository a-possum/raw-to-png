"""Approximate remaining work from recent successful jobs, not skipped files."""
from collections import deque
import heapq
import math
import statistics

from .i18n import message


class RemainingTime:
    def __init__(self):
        self.samples = deque(maxlen=8)

    def completed(self, seconds, pixels, bootstrap_seconds=0):
        if seconds > 0 and pixels > 0:
            self.samples.append((seconds, pixels, max(0, bootstrap_seconds)))

    def estimate(self, queued, running, limit, waiting=False):
        """running is (elapsed wall time, known RAW pixels or zero) per worker."""
        if waiting or len(self.samples) < 2:
            return None
        pixels = statistics.median(row[1] for row in self.samples)
        overhead = statistics.median(row[2] for row in self.samples)
        per_pixel = statistics.median(max(0, seconds - bootstrap) / count
                                      for seconds, count, bootstrap in self.samples)
        duration = max(.1, overhead + per_pixel * pixels)
        slots = []
        for elapsed, count in running:
            expected = max(.1, overhead + per_pixel * (count or pixels))
            # A stalled or unusually slow job should not count down to zero.
            if elapsed > expected * 1.5:
                return None
            slots.append(max(1, expected - elapsed))
        heapq.heapify(slots)
        limit = max(1, limit)
        for _ in range(queued):
            start = 0
            while len(slots) >= limit:
                start = heapq.heappop(slots)
            heapq.heappush(slots, start + duration)
        # Metadata probing/launch is serial even when conversions are parallel.
        return max(max(slots, default=0), queued * overhead)


def duration_message(seconds):
    if seconds < 10:
        return message('менее 10 с')
    if seconds < 60:
        return message('{seconds} с', seconds=math.ceil(seconds / 10) * 10)
    if seconds < 3600:
        rounded = math.ceil(seconds / 30) * 30
        minutes, rest = divmod(rounded, 60)
        return (message('{minutes} мин {seconds} с', minutes=minutes, seconds=rest)
                if rest else message('{minutes} мин', minutes=minutes))
    hours, minutes = divmod(math.ceil(seconds / 60), 60)
    return message('{hours} ч {minutes} мин', hours=hours, minutes=minutes)
