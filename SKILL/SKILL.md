---
name: janos-subghz-uart
description: Build UI applications (LVGL touchscreen or keyboard text-UI) that talk to JanOS Sub-GHz firmware (CC1101 on ESP32-C5) over UART. Use when creating UI for Tab5/CoreS3/Cardputer that issues subghz_* commands (subghz_freq, subghz_rx, subghz_tx, subghz_freq_analyzer hunt, subghz_scanner, subghz_weather, subghz_list, subghz_save, subghz_delete, subghz_rename, subghz_jam, subghz_stop) and parses [SUBGHZ_*] / [SUBGHZ_FA] / [SUBGHZ_RX] / [SUBGHZ_SCAN_*] / [SUBGHZ_WEATHER] / [KAT_RX] / [KL_DEC] / [SUBGHZ_RSSI] events. Two-tier storage model: a volatile in-memory cache (mem) filled by subghz_rx/hunt and a persistent SD library (sd) populated by subghz_save. Covers receive, transmit, frequency analyzer with auto-capture (hunt mode), mem/SD listing, RAW capture, jammer, traffic scanner, weather sensors.
---

# JanOS SubGHz UART UI Builder

Guide for building UIs that drive the JanOS SubGHz CC1101 stack over a text UART.
The firmware runs on ESP32‑C5; this skill is about the **UI side** (Tab5 / CoreS3
LVGL touch, Cardputer keyboard text UI, or any host). This file is the **index +
command-domain quickstart**; device architecture and the screen catalog live in
companion files.

## This skill's files

- **[commands-reference.md](commands-reference.md)** — every `subghz_*` command:
  syntax, output, completion markers, event formats. The source of truth.
- **[architecture-reference.md](architecture-reference.md)** — how to build the UI
  on any device: the two UI paradigms (LVGL touch vs keyboard text UI), the
  modular SubGHz pattern, the RF-settings command builders, the host/state split,
  parsing, and SubGHz widgets (waterfall, capture list, hunt spinner,
  scanner→listen handoff). **Read this before building screens on a new device.**
- **[screens-reference.md](screens-reference.md)** — catalog of every SubGHz
  screen across the three reference projects with the commands each sends.
- **[flows-reference.md](flows-reference.md)** — implementation-grade runbook:
  per-screen command sequences, runtime state/cache, parser tags, whether
  RX/scan/hunt continues during save/TX/list, and cleanup/handoff behavior.
  **Read this when implementing a SubGHz screen, not just listing features.**

## Reference projects (all in the workspace)

| Project | Path | Display | Input | UI |
|---------|------|---------|-------|----|
| Tab5 | `/Users/jan/kod/tab5/M5MonsterC5-Tab5` | 1280x720 | touch | LVGL, modular `subghz_host.h` |
| CoreS3 | `/Users/jan/kod/coreS3` | 320x240 | touch | LVGL, single UART |
| CardputerADV | `/Users/jan/kod/M5MonsterC5-CardputerADV` | 240x135 | keyboard | custom text UI, no LVGL |

## Architecture

```
┌────────────────────────────────┐        UART (115200 8N1)        ┌──────────────────────┐
│  UI Device (Tab5/CoreS3/etc)   │ ──────────────────────────────> │  JanOS SubGHz on C5  │
│  - touch or keyboard UI        │ <────────────────────────────── │  - CC1101 radio      │
│  - Sends `subghz_*` commands   │     [SUBGHZ_*] text events      │  - SPI2 + GDO0 ISR   │
│  - Parses [SUBGHZ_*] events    │                                 │  - PSRAM mem cache   │
│  - FreeRTOS UART task          │                                 │  - SD .sub library   │
└────────────────────────────────┘                                 └──────────────────────┘
```

JanOS exposes a text CLI over UART. Every UI screen sends a `subghz_*` command and parses the streamed `[SUBGHZ_*]` (and `[KAT_RX]`, `[KL_DEC]`, `[KAT_DBG]`) text events.

## Storage model (two tiers)

Signals live in one of two places. **Commands that touch signals pick a source explicitly**:

| Tier  | Backed by                          | How it's filled                                | Indexing                                   | Persistence              |
|-------|------------------------------------|------------------------------------------------|--------------------------------------------|--------------------------|
| `mem` | Dynamic PSRAM cache (no fixed cap) | Auto-saved by `subghz_rx` and `subghz_freq_analyzer hunt` | `idx = capture_seq` (monotonic 1-based)    | Wiped on reboot or `subghz_clear` |
| `sd`  | `/sdcard/lab/subghz/*.sub`         | Deliberate `subghz_save <mem_idx>` or `subghz_save all` | 1..N enumeration sorted by leading `NNNNN_` prefix then name | Survives reboot |

Routing rules:

