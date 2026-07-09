from pathlib import Path

import pytest

from app import protocol
from app.sdk_backend import SdkBackendConfig, rgb565_to_image


def test_rgb565_to_image_little_endian_primary_colors():
    rgb565 = (
        (0xF800).to_bytes(2, "little")
        + (0x07E0).to_bytes(2, "little")
        + (0x001F).to_bytes(2, "little")
    )

    image = rgb565_to_image(rgb565, 3, 1)

    assert image.getpixel((0, 0)) == (255, 0, 0)
    assert image.getpixel((1, 0)) == (0, 255, 0)
    assert image.getpixel((2, 0)) == (0, 0, 255)


def test_rgb565_to_image_rejects_wrong_size():
    with pytest.raises(ValueError, match="RGB565 buffer"):
        rgb565_to_image(b"\x00", 1, 1)


def test_sdk_backend_config_defaults_to_paths():
    config = SdkBackendConfig()

    assert isinstance(config.sdk_dir, Path)
    assert isinstance(config.bridge_dir, Path)


def test_key_constants_match_sdk_dynamic_key_shape():
    assert protocol.KEY_COUNT == 10
    assert protocol.KEY_IMAGE_SIZE == 115
