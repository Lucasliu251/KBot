from __future__ import annotations

import asyncio
import unittest

from kookvoice.kookvoice import PCMTransportPacer


class FakeClock:
    def __init__(self, oversleep: float = 0.0) -> None:
        self.now = 0.0
        self.oversleep = oversleep

    def __call__(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.now += max(0.0, delay) + self.oversleep
        self.oversleep = 0.0


class TransportPacingTest(unittest.TestCase):
    def test_processing_time_is_deducted_from_next_sleep(self) -> None:
        async def scenario() -> list[float]:
            clock = FakeClock()
            pacer = PCMTransportPacer(clock=clock, sleeper=clock.sleep)
            sent_at = []
            for _ in range(500):
                await pacer.wait()
                sent_at.append(clock.now)
                # 模拟线上逐样本音量处理与 pipe drain 的每帧开销。
                clock.now += 0.0003
            return sent_at

        sent_at = asyncio.run(scenario())
        mean_interval = (sent_at[-1] - sent_at[0]) / (len(sent_at) - 1)
        self.assertAlmostEqual(mean_interval, 0.02, places=9)

    def test_large_lateness_resyncs_without_burst(self) -> None:
        async def scenario() -> tuple[float, bool, float]:
            clock = FakeClock()
            pacer = PCMTransportPacer(clock=clock, sleeper=clock.sleep)
            await pacer.wait()
            clock.now += 0.055
            lateness, resynced = await pacer.wait()
            resync_sent_at = clock.now
            clock.now += 0.0003
            await pacer.wait()
            return lateness, resynced, clock.now - resync_sent_at

        lateness, resynced, next_interval = asyncio.run(scenario())
        self.assertTrue(resynced)
        self.assertGreater(lateness, 0.02)
        self.assertAlmostEqual(next_interval, 0.02, places=9)

    def test_large_event_loop_oversleep_resyncs_without_next_frame_burst(self) -> None:
        async def scenario() -> tuple[bool, float]:
            clock = FakeClock()
            pacer = PCMTransportPacer(clock=clock, sleeper=clock.sleep)
            await pacer.wait()
            clock.now += 0.0003
            clock.oversleep = 0.03
            _, resynced = await pacer.wait()
            resync_sent_at = clock.now
            clock.now += 0.0003
            await pacer.wait()
            return resynced, clock.now - resync_sent_at

        resynced, next_interval = asyncio.run(scenario())
        self.assertTrue(resynced)
        self.assertAlmostEqual(next_interval, 0.02, places=9)


if __name__ == '__main__':
    unittest.main()