- `subghz_rx`, `subghz_freq_analyzer hunt` → write to **mem only** (no automatic SD persistence).
- `subghz_list`, `subghz_info`, `subghz_tx` take a `<mem|sd>` source argument.
- `subghz_save <mem_idx>|all` is the **only** way to promote a mem signal to the SD library. The mem entry is left in place.
- `subghz_delete <sd_idx>` and `subghz_rename <sd_idx> <new_name>` operate on **SD only**. Rename updates both the filename and the `Name:` field inside the `.sub`.
- `subghz_clear` empties the **mem cache only**; the SD library is untouched.
- Indices in the two tiers are independent — a UI that needs to mutate either side should re-list the affected source right after every mutation (delete / rename / save).

## UART Setup

```c
#define UART_NUM          UART_NUM_1
#define UART_BAUD_RATE    115200
#define UART_BUF_SIZE     4096

static void uart_init(void) {
    const uart_config_t uart_config = {
        .baud_rate = UART_BAUD_RATE,
        .data_bits = UART_DATA_8_BITS,
        .parity    = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    uart_driver_install(UART_NUM, UART_BUF_SIZE * 2, 0, 0, NULL, 0);
    uart_param_config(UART_NUM, &uart_config);
    uart_set_pin(UART_NUM, tx_pin, rx_pin, UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
}
```

## Sending Commands

Always append `\r\n`. Log every command sent.

```c
static void uart_send_command(const char *cmd) {
    uart_write_bytes(UART_NUM, cmd, strlen(cmd));
    uart_write_bytes(UART_NUM, "\r\n", 2);
    ESP_LOGI(TAG, "Sent: %s", cmd);
}
```

## Reading & Parsing Responses

### Core pattern: line-by-line accumulation

All `[SUBGHZ_*]` events are line‑based. Read bytes, accumulate into a line buffer, parse on newline:

```c
char rx_buffer[UART_BUF_SIZE];
char line_buffer[512];
int line_pos = 0;

while (!done && !timed_out) {
    int len = uart_read_bytes(UART_NUM, rx_buffer, UART_BUF_SIZE - 1, pdMS_TO_TICKS(100));
    if (len > 0) {
        rx_buffer[len] = '\0';
        for (int i = 0; i < len; i++) {
            char c = rx_buffer[i];
            if (c == '\n' || c == '\r') {
                if (line_pos > 0) {
                    line_buffer[line_pos] = '\0';

                    /* === PARSE THIS LINE ===
                     * Most subghz events start with [SUBGHZ_, [KAT_, [KL_  */
                    if (strstr(line_buffer, "COMPLETION_MARKER")) {
                        done = true; break;
                    }
                    parse_subghz_line(line_buffer);

                    line_pos = 0;
                }
            } else if (line_pos < sizeof(line_buffer) - 1) {
                line_buffer[line_pos++] = c;
            }
        }
    }
}
```

### Completion markers cheat-sheet

| Command | Completion / first useful line | Continuous events while running |
|---------|--------------------------------|----------------------------------|
| `subghz_status`           | `[SUBGHZ_STATUS] ...`           | one line, single shot |
| `subghz_freq` (set)       | `[SUBGHZ_FREQ] <MHz>`           | one line, single shot |
| `subghz_freq_analyzer`    | `[SUBGHZ_FA_START] ...`         | `[SUBGHZ_FA] freq=... rssi=... stage=...` (continuous) |
| `subghz_freq_analyzer hunt` | `[SUBGHZ_FA_START] ... hunt=1`| FA hits + `[SUBGHZ_FA] hunt capture ...` + `[SUBGHZ_RX]` / `[KAT_RX]` / `[KL_DEC]` |
| `subghz_scanner`          | `[SUBGHZ_SCAN_START] dwell=Nms edges=N rssi=N fast=0\|1` | `[SUBGHZ_SCAN_HIT] freq=... edges=... rssi=...` (gated by edges and rssi floor) + `[SUBGHZ_SCAN_PASS] freqs=N hits=N` per loop |
| `subghz_weather`          | `[SUBGHZ_WEATHER_START] freq=433.92` | `[SUBGHZ_WEATHER] proto=... id=0x... ch=... temp=... hum=... batt=...` per decoded report |
| `subghz_rx [raw] [rssi=-DBM]` | none until first hit          | `[SUBGHZ_RSSI] N` (~1 Hz), then on decode hit `[REPLAY_SEG]` + `SubGHz: key saved` + `[SUBGHZ_RX]` / `[SUBGHZ_RX_DUP]` / `[SUBGHZ_RAW]` / `[SUBGHZ_RX_DROP]` (burst killed by noise gate, default `-80 dBm`). Saved to mem only — promote to SD with `subghz_save`. |
| `subghz_tx <idx> <mem\|sd> [raw]` | `[SUBGHZ_TX] idx=N source=<mem\|sd> done` | one line |
| `subghz_jam`              | `SubGHz jammer ACTIVE on ...`   | (jammer running until stop) |
| `subghz_list <mem\|sd>`   | `[SUBGHZ_LIST_END] count=N source=<mem\|sd>` | `[SUBGHZ_LIST] ...` per signal |
| `subghz_info <idx> <mem\|sd>` | `[SUBGHZ_INFO_END]`         | `[SUBGHZ_INFO] ...` + optional `[SUBGHZ_INFO_RAW] t1 t2 ...`, or `[SUBGHZ_INFO_ERR] idx=N reason=... source=<mem\|sd>` on failure |
| `subghz_save <mem_idx>\|all` | `[SUBGHZ_SAVE_END] count=N` | `[SUBGHZ_SAVE] idx=N file=... name=...` per saved entry, `[SUBGHZ_SAVE_ERR] idx=N reason=<invalid\|not_found\|collision\|write_failed>` on failure |
| `subghz_delete <sd_idx>`  | `[SUBGHZ_DELETE] idx=N file=... remaining=M source=sd` | one line, or `[SUBGHZ_DELETE_ERR] idx=N reason=... source=sd` |
| `subghz_rename <sd_idx> <new_name>` | `[SUBGHZ_RENAME] idx=N old=... new=... file=... source=sd` | one line, or `[SUBGHZ_RENAME_ERR] idx=N reason=... source=sd` |
| `subghz_clear`            | `[SUBGHZ_CLEAR] done removed=N source=mem` | one line; wipes mem cache; SD library is intentionally untouched |
| `subghz_stop`             | `SubGHz operations stopped.`    | one line, kills any running task |
| `subghz_protocols`        | `[SUBGHZ_PROTOS_END] ...`       | `[SUBGHZ_PROTO] ...` per protocol |
| `subghz_keys`             | `[SUBGHZ_KEYS_END]`             | `[SUBGHZ_KEY] ...` per MF key + `[SUBGHZ_KEYS_RAW]` summary |
| `subghz_selftest`         | exit code via prompt            | implementation‑specific log lines |

