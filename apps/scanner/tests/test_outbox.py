"""Scanner outbox smoke tests."""

from kalchas_scanner.outbox import MemoryAlertSink


def test_memory_sink_collects() -> None:
    sink = MemoryAlertSink()
    sink.emit({"match_id": "1", "value": 2.5})
    assert sink.items == [{"match_id": "1", "value": 2.5}]
