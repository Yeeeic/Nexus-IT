import asyncio

from backend.app.realtime.hub import BoundedClientBuffer


def test_buffer_caps_at_100_and_drops_new_noncritical_telemetry() -> None:
    buffer = BoundedClientBuffer(capacity=100)

    async def exercise() -> None:
        for index in range(100):
            assert await buffer.put({"type": "telemetry", "value": index}, critical=False)
        assert not await buffer.put({"type": "telemetry", "value": 101}, critical=False)
        assert buffer.size == 100

    asyncio.run(exercise())


def test_critical_event_evicts_intermediate_telemetry_when_full() -> None:
    buffer = BoundedClientBuffer(capacity=2)

    async def exercise() -> None:
        await buffer.put({"type": "alert", "value": 1}, critical=True)
        await buffer.put({"type": "telemetry", "value": 2}, critical=False)
        assert await buffer.put({"type": "alert", "value": 3}, critical=True)
        first = await buffer.get()
        second = await buffer.get()
        assert [first["value"], second["value"]] == [1, 3]

    asyncio.run(exercise())
