# JanOS SubGHz UI Architecture Reference

How to build a SubGHz UI that drives the JanOS CC1101 stack over UART, distilled
from three shipping reference projects. This is the **cross-device app-building
compendium** for the SubGHz domain: device classes, UI paradigms, screen
lifecycles, RX dispatch, threading, the RF-settings command builders, the
host/state split, and SubGHz-specific UI widgets (waterfall, capture list,
hunt spinner).

For the `subghz_*` command vocabulary and exact event formats see
[commands-reference.md](commands-reference.md). For the full per-screen catalog
see [screens-reference.md](screens-reference.md).

---

## The three reference projects

| Project | Path | Display | Input | UI library | SubGHz screens |
|---------|------|---------|-------|------------|----------------|
| **Tab5** | `/Users/jan/kod/tab5/M5MonsterC5-Tab5` | 1280x720 | touch | **LVGL** | `main/screens/subghz_*.c` |
| **CoreS3** | `/Users/jan/kod/coreS3` | 320x240 | touch | **LVGL** | `main/screens/subghz_*.c` |
| **CardputerADV** | `/Users/jan/kod/M5MonsterC5-CardputerADV` | 240x135 | **keyboard** | **none — text UI** | `main/screens/subghz_*.c` |

The CC1101 radio lives on a JanOS ESP32-C5; the UI sends `subghz_*` commands and
parses streamed `[SUBGHZ_*]` / `[KAT_RX]` / `[KL_DEC]` text events.

---

## Two UI paradigms

### Paradigm A — LVGL touch (Tab5, CoreS3)

Screens are `lv_obj_t` trees; navigation is imperative `show_subghz_*_page()` /
`show_subghz_*_screen()`; back buttons call the parent show function. LVGL is
not thread-safe (see Threading).

### Paradigm B — keyboard text UI (CardputerADV)

No LVGL. Custom 30x8 character framebuffer (`main/ui/text_ui.c`), stack-based
`screen_manager` with `screen_t` callbacks (`on_key`/`on_draw`/`on_tick`/
`on_destroy`/`on_resume`). UART runs in its own task; SubGHz screens defer
drawing via dirty flags consumed in `on_tick`
(`main/screens/subghz_listen_screen.c:456`).

The general lifecycle, navigation API, UART setup, line-accumulator, threading
rules, input models, and PSRAM patterns are **identical to the WiFi/janos side**
— see the janos `architecture-reference.md`. This file documents what is
SubGHz-specific.

---

## The modular SubGHz pattern (recommended template)

All three projects keep SubGHz in its own module under `main/screens/`, separate
from the WiFi UI. This is the cleanest template for adding SubGHz to a new
device. Files (names consistent across projects):

| File | Role |
|------|------|
| `subghz_screen.c` / `subghz_menu_screen.c` | SubGHz sub-menu + tile/menu factory |
| `subghz_listen_screen.c` | Receive / RSSI waterfall / capture list (`subghz_rx`) |
| `subghz_scanner_screen.c` | Quick traffic scan over the freq list (`subghz_scanner`) |
| `subghz_hunter_screen.c` | Frequency analyzer + auto-capture (`subghz_freq_analyzer hunt`) |
| `subghz_manage_screen.c` | SD signal library CRUD (`subghz_list sd`, rename, delete, tx) |
| `subghz_weather_screen.c` | Weather sensor decoder (`subghz_weather`) |
| `subghz_jammer_screen.c` | Jammer (`subghz_jam`) |
| `subghz_tesla_screen.c` | Tesla charge-port replay (`subghz_tx tesla`) |
| `subghz_settings_screen.c` | Freq correction get/set |
| `subghz_*_settings_screen.c` | NVS RF tuning for Listen / Hunter / Scanner |
| `subghz_parser.c/h` | `[SUBGHZ_*]` line -> `subghz_signal_info_t` parser |
| `subghz_rf_settings.c/h` | NVS RF params + `subghz_*` command builders |
| Tab5 only: `subghz_host.h`, `subghz_signal_list.c`, `subghz_text_input_popup.c`, `psram_dynarr.c` | host API, sync list collector, rename popup, PSRAM arrays |
| Cardputer only: `subghz_freq_picker_screen.c` | numeric frequency picker (UI-only, no command) |

### Tab5 host/state split (for multi-endpoint devices)

