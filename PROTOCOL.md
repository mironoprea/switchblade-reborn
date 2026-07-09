# PROTOCOL.md — Switchblade Reborn Protocol Documentation

This file documents the USB wire protocol for the Razer DeathStalker Ultimate
Switchblade UI (VID 0x1532, PID 0x0114).  Facts are tagged with their evidence
source.  Update this file when hardware captures reveal new information.

## Device map

**[CONFIRMED]** on real hardware (see HANDOFF.md). Vendor interface = interface 3, class 0xFF.

| Interface | Class | Subclass | Protocol | Endpoints | Purpose |
|-----------|-------|----------|----------|-----------|---------|
| 0 | 0x03 (HID) | 0x01 | 0x02 | Interrupt IN 0x81 (8B) | Standard keyboard |
| 1 | 0x03 (HID) | 0x00 | 0x01 | Interrupt IN 0x82 (16B) | HID media/consumer |
| 2 | 0x03 (HID) | 0x01 | 0x01 | Interrupt IN 0x83 (8B) | HID system control |
| 3 | 0xFF (Vendor) | 0xF0 | 0x00 | Bulk OUT 0x01 (512), Bulk OUT 0x02 (512), no bulk IN observed | Switchblade UI |

The vendor interface (class 0xFF) must be bound to WinUSB via Zadig.
HID interfaces (class 0x03) must NOT be touched.

## Blit packet format

**[PORTED from FxChiP/rzswitchblade]** Header format, opcode, and checksum confirmed
against the C source (`rzsblit_proto.c`, `rzsblit_sync.c`).

A blit consists of a 12-byte header followed by RGB565 pixel data, sent to bulk
OUT endpoint 0x01.

**[CONFIRMED]** The DeathStalker Ultimate updates the screen when the 12-byte
header and pixel payload are sent as **two separate** bulk transfers: header first,
then the complete payload as one transfer. Chunking the payload into 512-byte
writes completed at the USB level but did not update the LCD reliably. This
matches the FxChiP/rzswitchblade transfer shape.

### Header (12 bytes)

| Offset | Size | Field | Description |
|--------|------|-------|-------------|
| 0 | 2 | opcode | `0x0001` (BLIT) |
| 2 | 2 | x1 | Rectangle left (big-endian uint16) |
| 4 | 2 | y1 | Rectangle top (big-endian uint16) |
| 6 | 2 | x2 | Rectangle right (big-endian uint16) |
| 8 | 2 | y2 | Rectangle bottom (big-endian uint16) |
| 10 | 2 | checksum | XOR of the five preceding uint16 fields |

All fields are big-endian (`htons` in C).  The checksum is computed as:

```
checksum = opcode ^ x1 ^ y1 ^ x2 ^ y2
```

(as uint16 XOR, result masked to 0xFFFF).

### Rectangle semantics

The rectangle is **inclusive**: pixel count = (x2 - x1 + 1) × (y2 - y1 + 1).

### Pixel format

RGB565, 2 bytes per pixel. **[CONFIRMED]** Little-endian byte order within each
pixel word is required on this hardware. Big-endian writes produced swapped or
wrong colors during live bring-up.

Pixel value:
```
r5 = (R >> 3) & 0x1F
g6 = (G >> 2) & 0x3F
b5 = (B >> 3) & 0x1F
pixel = (r5 << 11) | (g6 << 5) | b5
```

### Example: full-screen blit (800×480, solid black)

Header bytes:
```
00 01   # opcode = 0x0001 (BLIT)
00 00   # x1 = 0
00 00   # y1 = 0
03 1F   # x2 = 799 (SCREEN_WIDTH - 1)
01 DF   # y2 = 479 (SCREEN_HEIGHT - 1)
02 C1   # checksum = 0x0001 ^ 0x0000 ^ 0x0000 ^ 0x031F ^ 0x01DF = 0x02C1
```

