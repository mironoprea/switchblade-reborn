"""Tests for app.input_listener — loop pacing, no hardware needed."""

import time

from app.input_listener import InputListener


class _FakeInfo:
    def __init__(self, in_endpoint):
        self.in_endpoint = in_endpoint


class _FakeLink:
    def __init__(self, info, *, ready=True):
        self.info = info
        self._ready = ready

    def is_ready(self):
        return self._ready

    def read(self, *a, **k):
        raise AssertionError("read must not be called without an IN endpoint")


def test_run_paces_itself_when_no_vendor_in_endpoint(monkeypatch):
    # With no vendor IN endpoint, UsbLink.read() returns instantly, so the
    # listener must sleep to yield the CPU rather than hot-loop `continue`.
    link = _FakeLink(_FakeInfo(in_endpoint=None))
    listener = InputListener(link, callback=lambda ev: None)

    sleeps = []
    polls = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        listener._stop.set()  # terminate the loop after the first pass

    def fake_poll_hid():
        polls.append(True)

    monkeypatch.setattr(listener, "_poll_hid", fake_poll_hid)
    monkeypatch.setattr(time, "sleep", fake_sleep)

    listener._run()  # would spin forever (AssertionError on read) if unguarded

    assert polls == [True]
    assert sleeps == [0.01]


def test_run_closes_hid_handles_when_link_disconnects(monkeypatch):
    link = _FakeLink(_FakeInfo(in_endpoint=None), ready=False)
    listener = InputListener(link, callback=lambda ev: None)
    listener._hid_opened = True

    closes = []

    def fake_close_hid():
        closes.append(True)
        listener._hid_opened = False

    def fake_sleep(seconds):
        listener._stop.set()

    monkeypatch.setattr(listener, "_close_hid", fake_close_hid)
    monkeypatch.setattr(time, "sleep", fake_sleep)

    listener._run()

    assert closes == [True]


def test_poll_hid_discards_failed_handles():
    class _BadHid:
        def __init__(self):
            self.closed = False

        def read(self, length):
            raise OSError("stale handle")

        def close(self):
            self.closed = True

    dev = _BadHid()
    listener = InputListener(_FakeLink(_FakeInfo(in_endpoint=None)), callback=lambda ev: None)
    listener._hid_opened = True
    listener._hid_handles = [dev]

    listener._poll_hid()

    assert dev.closed
    assert listener._hid_handles == []
    assert not listener._hid_opened
