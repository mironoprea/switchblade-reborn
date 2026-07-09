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
| 3 | 0xFF (Vendor) | 0xF0 | 0x00 | Bulk OUT 0x01 (512), Bulk IN 0x02 (512) | Switchblade UI |

The vendor interface (class 0xFF) must be bound to WinUSB via Zadig.
HID interfaces (class 0x03) must NOT be touched.

## Blit packet format

**[PORTED from FxChiP/rzswitchblade]** Header format, opcode, and checksum confirmed
against the C source (`rzsblit_proto.c`, `rzsblit_sync.c`).

A blit consists of a 12-byte header followed by RGB565 pixel data, sent as
consecutive bulk OUT transfers to endpoint 0x01.

**[PORTED from FxChiP/rzswitchblade]** In the original C library, the 12-byte header
and the pixel payload are sent as **two separate** `libusb_bulk_transfer` calls (header
first, then pixel data). The current Python implementation concatenates them into a
single `write()` call, which is internally chunked to `max_out_packet` (512 bytes).
If blits fail on hardware, try sending the header and payload as separate transfers
(see IMPLEMENTATION_PLAN.md Section G.5).

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

RGB565, 2 bytes per pixel.  Big-endian within each pixel word by default
(most significant byte first).  If colors appear swapped on hardware, switch
to little-endian byte order per pixel.

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

### Example: key blit (key 0, 115×115, solid red)

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

**[UNKNOWN]** The exact addressing of dynamic key images is not yet confirmed.
FxChiP/rzswitchblade only implements touchpad blitting (`rzswitchblade_blit_tp_sync`);
no key-image addressing code exists in that library.

Two hypotheses:

1. Keys are an extended region of the same virtual framebuffer, starting at
   y = 480 (below the screen).  Each key is 115×115 pixels, laid out
   horizontally: key 0 at x=0, key 1 at x=115, etc.
2. A different opcode or endpoint is used for key images.

**[PORTED from FxChiP/rzswitchblade]** The FxChiP README states each "macro button"
can hold a **116×116** icon (not 115×115). The current code uses 115; if key
images appear clipped or offset, try `KEY_IMAGE_SIZE = 116`.

A USB capture of Synapse assigning key images resolves this.

## Key events

**[UNKNOWN]** Key press events are expected on the vendor IN endpoint (0x02).
The exact packet format is unknown.  Two hypotheses implemented in
`protocol.parse_key_event()`:

1. `byte[0]` = key index (1-indexed, 1-10), `byte[1]` = down/up flag.
2. `byte[0]` = bitmask of pressed keys (bit 0 = key 0, etc.)

If no events arrive on the vendor interface, listen on HID interfaces via
hidapi instead.

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
