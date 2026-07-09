from tools import analyze_capture


def test_parse_capdata_accepts_tshark_colon_hex():
    assert analyze_capture.parse_capdata("00:01:00:00") == b"\x00\x01\x00\x00"


def test_decode_blit_header_validates_checksum():
    header = bytes.fromhex("000100000000031f01df02c1")

    assert analyze_capture.decode_blit_header(header) == (
        1,
        0,
        0,
        799,
        479,
        0x02C1,
    )


def test_find_blit_headers_attaches_next_payload_length():
    header = bytes.fromhex("000100000000000a000a0001")
    payloads = [
        analyze_capture.UsbPayload("1", "5", "0x01", "0x03", header),
        analyze_capture.UsbPayload("2", "5", "0x01", "0x03", b"x" * 242),
    ]

    headers = analyze_capture.find_blit_headers(payloads)

    assert len(headers) == 1
    assert headers[0].width == 11
    assert headers[0].height == 11
    assert headers[0].payload_len == 242
