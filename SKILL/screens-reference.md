# JanOS SubGHz Screen Catalog

Every SubGHz screen found across the three reference projects, with the
`subghz_*` commands each sends and per-device construction notes. Use this as a
menu of what a SubGHz UI can offer.

Columns: **Screen** · **Sends** (UART commands) · **Devices** (T=Tab5, C=CoreS3,
K=CardputerADV). All three implement the same SubGHz feature set; the file names
match across projects (`subghz_<feature>_screen.c`, except Cardputer's menu is
`subghz_menu_screen.c`).

For command syntax/events see [commands-reference.md](commands-reference.md).
For how to build these screens see [architecture-reference.md](architecture-reference.md).
For implementation-grade flows (exact command sequence, state/cache, parser
tags, whether RX/scan/hunt continues during secondary operations, and cleanup
handoffs) see [flows-reference.md](flows-reference.md).

---

## Menu & navigation

| Screen | Sends | Devices |
|--------|-------|---------|
| SubGHz menu (tile grid / text menu, ~8 entries) | none | T C K |

The SubGHz menu is reached from the home screen only when a `subghz_status`
probe succeeded at boot. Entries: Listen, Quick Scan, Hunter, SD Signals,
Weather, Jammer, Tesla, Settings.

---

## Receive / capture

| Screen | Sends | Devices |
|--------|-------|---------|
| Listen (RX waterfall + capture list) | `subghz_freq <MHz>`, `subghz_rx [raw] rssi=<dbm>`, `subghz_stop`, `subghz_save <idx>`, `subghz_tx <idx> mem` | T C K |
| Quick Scan (traffic scanner) | `subghz_scanner [dwell= edges= rssi= fast]` (via `subghz_rf_build_scanner_cmd`), `subghz_stop`, `subghz_freq` (on tile -> Listen) | T C K |
| Hunter (frequency analyzer + auto-capture) | `subghz_freq_analyzer [trigger] hunt\|raw [single] [fast] [timeout=]` (via `subghz_rf_build_hunter_cmd`), `subghz_stop`, `subghz_save`, `subghz_tx` | T C K |

- **Listen** streams `[SUBGHZ_RSSI]` (waterfall), `[SUBGHZ_RX]`/`[SUBGHZ_RX_DUP]`/
  `[SUBGHZ_RAW]` (capture rows), plus `[KAT_RX]`/`[KL_DEC]` decode detail. Save a
  mem capture to SD with `subghz_save <idx>`; replay with `subghz_tx <idx> mem`.
- **Quick Scan** streams `[SUBGHZ_SCAN_START]`, `[SUBGHZ_SCAN_HIT]`,
  `[SUBGHZ_SCAN_PASS]`. Tapping a hit stops the scanner and hands off to Listen
  at that frequency (cleanup scanner first — see architecture reference).
- **Hunter** streams `[SUBGHZ_FA_START]`, `[SUBGHZ_FA] freq=`, `hunt capture`,
  `hunt timeout/error/duplicate`, `silent`, plus the standard RX events on a hit.
  Show a "capturing..." spinner between `hunt capture` and its terminator.

---

## Signal library (SD)

| Screen | Sends | Devices |
|--------|-------|---------|
| SD Signals / Manage | `subghz_list sd`, `subghz_rename <idx> <name>`, `subghz_delete <idx>`, `subghz_tx <idx> sd`, `subghz_stop` | T C K |

Re-issue `subghz_list sd` after every `rename`/`delete`/`save` because SD indices
are positional. Tab5 uses `subghz_signal_list.c` (a synchronous
`subghz_list mem|sd` collector) and `subghz_text_input_popup.c` for the rename
keyboard popup; Cardputer reuses its `text_input_screen` for rename.

---

## Other receivers

| Screen | Sends | Devices |
|--------|-------|---------|
| Weather (sensor decoder) | `subghz_weather`, `subghz_stop` | T C K |
| Jammer | `subghz_freq <MHz>`, `subghz_jam`, `subghz_stop` | T C K |

Weather streams `[SUBGHZ_WEATHER_START]` then one `[SUBGHZ_WEATHER] proto=... id=...
temp=... hum=... batt=...` per decoded sensor (deduped ~30s); key the UI rows by
(proto, id, channel).

---

## Transmit

| Screen | Sends | Devices |
|--------|-------|---------|
| Tesla (charge-port replay) | `subghz_freq 315.00`, `subghz_tx tesla` | T C K |

Replay of saved signals is handled inside Listen / SD Signals via
`subghz_tx <idx> <mem\|sd> [raw]`; there is no separate generic "replay" screen.

---

## Settings (NVS, no streaming UART)

| Screen | Sends | Devices |
|--------|-------|---------|
| Freq correction | `subghz_get_freq_correction`, `subghz_set_freq_correction ±X.XX` | T C K |
| Listen settings (RSSI gate) | none — edits NVS via `subghz_rf_settings_save()` | T C K |
| Hunter settings (trigger, timeout, raw/single/fast) | none — NVS | T C K |
| Scanner settings (dwell, edges, RSSI, fast) | none — NVS | T C K |

The settings sub-screens only mutate the `subghz_rf_settings_t` struct; the
Listen/Hunter/Scanner screens read it back and build the command at start time.

---

## Device-only screens

| Screen | Sends | Devices |
|--------|-------|---------|
| Frequency picker (numeric MHz entry) | none — returns chosen MHz to caller | K |

Cardputer adds `subghz_freq_picker_screen` because it has no touch keyboard for
quick frequency entry; on Tab5/CoreS3 the frequency is chosen via on-screen
controls or the scanner handoff.

---

## Per-device construction notes

- **Tab5** — modular `main/screens/subghz_*.c` behind the `subghz_host.h` API;
  per-tab `subghz_tab_state_t` in PSRAM; ~800x70 waterfall; chunked PSRAM capture
  list; Hunter history in `psram_dynarr`.
- **CoreS3** — single UART; 320x40 waterfall; recycled 10-row pool +
  virtual-scroll capture list; 8-tile menu shrunk to 38px rows to fit 320x240.
- **CardputerADV** — text UI, keyboard nav; dirty-flag redraw in `on_tick`;
  `SemaphoreHandle_t`-guarded signal array; split detail into Header/Raw/Decoded
  tabs; dedicated numeric frequency picker.