Payload: 800 × 480 × 2 = 768,000 bytes of `0x00 0x00` (black pixels).

### Rejected example: old key blit hypothesis (key 0, 115×115)

These bytes are retained only as documentation of the rejected hypothesis. Live
testing showed this address writes into the main touch LCD, not a physical key.

Header bytes:
```
00 01   # opcode = 0x0001 (BLIT)
00 00   # x1 = 0 (key_index * KEY_IMAGE_SIZE)
01 E0   # y1 = 480 (KEY_Y_OFFSET)
00 72   # x2 = 114 (0 + 115 - 1)
02 52   # y2 = 594 (480 + 115 - 1)
03 C1   # checksum = 0x0001 ^ 0x0000 ^ 0x01E0 ^ 0x0072 ^ 0x0252 = 0x03C1
```

## Key image addressing

**[REJECTED hypothesis / UNKNOWN replacement]** The exact addressing of dynamic key
images is not yet confirmed. Hardware testing showed the old virtual-framebuffer
hypothesis (`y = 480`, one 115×115 region per key) writes onto the main touch LCD
instead of separate physical key displays. The daemon therefore does **not** blit
profile key images to hardware keys by default.
FxChiP/rzswitchblade only implements touchpad blitting (`rzswitchblade_blit_tp_sync`);
no key-image addressing code exists in that library.

Remaining hypotheses:

1. A different opcode, endpoint, report, or mode is used for physical key images.
2. The physical key backlights may not be individually addressable as full images
   on this DeathStalker Ultimate firmware path.

**[PORTED from FxChiP/rzswitchblade]** The FxChiP README states each "macro button"
can hold a **116×116** icon (not 115×115). The current code uses 115; if key
images appear clipped or offset, try `KEY_IMAGE_SIZE = 116`.

A USB capture of Synapse assigning key images resolves this.

## Key events

**[CONFIRMED]** Physical LCD-key presses arrive on a non-keyboard HID collection,
not the vendor interface. Live enumeration on 2026-07-09 showed no vendor bulk IN
endpoint on interface 3; endpoint `0x02` is reported as a second bulk OUT endpoint.

Captured HID reports use report ID `0x04`:

1. `04 50 ...` through `04 59 ...` = physical LCD key 0 through 9 pressed.
2. `04 00 ...` = release of the previously pressed physical LCD key.

The physical keys and the main touch LCD are distinct surfaces. Do not infer key
image addressing from physical keypress reports.

Two legacy vendor-packet hypotheses are still implemented in
`protocol.parse_key_event()` for captures that do produce raw vendor key bytes:

1. `byte[0]` = key index (1-indexed, 1-10), `byte[1]` = down/up flag.
2. `byte[0]` = bitmask of pressed keys (bit 0 = key 0, etc.)

The daemon uses hidapi for this path when the vendor interface has no IN endpoint.

**[CONFIRMED implementation behavior]** Because the attached hardware exposes no
vendor bulk IN endpoint, `UsbLink.read()` returns `b""` immediately in that state
and `InputListener` paces itself with a sleep instead of busy-spinning. Use
`tools/listen_hid.py` before Zadig, while the Razer/HID stack is still intact, to
capture raw reports from the non-keyboard HID collections.

## Init sequence

**[PORTED from FxChiP/rzswitchblade]** No init/mode-switch sequence is needed.
The FxChiP C library opens the device, detaches the kernel driver (Linux), claims
the interface, and immediately blits. No control transfers or magic packets are sent
before the first blit. The `Daemon._initialize_device()` hook exists as a no-op
placeholder; if hardware testing reveals an init sequence is needed (e.g. when using
WinUSB instead of the Linux kernel driver detach path), fill it in there.

## Brightness

**[UNKNOWN]** Screen brightness control format.  May be a vendor command or
standard Razer HID feature report (OpenRazer documents a 90-byte report format).
Captures needed.
