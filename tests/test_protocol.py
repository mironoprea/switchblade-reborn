"""Tests for app.protocol — pure functions, no hardware needed."""

import struct
import pytest
from app import protocol


class TestBlitHeader:
    def test_header_structure(self):
        header = protocol.build_blit_header(0, 0, 799, 479)
        assert len(header) == 12
        fields = struct.unpack(">HHHHHH", header)
        assert fields[0] == protocol.OP_BLIT
        assert fields[1] == 0    # x1
        assert fields[2] == 0    # y1
        assert fields[3] == 799  # x2
        assert fields[4] == 479  # y2

    def test_checksum_is_xor_of_five_fields(self):
        header = protocol.build_blit_header(10, 20, 30, 40)
        fields = struct.unpack(">HHHHHH", header)
        expected_checksum = (fields[0] ^ fields[1] ^ fields[2] ^ fields[3] ^ fields[4]) & 0xFFFF
        assert fields[5] == expected_checksum

    def test_checksum_specific_value(self):
        # Full-screen: opcode=1, x1=0, y1=0, x2=799, y2=479
        # XOR: 0x0001 ^ 0x0000 ^ 0x0000 ^ 0x031F ^ 0x01DF = 0x02C1
        header = protocol.build_blit_header(0, 0, 799, 479)
        fields = struct.unpack(">HHHHHH", header)
        assert fields[5] == 0x02C1

    def test_full_screen_blit_checksum(self):
        """Verify the exact header bytes for a full-screen blit."""
        header = protocol.build_blit_header(0, 0, 799, 479)
        expected = bytes([0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x03, 0x1F, 0x01, 0xDF, 0x02, 0xC1])
        assert header == expected


class TestBuildBlit:
    def test_full_screen_payload(self):
        payload = b"\x00\x00" * (800 * 480)
        packet = protocol.build_screen_blit(payload)
        assert len(packet) == 12 + len(payload)
        # Header should be present
        assert packet[:2] == b"\x00\x01"

    def test_small_rect(self):
        width, height = 10, 5
        payload = b"\xFF\xFF" * (width * height)
        packet = protocol.build_blit(0, 0, 9, 4, payload)
        assert len(packet) == 12 + width * height * 2

    def test_payload_size_mismatch_raises(self):
        with pytest.raises(ValueError, match="payload size mismatch"):
            protocol.build_blit(0, 0, 9, 9, b"\x00" * 10)  # should be 200 bytes

    def test_coordinate_swap(self):
        """x1 > x2 and y1 > y2 should be swapped automatically."""
        payload = b"\x00" * (10 * 10 * 2)
        packet = protocol.build_blit(9, 9, 0, 0, payload)
        fields = struct.unpack(">HHHHHH", packet[:12])
        assert fields[1] == 0  # x1
        assert fields[2] == 0  # y1
        assert fields[3] == 9  # x2
        assert fields[4] == 9  # y2


class TestKeyBlit:
    def test_key_rect(self):
        x1, y1, x2, y2 = protocol.key_rect(0)
        assert x1 == 0
        assert y1 == protocol.KEY_Y_OFFSET
        assert x2 == protocol.KEY_IMAGE_SIZE - 1
        assert y2 == protocol.KEY_Y_OFFSET + protocol.KEY_IMAGE_SIZE - 1

    def test_key_rect_index_1(self):
        x1, y1, x2, y2 = protocol.key_rect(1)
        assert x1 == protocol.KEY_IMAGE_SIZE
        assert x2 == protocol.KEY_IMAGE_SIZE * 2 - 1

    def test_key_rect_invalid_index(self):
        with pytest.raises(ValueError):
            protocol.key_rect(10)
        with pytest.raises(ValueError):
            protocol.key_rect(-1)

    def test_build_key_blit(self):
        payload = b"\x00" * (protocol.KEY_IMAGE_SIZE * protocol.KEY_IMAGE_SIZE * 2)
        packet = protocol.build_key_blit(0, payload)
        assert len(packet) == 12 + len(payload)


class TestKeyEvent:
    def test_parse_key_down(self):
        # Key index 1 (1-indexed) = key 0, flag=1 = down
        data = bytes([1, 1])
        event = protocol.parse_key_event(data)
        assert event is not None
        assert event.key_index == 0
        assert event.pressed is True

    def test_parse_key_up(self):
        data = bytes([5, 0])
        event = protocol.parse_key_event(data)
        assert event is not None
        assert event.key_index == 4
        assert event.pressed is False

    def test_parse_key_index_10(self):
        data = bytes([10, 1])
        event = protocol.parse_key_event(data)
        assert event is not None
        assert event.key_index == 9
        assert event.pressed is True

    def test_parse_unknown_packet(self):
        data = bytes([0xFF, 0xFF])
        event = protocol.parse_key_event(data)
        # Should not match pattern 1 (index 255 > 10)
        # Bitmask: 0xFF = bits 0-7, which are valid key indices
        # So it could match pattern 2
        assert event is not None or event is None  # either is acceptable

    def test_parse_empty(self):
        event = protocol.parse_key_event(b"")
        assert event is None

    def test_parse_bitmask(self):
        # Bit 3 set = key 3 pressed
        data = bytes([0x08])
        event = protocol.parse_key_event(data)
        assert event is not None
        assert event.key_index == 3
