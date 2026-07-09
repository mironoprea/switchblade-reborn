from pathlib import Path

from tools import capture_usbpcap


def test_build_command_targets_root_and_output():
    cmd = capture_usbpcap.build_command(
        "USBPcapCMD.exe",
        6,
        Path("captures/test.pcap"),
        snaplen=1234,
    )

    assert cmd == [
        "USBPcapCMD.exe",
        "-d",
        r"\\.\USBPcap6",
        "-o",
        "captures\\test.pcap",
        "-s",
        "1234",
        "-A",
    ]


def test_parse_root_range_and_list():
    assert capture_usbpcap._parse_roots("1-3") == [1, 2, 3]
    assert capture_usbpcap._parse_roots("2,4,6") == [2, 4, 6]
