# Hardware protocol

Device: Razer DeathStalker Ultimate, VID `1532`, PID `0114`.

## Interfaces

| Interface | Class | Endpoint | Use |
|---|---|---|---|
| `MI_00` | HID | interrupt IN `0x81` | keyboard/mouse collection |
| `MI_01` | HID | interrupt IN `0x82` | media and adaptive-key reports |
| `MI_02` | HID | interrupt IN `0x83` | system control and brightness reports |
| `MI_03` | vendor `0xff` | bulk OUT `0x01`, `0x02` | main display and adaptive-key images |

Only `MI_03` is bound to WinUSB.

## Image transfer

Each update is two bulk transfers: a 12-byte header followed by one complete
little-endian RGB565 payload. Header fields are six big-endian unsigned 16-bit
integers:

```text
opcode, x1, y1, x2, y2, checksum
```

`opcode` is `0x0001`; coordinates are inclusive; `checksum` is the XOR of the
first five fields. Main-display updates use endpoint `0x01` and coordinates
within `(0,0)-(799,479)`.

Adaptive-key images use endpoint `0x02`, a 115×115 RGB565 payload, and these
captured rectangles:

| Key | Rectangle |
|---:|---|
| 0 | `(9,318)-(124,433)` |
| 1 | `(178,318)-(293,433)` |
| 2 | `(346,318)-(461,433)` |
| 3 | `(515,318)-(630,433)` |
| 4 | `(683,318)-(798,433)` |
| 5 | `(9,151)-(124,266)` |
| 6 | `(178,151)-(293,266)` |
| 7 | `(346,151)-(461,266)` |
| 8 | `(515,151)-(630,266)` |
| 9 | `(683,151)-(798,266)` |

The key rectangles span 116×116 coordinate units although the accepted payload
is 115×115; key packets therefore use a dedicated validator.

## Key input

Adaptive keys report through HID report ID `0x04`. `04 50` through `04 59`
represent keys 0 through 9 pressed. `04 00` releases the last pressed key.

## Brightness

Brightness is a 90-byte HID feature report accepted by `MI_02`. Channel 1 is the
normal keyboard backlight and channel 2 is the ten adaptive-key backlights.

- Bytes 6-8: `03 09 01`.
- Byte 10: channel (`01` or `02`).
- Byte 11: `round(percent * 255 / 100)`.
- Byte 88: XOR of bytes 6 through 87.
- Other request bytes are zero except byte 2, which is `ff`.

`app.protocol.build_brightness_report()` is the executable specification.