For continuous tasks (`subghz_rx`, `subghz_freq_analyzer`, `subghz_scanner`, `subghz_weather`, `subghz_jam`) you stop with `subghz_stop` from the UI cleanup.

### Universal subghz event tag conventions

* `[SUBGHZ_*]` — primary GUI events (`RX`, `RX_DUP`, `RAW`, `RSSI`, `LIST`, `INFO`, `SAVE`, `SAVE_ERR`, `SAVE_END`, `RENAME`, `RENAME_ERR`, `DELETE`, `DELETE_ERR`, `FA`, `FA_START`, `SCAN_START`, `SCAN_HIT`, `SCAN_PASS`, `WEATHER`, `WEATHER_START`, `STATUS`, `FREQ`, `TX`, `CLEAR`, `PROTO`, `KEY`). All `RX`/`RAW`/`LIST`/`INFO` rows end in ` name=<basename>` (the SD-renameable label, see [commands-reference.md](commands-reference.md#subghz_rename)).
* `[KAT_RX]` — rolling‑code dispatcher result (KeeLoq, Nice FloR-S, Faac SLH, CAME Atomo, Somfy, Hormann, Security+, etc.). Always has `serial=0xNNNN btn=N cnt=N mf=NAME`.
* `[KL_DEC]` — KeeLoq‑specific decoder dump: `bits=N te_auto=N fix=0xN hop=0xN plain=0xN learn=N mf=NAME cnt=N`.
* `[KL_GROUND]` — KeeLoq dedup/ground‑truth verification line.
* `[REPLAY_SEG]` — one line per decoded burst from segmented replay. GUI should rely on `[SUBGHZ_RX]`.
* `[KAT_DBG]` — per‑attempt decode‑failure debug. **Off by default** — `subghz_debug kat_dbg on`.
* `[subghz]` (lowercase) — verbose firmware diagnostic, **NOT meant for GUI parsing**. RCSwitch timing (`RAW t[0..9]`, `TE corrected`, `Reclassified`) **off by default** — `subghz_debug rc_dbg on` or `subghz_replay_test`.

When showing logs to the user in the UI, you usually want to:
1. Surface `[SUBGHZ_*]` events into structured rows.
2. Surface `[KAT_RX]` and `[KL_DEC]` into the decoded fields panel of the captured key.
3. Optionally show `[subghz]` lines in a "verbose" log drawer (collapsed by default).

## Key Parsing Recipes

### Frequency analyzer hit (live waterfall / list)

```c
/* Line: "[SUBGHZ_FA] freq=433.9200 rssi=-62 stage=fine"   (or stage=coarse, freq=433.857)
 * Note fine prints %.4f, coarse prints %.3f. Both work with %f. */
if (strstr(line, "[SUBGHZ_FA] freq=")) {
    float freq;
    int   rssi;
    char  stage[8] = {0};
    if (sscanf(line, "[SUBGHZ_FA] freq=%f rssi=%d stage=%7s", &freq, &rssi, stage) == 3) {
        /* update FA waterfall: freq + rssi + stage(coarse|fine) */
    }
}
```

### FA hunt-mode events

```c
/* "[SUBGHZ_FA] hunt capture freq=433.9200 stage=fine timeout=2000ms mode=decode" */
if (strstr(line, "[SUBGHZ_FA] hunt capture")) {
    float freq; char stage[8]; int timeout_ms; char mode[8];
    sscanf(line, "[SUBGHZ_FA] hunt capture freq=%f stage=%7s timeout=%dms mode=%7s",
           &freq, stage, &timeout_ms, mode);
    /* show "Capturing on 433.9200…" overlay for `timeout_ms` */
}
/* "[SUBGHZ_FA] hunt timeout (no burst captured)"          → spinner off, count++ misses
 * "[SUBGHZ_FA] hunt error (alloc/save)"                   → red error banner
 * "[SUBGHZ_FA] hunt duplicate (already in keystore)"      → toast "duplicate" */
if (strstr(line, "[SUBGHZ_FA] hunt timeout"))   { /* miss */ }
if (strstr(line, "[SUBGHZ_FA] hunt error"))     { /* error */ }
if (strstr(line, "[SUBGHZ_FA] hunt duplicate")) { /* dup */ }

/* "[SUBGHZ_FA] silent (last freq=433.857 rssi=-44)" — sample-hold expired, no signal */
if (strstr(line, "[SUBGHZ_FA] silent")) { /* idle indicator */ }
```

### Captured key (decoded protocol)

`[SUBGHZ_RX]` is emitted by both `subghz_rx` and the analyzer's hunt mode. There are TWO field layouts depending on whether the protocol is rolling-code or static:

```c
/* Static / fixed-code (Princeton, Holtek, CAME, Nice, etc.):
 * "[SUBGHZ_RX] idx=2 type=HOLTEK freq=433.91 bits=12 id=3F0A te=337 proto=HOLTEK learn=UNKNOWN mf=- cnt=0" */
if (strstr(line, "[SUBGHZ_RX] idx=")) {
    int idx, bits, cnt, te;
    char type[24], id[24], proto[24], learn[24], mf[24];
    float freq;

    /* Try rolling-code layout first (has serial=0xNNNNNN btn=N) */
    unsigned long serial; int btn;
    int n = sscanf(line,
        "[SUBGHZ_RX] idx=%d type=%23s freq=%f bits=%d serial=0x%lX btn=%d "
        "proto=%23s learn=%23s mf=%23s cnt=%d te=%d",
        &idx, type, &freq, &bits, &serial, &btn, proto, learn, mf, &cnt, &te);
    if (n >= 6) {
        /* rolling-code key: KeeLoq, StarLine, Nice FloR-S, Faac SLH, CAME Atomo,
         * Somfy Telis/Keytis, Hormann HSM/BiSecur, Security+ 1.0/2.0, KingGates,
         * Hay21, Scher-Khan, KIA Seed, X10, Alutech AT-4N, Jarolift */
        store_key(idx, type, freq, bits, serial, btn, proto, learn, mf, cnt, te);
    } else if (sscanf(line,
        "[SUBGHZ_RX] idx=%d type=%23s freq=%f bits=%d id=%23s te=%d "
        "proto=%23s learn=%23s mf=%23s cnt=%d",
        &idx, type, &freq, &bits, id, &te, proto, learn, mf, &cnt) == 10) {
        /* static OOK key: HOLTEK, Princeton, CAME, NICE, GateTX, Linear, Megacode,
         * Marantec, Bett, Doitrand, Phoenix V2, Honeywell, Magellan, Intertechno,
         * Clemsa, Ansonic, SMC5326, Dooya, Mastercode, Legrand, Dickert, etc. */
        store_key_static(idx, type, freq, bits, id, te, proto, mf, cnt);
    }
}
```

### Captured RAW (decode failed → raw replay)

```c
/* "[SUBGHZ_RAW] idx=3 freq=433.90 edges=154" */
if (strstr(line, "[SUBGHZ_RAW] idx=")) {
    int idx, edges;
    float freq;
    if (sscanf(line, "[SUBGHZ_RAW] idx=%d freq=%f edges=%d", &idx, &freq, &edges) == 3) {
        /* RAW key — no protocol info, just edge count */
    }
}
```

### Duplicate hit

```c
/* Static dup:  "[SUBGHZ_RX_DUP] idx=1 type=HOLTEK freq=433.92 id=AABBCC proto=HOLTEK learn=- mf=- cnt=0"
 * Rolling dup: "[SUBGHZ_RX_DUP] idx=2 type=KeeLoq freq=433.92 serial=0x04DEC1 cnt=37189 learn=MAGIC_XOR_T1 mf=Leopard" */
if (strstr(line, "[SUBGHZ_RX_DUP] idx=")) {
    int idx;
    sscanf(line, "[SUBGHZ_RX_DUP] idx=%d", &idx);
    /* highlight existing row idx, increment hit-count counter */
}
```

### KeeLoq decoded payload (extra detail panel)

```c
/* "[KL_DEC] bits=65 te_auto=400 fix=0x2004DEC1 hop=0x3B760601 plain=0x22C19144 learn=4 mf=Leopard cnt=37188"
 * — emitted BEFORE the matching [KAT_RX] / [SUBGHZ_RX]. Stash it and
 *    attach to the next [SUBGHZ_RX] for the "decrypted payload" panel. */
if (strstr(line, "[KL_DEC] bits=")) {
    int bits, learn, cnt;
    unsigned long fix, hop, plain;
    char te_auto_buf[16] = {0}; /* may be "n/a" if no MF key matched */
    char mf[32];
    if (sscanf(line, "[KL_DEC] bits=%d te_auto=%15s fix=0x%lX hop=0x%lX plain=0x%lX "
               "learn=%d mf=%31s cnt=%d",
               &bits, te_auto_buf, &fix, &hop, &plain, &learn, mf, &cnt) == 8) {
        /* attach: fix code, hop code, decrypted plain, MF name, counter */
    }
}
```

### KAT rolling-code summary

```c
/* "[KAT_RX] KeeLoq decoded+decrypted: serial=0x04DEC1 btn=2 cnt=37188 mf=Leopard learn=MAGIC_XOR_T1"
 * "[KAT_RX] Nice FloR-S decoded+decrypted: serial=0x44A2582 btn=1 cnt=3040 mf=Nice One learn=UNKNOWN"
 * "[KAT_RX] <Proto> captured: serial=0xN btn=N raw=0xN learn=N (no MF key — clean re-encode on TX)" */
if (strstr(line, "[KAT_RX] ") && strstr(line, "decoded+decrypted")) {
    /* extract proto name (between "[KAT_RX] " and " decoded+decrypted")
     * + serial / btn / cnt / mf / learn fields */
}
```

### Decode failure (informational)

```c
/* "[KAT_DBG] decode failed: KL step=0 bits=0 hc=0 te_auto=0 | SL step=0 bits=0 hc=0 | FLOR step=2 bits=0 hc=1"
 * → optional verbose log, or just bump a "decode-fail" counter.
 *    Rolling-code dispatchers gave up; firmware will fall through to static
 *    decoders (PRINCETON / HOLTEK / etc) or save as RAW. */
if (strstr(line, "[KAT_DBG] decode failed")) { /* verbose only */ }
```

### RSSI waterfall (subghz_rx only)

```c
/* "[SUBGHZ_RSSI] -45"  ~ 1 Hz */
if (strstr(line, "[SUBGHZ_RSSI] ")) {
    int rssi = atoi(line + strlen("[SUBGHZ_RSSI] "));
    waterfall_push(rssi);
}

/* "[SUBGHZ_RX_DROP] reason=rssi peak=-87 th=-80 edges=23"
 * Burst rejected by the RX noise gate (default -80 dBm). Common on
 * clone / detuned CC1101 modules whose noise floor is ~-90 dBm. Safe
 * to ignore in the main UI; optionally show a faint "dropped: -87 dBm"
 * line in a debug panel so the user can tell phantom noise apart from
 * a UI bug. */
if (strstr(line, "[SUBGHZ_RX_DROP] ")) {
    int peak, th, edges;
    if (sscanf(line, "[SUBGHZ_RX_DROP] reason=rssi peak=%d th=%d edges=%d",
               &peak, &th, &edges) == 3) {
        debug_log_rx_drop(peak, th, edges);
    }
}
```

### List entries (subghz_list)

`subghz_list` always takes a `<mem|sd>` source argument. The per-row format is
identical for both sources (so the UI parser is shared). The terminator carries
the source so the UI can pick which list to refresh.

```c
/* RAW:    "[SUBGHZ_LIST] idx=3 type=RAW freq=433.90 edges=154 name=00003_raw_433900"
 * Static: "[SUBGHZ_LIST] idx=2 type=HOLTEK freq=433.91 bits=12 id=3F0A te=337 mf=- name=garageMain"
 * Rolling:"[SUBGHZ_LIST] idx=1 type=KeeLoq freq=433.85 bits=65 serial=0x04DEC1 btn=2 cnt=37188 mf=Leopard learn=MAGIC_XOR_T1 name=00001_KeeLoq_433.85_04DEC1" */
if (strstr(line, "[SUBGHZ_LIST] idx=")) { /* parse like SUBGHZ_RX above */ }

/* Terminator: "[SUBGHZ_LIST_END] count=4 source=mem"  (or source=sd) */
if (strstr(line, "[SUBGHZ_LIST_END] ")) {
    int count; char src[8] = {0};
    sscanf(line, "[SUBGHZ_LIST_END] count=%d source=%7s", &count, src);
    list_done_for_source(src, count);
}
```

### Status line

```c
/* "[SUBGHZ_STATUS] mode=Receive freq=433.92 keys=12 rssi=-92" */
if (strstr(line, "[SUBGHZ_STATUS] ")) {
    char mode[16];
    float freq; int keys, rssi;
    sscanf(line, "[SUBGHZ_STATUS] mode=%15s freq=%f keys=%d rssi=%d",
           mode, &freq, &keys, &rssi);
}
```

For the full per-command field tables and every event format the firmware emits, see [commands-reference.md](commands-reference.md).

## Building screens

The screen lifecycle, navigation, threading rules, RF-settings command builders,
the waterfall/capture-list/hunt-spinner widgets, the scanner→listen handoff, and
per-device sizing are documented in
[architecture-reference.md](architecture-reference.md). In short:

- **LVGL touch (Tab5, CoreS3):** `show_subghz_*_page()` → hide/clear siblings →
  build widgets → send `subghz_*` → stream events via reader task /
  `uart_set_line_callback` → update under `bsp_display_lock` / `lv_timer` →
  cleanup sends `subghz_stop`, clears callback, deletes objects, frees PSRAM.
- **Keyboard text UI (Cardputer):** `subghz_*_screen_create()` returns a
  `screen_t` with `on_key`/`on_draw`/`on_tick`/`on_destroy`; navigate with
  `screen_manager_push/pop/replace`; the UART callback sets dirty flags, draw
  only in `on_tick`; `on_destroy` sends `subghz_stop` and clears the callback.

Always send **`subghz_stop`** in cleanup (universal stop for any `subghz_*`
task), and when handing off between SubGHz screens run the prior screen's
cleanup first so only one screen owns the UART RX path.

Pick the screen you need from [screens-reference.md](screens-reference.md), look
up its events in [commands-reference.md](commands-reference.md), and build it
following the matching paradigm in
[architecture-reference.md](architecture-reference.md).

## Common Workflows

All four flows below assume UART is initialized and the firmware booted past `[subghz] CC1101 initialized on SPI2 ...`.

### 1. Manual receive ("Read")

```
subghz_freq 433.92         → wait for "[SUBGHZ_FREQ] 433.92"
subghz_rx                  → continuous events:
                              [SUBGHZ_RSSI] N             ~1 Hz waterfall
                              [REPLAY_SEG] start=…      decode segment (one per hit)
                              SubGHz: key saved …       legacy human line
                              [SUBGHZ_RX] idx=… type=…    new key (decoded)
                              [SUBGHZ_RX_DUP] idx=…       duplicate hit
                              [SUBGHZ_RAW] idx=… edges=…  decode failed → raw
                              [SUBGHZ_RX_DROP] reason=rssi peak=… th=… edges=…
                                                          burst killed by noise gate (clone/noisy CC1101 modules)
                              [KAT_RX] / [KL_DEC]         extra rolling-code detail
# Loosen the gate for weak / far signals (default is -80 dBm, range -120..-40):
subghz_rx rssi=-95
subghz_stop                → "SubGHz operations stopped."
```

### 2. RAW capture (no decode)

```
subghz_freq 868.35
subghz_rx raw
   → [SUBGHZ_RAW] idx=N freq=868.35 edges=N
subghz_stop
```

### 3. Frequency Analyzer (Flipper-style)

Two stages of the firmware do the heavy lifting (coarse scan then fine scan), GUI just consumes hits.

```
subghz_freq_analyzer            → scan-only, default trigger -85 dBm
subghz_freq_analyzer -90        → scan-only, custom trigger
   → [SUBGHZ_FA_START] trigger=-85 hunt=0 raw=0
   → [SUBGHZ_FA] freq=… rssi=… stage=fine|coarse  (per hit)
   → [SUBGHZ_FA] silent (last freq=… rssi=…)      (when sample-hold expires)
subghz_stop
```

### 4. Frequency Analyzer + auto-capture (HUNT mode)

The killer feature — analyzer scans, locks on a hit, switches to RX, captures+decodes one burst, saves to NVS, resumes scanning. Keep doing this in the background while the GUI shows a live "captures" list.

```
subghz_freq_analyzer hunt              → decode + auto-save on hit
subghz_freq_analyzer raw               → save raw timings on hit (no decode)
subghz_freq_analyzer -80 hunt          → custom trigger + hunt
subghz_freq_analyzer raw -75           → custom trigger + raw (any order)
   → [SUBGHZ_FA_START] trigger=-85 hunt=1 raw=0
   → [SUBGHZ_FA] freq=433.85 rssi=-50 stage=fine
   → [SUBGHZ_FA] hunt capture freq=433.85 stage=fine timeout=2000ms mode=decode
   → [KL_DEC] bits=65 te_auto=400 fix=0x... hop=0x... plain=0x... learn=4 mf=Leopard cnt=37188
   → [KAT_RX] KeeLoq decoded+decrypted: serial=0x04DEC1 btn=2 cnt=37188 mf=Leopard learn=MAGIC_XOR_T1
   → [SUBGHZ_RX] idx=1 type=KeeLoq freq=433.85 bits=65 serial=0x04DEC1 btn=2 ...
   → [SUBGHZ_FA] freq=433.91 rssi=-60 stage=fine
   → [SUBGHZ_FA] hunt capture freq=433.91 stage=fine timeout=2000ms mode=decode
   → [SUBGHZ_FA] hunt timeout (no burst captured)
   → [SUBGHZ_FA] silent (last freq=433.91 rssi=-60)
   → ... (continues)
subghz_stop
```

UI hint: keep a header strip showing "FA scanning… last hit 433.85 @ -50 dBm" plus a scrollable captures list filled from `[SUBGHZ_RX]` / `[SUBGHZ_RAW]`. Show a small "capturing…" spinner between `hunt capture` and the next event terminating the capture window (`[SUBGHZ_RX]`, `[SUBGHZ_RAW]`, `hunt timeout`, `hunt error`, `hunt duplicate`).

### 4b. Traffic scanner (subghz_scanner)

Edge-activity scan over the same Flipper Momentum frequency list as the
analyzer, but with no fine/hunt stages — just reports which frequencies
have OOK traffic above the configured RSSI floor. Loops forever until
`subghz_stop`. Adjacent in-band hits within ±500 kHz are collapsed into
one row (the strongest-RSSI representative wins) — see "dedup" below.

```
subghz_scanner                          → defaults: dwell=80ms, edges=4, rssi=-75
subghz_scanner dwell=120 edges=8        → less twitchy
subghz_scanner edges=2 fast             → more sensitive on edges + faster scan
subghz_scanner rssi=-80                 → widen RSSI window (catches weaker bursts)
subghz_scanner -85 edges=8              → Flipper-style trigger + tighter edge gate
   → [SUBGHZ_SCAN_START] dwell=80ms edges=4 rssi=-75 fast=0
   → [SUBGHZ_SCAN_HIT] freq=433.9200 edges=79 rssi=-39    # one row per cluster
   → [SUBGHZ_SCAN_HIT] freq=868.3500 edges=24 rssi=-49
   → [SUBGHZ_SCAN_PASS] freqs=62 hits=2
   → [SUBGHZ_SCAN_PASS] freqs=62 hits=0                   # both transmitters silent
   → ... (continues)
subghz_stop
```

Parser:

```c
/* "[SUBGHZ_SCAN_START] dwell=80ms edges=4 rssi=-75 fast=0" */
if (strstr(line, "[SUBGHZ_SCAN_START] ")) {
    int dwell, edges, rssi_floor, fast;
    if (sscanf(line, "[SUBGHZ_SCAN_START] dwell=%dms edges=%d rssi=%d fast=%d",
               &dwell, &edges, &rssi_floor, &fast) == 4) {
        /* show "scanning… (>=N edges, >=R dBm)" header */
    }
}
/* "[SUBGHZ_SCAN_HIT] freq=433.9200 edges=18 rssi=-58" */
if (strstr(line, "[SUBGHZ_SCAN_HIT] freq=")) {
    float freq; unsigned edges; int rssi;
    if (sscanf(line, "[SUBGHZ_SCAN_HIT] freq=%f edges=%u rssi=%d",
               &freq, &edges, &rssi) == 3) {
        /* highlight freq in the UI list, optionally bump per-freq hit count */
    }
}
/* "[SUBGHZ_SCAN_PASS] freqs=62 hits=1" — emitted at the end of every full pass */
if (strstr(line, "[SUBGHZ_SCAN_PASS] ")) { /* refresh "passes/hits" header */ }
```

Two layers of dedup are built into the firmware:
1. **Per-pass cluster collapse** — the OOK RX preset's 650 kHz BW makes one
   transmission light up every neighbouring scan-list entry within
   ~±500 kHz, so the scanner emits a single `[SUBGHZ_SCAN_HIT]` per
   contiguous run (representative = strongest RSSI, ties broken by
   edges). The reported `freq` is therefore an estimate of the
   transmitter centre, accurate to roughly the scan-list spacing
   (100–250 kHz in the 433/868 bands). Two real transmitters within
   ±500 kHz of each other will be reported as one cluster.
2. **Cross-pass sample-hold** — a cluster representative is suppressed
   on later passes unless its centre drifts more than 500 kHz or
   2+ fully silent passes break the streak — so the UI gets one row per
   "active session" rather than a flood.

The default `rssi=-75` floor exists because the CC1101 + ESP32 noise
floor pings at -85..-100 dBm and edge count alone cannot tell those
apart from a real -50 dBm burst. Drop to `rssi=-80`/`-85` only if you
are losing real weak hits.

### 4c. Weather sensor receiver (subghz_weather)

Listens on 433.92 MHz OOK and decodes broadcasts from common cheap
weather sensors (Nexus, Acurite-606TX, Auriol/Prologue HG02832,
LaCrosse-TX141TH-Bv2). Loops forever until `subghz_stop`. Same-(proto,
id, channel) packets are deduplicated for ~30 s unless temperature or
humidity changed.

```
subghz_weather
   → [SUBGHZ_WEATHER_START] freq=433.92
   → [SUBGHZ_WEATHER] proto=Acurite-592TXR id=0x12AB ch=1 temp=23.4 hum=48 batt=ok
   → [SUBGHZ_WEATHER] proto=Acurite-606TX id=0xC1 ch=- temp=-3.2 hum=- batt=ok
   → [SUBGHZ_WEATHER] proto=Bresser-3CH id=0x12 ch=2 temp=18.1 hum=55 batt=low
   → [SUBGHZ_WEATHER] proto=LaCrosse-TX141THBv2 id=0x7E ch=1 temp=22.5 hum=43 batt=ok
   → [SUBGHZ_WEATHER] proto=Oregon-v3.0 id=0xF824 ch=1 temp=19.7 hum=62 batt=ok
   → ... (continues every 30–60 s as sensors transmit)
subghz_stop
```

Parser:

```c
/* "[SUBGHZ_WEATHER] proto=Acurite-592TXR id=0x12AB ch=1 temp=23.4 hum=48 batt=ok"
 * 24 protocols supported (Acurite, Oregon, LaCrosse, Bresser, GT-WT, Nexus,
 * Auriol, Vauno, EMOS, AmbientWeather, Wendox, ThermoPRO, Solight, …).
 * Fields hum=- and ch=- can appear when the protocol does not carry them. */
if (strstr(line, "[SUBGHZ_WEATHER] proto=")) {
    char proto[32], ch[8], temp[16], hum[8], batt[8];
    unsigned long id;
    if (sscanf(line,
               "[SUBGHZ_WEATHER] proto=%31s id=0x%lX ch=%7s temp=%15s hum=%7s batt=%7s",
               proto, &id, ch, temp, hum, batt) == 6) {
        /* update sensor row keyed by (proto, id, channel) */
    }
}
```

### 5. List & replay (mem cache)

```
subghz_list mem
   → [SUBGHZ_LIST] idx=1 ... (one per signal)
   → [SUBGHZ_LIST_END] count=N source=mem

subghz_info <idx> mem        # detail panel
   → [SUBGHZ_INFO] ...
   → [SUBGHZ_INFO_RAW] t1 t2 t3 ...   (only for raw or unknown signals)
   → [SUBGHZ_INFO_END]

subghz_tx <idx> mem          # replay from mem cache
subghz_tx <idx> mem raw      # force raw replay (bypass KeeLoq counter increment)
   → [SUBGHZ_TX] idx=N source=mem done

subghz_clear                 # wipe the mem cache; SD library untouched
   → [SUBGHZ_CLEAR] done removed=N source=mem
```

### 6. Save / SD library (`/sdcard/lab/subghz/`)

The SD library is the **persistent** half of the storage model. It is only
populated by `subghz_save` — there is no automatic write to SD after RX/hunt.
`subghz_delete` / `subghz_rename` always operate on SD; renaming changes both
the filename and the `Name:` field inside the `.sub` file so the new name
survives reboot.

```
# Promote a mem entry to the SD library (mem entry is kept):
subghz_save 1                  → [SUBGHZ_SAVE] idx=1 file=/sdcard/lab/subghz/00001_KeeLoq_433.85_04DEC1.sub name=00001_KeeLoq_433.85_04DEC1
                               → [SUBGHZ_SAVE_END] count=1
                               (or [SUBGHZ_SAVE_ERR] idx=1 reason=collision|not_found|write_failed|...)

subghz_save all                → one [SUBGHZ_SAVE] line per copied mem entry
                               → [SUBGHZ_SAVE_END] count=N

# List the SD library (1-based idx is positional to this enumeration):
subghz_list sd
   → [SUBGHZ_LIST] idx=1 type=... name=00001_KeeLoq_433.85_04DEC1
   → [SUBGHZ_LIST] idx=2 type=... name=garageMain
   → [SUBGHZ_LIST_END] count=2 source=sd

# Inspect a single SD signal:
subghz_info 2 sd               → [SUBGHZ_INFO] ... name=garageMain
                               → [SUBGHZ_INFO_END]

# Replay from SD:
subghz_tx 2 sd                 → [SUBGHZ_TX] idx=2 source=sd done

# Rename file + Name: field on disk:
subghz_rename 1 garageMain     → [SUBGHZ_RENAME] idx=1 old=00001_KeeLoq_433.85_04DEC1 new=garageMain file=/sdcard/lab/subghz/garageMain.sub source=sd
                               (or [SUBGHZ_RENAME_ERR] idx=1 reason=collision|bad_char|not_found|too_long|... source=sd)

# Remove file from disk:
subghz_delete 2                → [SUBGHZ_DELETE] idx=2 file=/sdcard/lab/subghz/garageMain.sub remaining=1 source=sd
                               (or [SUBGHZ_DELETE_ERR] idx=2 reason=not_found|sd_error|unlink_failed source=sd)
```

UI tips:

- The SD idx is positional (1..N) within the current directory enumeration. After every `subghz_save`/`subghz_delete`/`subghz_rename` the UI must re-issue `subghz_list sd` before using the new indices.
- Files imported from Flipper (with `Filetype: Flipper SubGhz`) work transparently — drop them into `/sdcard/lab/subghz/`, they will show up in `subghz_list sd` and be usable by `subghz_info sd` / `subghz_tx sd`.

### 7. Jammer

```
subghz_freq 433.92
subghz_jam
   → "SubGHz jammer ACTIVE on 433.92 MHz. Use 'subghz_stop' to end."
subghz_stop
```

## Adapting across devices

Per-device sizing (waterfall resolution, capture-row pooling, menu tile sizes,
tabbed detail panels on tiny screens) and the keyboard vs touch construction
patterns are in [architecture-reference.md](architecture-reference.md#per-device-sizing-subghz).
Key points: split a captured-key detail into Header/Raw/Decoded tabs on the
Cardputer; use a recycled row pool + virtual scroll for the capture list rather
than one widget per signal; lower the waterfall vertical resolution on small
displays; and on the Cardputer use the dedicated numeric frequency picker
(`subghz_freq_picker_screen`) instead of an on-screen control.