Tab5 supports several JanOS endpoints (tabs), so SubGHz state is per-tab and the
screens never touch the transport directly. `subghz_host.h` defines the host API
the screens call; `main.c` implements it:

- `subghz_host_state()` -> the active `subghz_tab_state_t` (holds `freq_mhz`,
  page pointers, capture chunks; allocated in PSRAM,
  `subghz_host_alloc_state()` `main/main.c:5830`).
- `subghz_host_uart_send(cmd)` / `subghz_host_uart_read_bytes(tab_id, ...)` —
  route to the active tab's transport (`main/main.c:5883`).
- `subghz_host_hide_all_pages()` / `subghz_host_show_main_tiles()` — navigation
  (`main/main.c:5915`).
- `subghz_host_current_container()` / `subghz_host_current_tab()`.

On a single-UART device (CoreS3, Cardputer) you don't need this indirection —
the SubGHz screens call `uart_send_command()` / `uart_register_line_callback()`
directly and keep state in a per-screen struct or file-scope globals.

---

## RF settings & command builders

Listen/Hunter/Scanner expose tunables (RSSI gates, trigger, dwell, edges,
timeout, raw/single/fast flags) persisted in NVS and assembled into the actual
`subghz_*` command. Don't hand-format these commands in the screen — use the
builders. `subghz_rf_settings.h`:

```c
typedef struct {
    int8_t   hunter_trigger_dbm;   /* -120..-40 */
    uint16_t hunter_timeout_ms;    /* 100..60000 */
    bool     hunter_raw;
    bool     hunter_single;
    bool     hunter_fast;
    uint16_t scanner_dwell_ms;     /* 20..500 */
    uint8_t  scanner_edges;
    int8_t   scanner_rssi_dbm;     /* -120..-40 */
    bool     scanner_fast;
    int8_t   listen_rssi_dbm;      /* -120..-40 */
} subghz_rf_settings_t;

void subghz_rf_build_hunter_cmd(const subghz_rf_settings_t *s, char *buf, size_t len);
void subghz_rf_build_scanner_cmd(const subghz_rf_settings_t *s, char *buf, size_t len);
```

Usage (CoreS3/Tab5 scanner start):

```c
subghz_rf_settings_t cfg;
subghz_rf_settings_load(&cfg);
char cmd[96];
subghz_rf_build_scanner_cmd(&cfg, cmd, sizeof(cmd));  // e.g. "subghz_scanner dwell=80 edges=4 rssi=-75"
uart_send_command(cmd);                                // (subghz_host_uart_send on Tab5)
```

Listen builds its command inline from `listen_rssi_dbm` and the raw flag:
`subghz_rx rssi=<dbm>` or `subghz_rx raw rssi=<dbm>`
(`main/screens/subghz_listen_screen.c:808`). The settings sub-screens
(`subghz_*_settings_screen.c`) only edit the NVS struct and call
`subghz_rf_settings_save()` — they send no UART.

---

## Parsing: `subghz_parser`

A pure string parser turns a `[SUBGHZ_*]` line into a `subghz_signal_info_t`.
Pattern (`main/screens/subghz_parser.c`):

1. `subghz_normalize_line(line)` finds the earliest `[SUBGHZ_` (or `[subghz]`)
   tag in a line so leading firmware noise is skipped.
2. Classify the tag into a `kind` (`RX`, `RX_DUP`, `RAW`, `LIST`, ...).
3. Extract `key=value` fields with helpers (`extract_int_field("idx=", ...)`,
   `extract_field("type=", ...)`, `extract_float_field("freq=", ...)`, plus
   `serial`, `btn`, `proto`, `learn`, `mf`, `cnt`, `te`, `edges`, `name`).

`[SUBGHZ_RSSI] <dBm>` is parsed as the integer after `]`. Reuse this parser
verbatim on a new device — only the screen that consumes the resulting structs
changes. Remember the two `[SUBGHZ_RX]` layouts (static `id=`/`te=` vs rolling
`serial=`/`btn=`) — try the rolling layout first; see
[commands-reference.md](commands-reference.md) for exact formats.

---

## SubGHz-specific UI widgets

### RSSI waterfall (Listen)

A scrolling RGB565 canvas fed by `[SUBGHZ_RSSI]` events. Allocate the canvas
buffer in PSRAM (`heap_caps_malloc(W * H * 2, MALLOC_CAP_SPIRAM)` with an
internal-RAM fallback) and free it in cleanup. Sizing: Tab5 ~800x70, CoreS3
`WATERFALL_W 320 x WATERFALL_H 40` (`main/screens/subghz_listen_screen.c:21`).
Push one column per RSSI sample inside the LVGL lock / `ui_tick_cb`.

