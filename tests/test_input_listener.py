"""Tests for app.input_listener — loop pacing, no hardware needed."""

import time

from app.input_listener import InputListener


class _FakeInfo:
    def __init__(self, in_endpoint):
        self.in_endpoint = in_endpoint


class _FakeLink:
    def __init__(self, info):
        self.info = info

    def is_ready(self):
        return True

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