### Capture list (Listen / Hunter)

Captures stream in unbounded, so do **not** create one widget per signal:

- **CoreS3** uses a recycled row-view pool (`SIGNAL_ROW_POOL_SIZE 10`,
  `SIGNAL_ROW_HEIGHT 18`, `main/screens/subghz_listen_screen.c:21`) + a virtual
  spacer — a virtual-scroll list over a PSRAM-backed signal store.
- **Tab5** keeps captures in a chunked PSRAM linked list
  (`subghz_signal_chunk_t`, 64 signals/chunk) and Hunter history in
  `psram_dynarr`.
- **Cardputer** keeps a `SemaphoreHandle_t`-guarded signal array and redraws only
  the dirty row range in `on_tick` (`row_dirty_from`/`row_dirty_to`).

`[SUBGHZ_RX]` appends a row; `[SUBGHZ_RX_DUP]` flashes/updates the existing row
by `idx`; `[SUBGHZ_RAW]` appends a RAW row.

### Hunt-mode spinner state machine

Between `[SUBGHZ_FA] hunt capture ...` and the terminating event the UI shows a
"capturing..." spinner; clear it on any terminator:

```
[SUBGHZ_FA] hunt capture freq=... timeout=2000ms mode=decode   → spinner ON
   ├─ [SUBGHZ_RX] / [SUBGHZ_RAW]                                → spinner OFF, append row
   ├─ [SUBGHZ_FA] hunt timeout (no burst captured)              → spinner OFF, miss
   ├─ [SUBGHZ_FA] hunt duplicate (already in keystore)          → spinner OFF, toast
   └─ [SUBGHZ_FA] hunt error (alloc/save)                       → spinner OFF, error
[SUBGHZ_FA] silent (last freq=... rssi=...)                     → idle indicator
```

Keep a header strip showing "FA scanning... last hit <freq> @ <rssi> dBm".

### Scanner -> Listen handoff

Tapping a scanner hit must stop the scanner, set the frequency, **clean up the
scanner screen first**, then open Listen with autostart. Cleaning up before
opening the next screen prevents two screens fighting over the single UART RX
owner (`main/screens/subghz_scanner_screen.c:199`):

```c
stop_scanner(st);
snprintf(cmd, sizeof(cmd), "subghz_freq %.2f", freq);
subghz_host_uart_send(cmd);        // uart_send_command() on single-UART devices
subghz_scanner_cleanup(st);        // stop reader / clear callback FIRST
show_subghz_listen_page_at(freq, true);
```

---

## Cleanup checklist (every SubGHz screen)

1. Send **`subghz_stop`** (the universal stop for any `subghz_*` task).
2. Clear the alive flag; stop/join the reader task.
3. `uart_set_line_callback(NULL)` / `uart_stop_collect()` (CoreS3) or
   `uart_clear_line_callback()` (Cardputer).
4. Delete `lv_timer`s / `esp_timer`s.
5. `lv_obj_del()` the page (LVGL) or `free(data)` (text UI); NULL pointers.
6. `heap_caps_free()` the waterfall canvas and any PSRAM capture chunks.

When handing off between SubGHz screens (Scanner -> Listen, Hunter -> Manage),
run the prior screen's cleanup **before** creating the next so only one screen
owns the UART RX path.

---

## Per-device sizing (SubGHz)

| Element | Tab5 (1280x720) | CoreS3 (320x240) | Cardputer (240x135) |
|---------|-----------------|------------------|---------------------|
| Menu tile | 220x154 | `LV_PCT(46)` x 38 (8 tiles) | text menu, ~8 items |
| Scanner freq tile | 320x130 | small grid | text rows |
| Waterfall | ~800x70 | 320x40 | n/a (text activity bar) |
| Capture row | 34-42px | 18px (pooled) | one text row |
| Detail panel | full popup | split or scrollable | tabbed (Header/Raw/Decoded) |

On the tiny Cardputer screen, split a captured-key detail into Header / Raw /
Decoded tabs instead of one long form, and use the dedicated
`subghz_freq_picker_screen` for numeric frequency entry (it sends no command —
it returns the chosen MHz to the caller).
