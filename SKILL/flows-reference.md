# JanOS SubGHz Operational Screen Flows

Implementation-grade runbook for SubGHz UI screens that drive JanOS CC1101
firmware over UART. Use this when implementing a new device UI and you need the
exact command sequence, state/cache, parser tags, concurrency behavior, and
cleanup/handoff rules for each screen.

For command/event syntax see [commands-reference.md](commands-reference.md).
For compact screen inventory see [screens-reference.md](screens-reference.md).
For architecture patterns see [architecture-reference.md](architecture-reference.md).

---

## Shared rules

- Continuous radio modes are mutually exclusive: Listen RX, Scanner, Hunter,
  Weather, and Jammer. Stop the current one with `subghz_stop` before starting
  another.
- `subghz_rx` and `subghz_freq_analyzer hunt` save new captures to **mem** only.
  Promote to SD with `subghz_save`.
- `subghz_list`, `subghz_info`, and `subghz_tx` always need a source:
  `<mem|sd>`.
- SD indices are positional. Re-run `subghz_list sd` after every save/delete/rename.
- Keep firmware `idx` separate from UI row position.
- UI callbacks/tasks must be cleaned up before another screen takes UART RX
  ownership.

Reference implementation roots:

- Tab5: `/Users/jan/kod/tab5/M5MonsterC5-Tab5/main/screens/subghz_*.c`
- CoreS3: `/Users/jan/kod/coreS3/main/screens/subghz_*.c`
- CardputerADV: `/Users/jan/kod/M5MonsterC5-CardputerADV/main/screens/subghz_*.c`

---

## 1. SubGHz menu

### Entry/preconditions

The main app should show the SubGHz menu only after a successful boot probe:
`subghz_status` returns `[SUBGHZ_STATUS] ...`. The menu itself sends no UART.

### State/cache

- Tab5: persistent per-tab `subghz_tab_state_t`, including shared `freq_mhz`
  (default 433.92), page pointers, and per-screen state.
- CoreS3: screen-local/static globals per SubGHz screen.
- Cardputer: menu state is only `selected_index` / `scroll_offset`.

### Navigation

Entries: Listen, Quick Scan, Hunter, SD Signals, Weather, Jammer, Tesla, Settings.
Back returns to the app home screen. Child screens own their own cleanup.

---

## 2. Listen (manual RX)

### Entry/preconditions

User chooses frequency or arrives from Scanner handoff. RF gate comes from NVS
`subghz_rf_settings.listen_rssi_dbm`. Raw/decode mode is UI state.

### Command sequence

| Action | Commands |
|--------|----------|
| Start decoded RX | `subghz_freq <MHz>` -> `subghz_rx rssi=<dbm>` |
| Start RAW RX | `subghz_freq <MHz>` -> `subghz_rx raw rssi=<dbm>` |
| Stop | `subghz_stop` |
| Save capture | `subghz_save <mem_idx>` |
| Replay capture | `subghz_tx <mem_idx> mem` |
| Force raw replay | `subghz_tx <mem_idx> mem raw` |

Tab5/CoreS3 allow manual Start unless the screen was opened with an autostart
flag (Scanner handoff). Cardputer autostarts Listen on screen create.

### State/cache

- Current frequency `freq_mhz` and `raw_mode`.
- Waterfall/activity buffer from `[SUBGHZ_RSSI]`.
- Capture history:
  - Tab5/CoreS3: PSRAM chunk list or virtual row pool for unbounded captures.
  - Cardputer: fixed signal array with mutex and dirty row range.
- Per capture: `idx`, `type`, `freq`, static `id` or rolling `serial/btn`,
  `cnt`, `mf`, `learn`, `te`, `edges`, `name`, duplicate flag.
- Pending status/toast for save, TX, errors.

### Parser tags

| Tag | Behavior |
|-----|----------|
| `[SUBGHZ_RSSI] <dBm>` | Push waterfall/activity sample. |
| `[SUBGHZ_RX] idx=...` | Append decoded capture. Try rolling layout first, then static layout. |
| `[SUBGHZ_RAW] idx=...` | Append RAW capture with `edges`. |
| `[SUBGHZ_RX_DUP] idx=...` | Flash/update existing row, increment hit/duplicate count. |
| `[SUBGHZ_RX_DROP] reason=rssi ...` | Optional debug log; do not show as a main capture. |
| `[KL_DEC]` | Stash KeeLoq decrypted payload; attach to next matching RX row/detail panel. |
| `[KAT_RX]` | Populate rolling-code summary/detail panel. |
| `[SUBGHZ_SAVE]` / `[SUBGHZ_SAVE_ERR]` | Toast/status for save. |
| `[SUBGHZ_TX]` | Toast/status for replay. |

### Concurrency

| Operation while RX running | Behavior |
|----------------------------|----------|
| Save | Tab5/CoreS3 keep RX running and parse save ack in the same stream. Cardputer stops RX before entering the action menu, sends save, then may resume. |
| Replay | Same: Tab5/CoreS3 can send TX while monitor remains; Cardputer stops RX for action. |
| Settings/frequency change | Stop RX first, change settings/freq, restart if requested. |

### Cleanup/handoff

On back/stop: `subghz_stop`, clear callback or kill reader task, delete timers,
free waterfall/capture PSRAM. If captures exist, Tab5 asks for leave confirmation.
Scanner handoff sets frequency, cleans up Scanner first, then opens Listen with
autostart.

---

## 3. Quick Scan / Traffic Scanner

### Entry/preconditions

Scanner has its own RF settings in NVS: dwell, edge threshold, RSSI floor, fast
flag. It does not depend on the current `subghz_freq`; firmware scans its own
frequency list.

### Command sequence

| Action | Commands |
|--------|----------|
| Start | `subghz_scanner dwell=<ms> edges=<n> rssi=<dbm> [fast]` |
| Stop/back | `subghz_stop` |
| Hit tap -> Listen | `subghz_stop` -> `subghz_freq <hit_mhz>` -> open Listen autostart |
| Settings | `subghz_stop` -> open scanner settings -> resume scanner on return if UX wants |

Build the start command with `subghz_rf_build_scanner_cmd()`; do not duplicate
string-building logic in each screen.

### State/cache

- Scanner running flag.
- MRU hit list, usually 6 slots: frequency rounded for display, RSSI, edges,
  last-seen/pass counter.
- Pass stats: `freqs`, `hits`, pulse/animation flag.

### Parser tags

| Tag | Behavior |
|-----|----------|
| `[SUBGHZ_SCAN_START] dwell=... edges=... rssi=... fast=...` | Set header/config display. |
| `[SUBGHZ_SCAN_HIT] freq=... edges=... rssi=...` | Insert/update MRU row; highlight hit. |
| `[SUBGHZ_SCAN_PASS] freqs=N hits=M` | Update pass counter and idle/pulse state. |

### Concurrency

Scanner is exclusive. Do not run list/manage/weather/listen while it is running.
Stop it first. Scanner itself can keep running while UI animates and updates MRU
rows.

### Cleanup/handoff

The important invariant: **cleanup Scanner before opening Listen** so two screens
do not both own UART RX. Handoff sequence:

```text
subghz_stop
subghz_freq <hit_mhz>
scanner_cleanup()
show_listen_at(<hit_mhz>, autostart=true)
```

Cardputer uses a pending frequency/autostart value and pushes Listen onto the
screen stack.

---

## 4. Hunter / Frequency Analyzer with auto-capture

### Entry/preconditions

Hunter settings in NVS: trigger dBm, timeout, raw vs decode, single, fast.
Fresh entry clears history; returning from settings can use a resume entry that
keeps captured rows.

### Command sequence

| Action | Commands |
|--------|----------|
| Start decode hunt | `subghz_freq_analyzer <trigger> hunt [single] [fast] timeout=<ms>` |
| Start raw hunt | `subghz_freq_analyzer <trigger> raw [fast] timeout=<ms>` |
| Scan-only analyzer | `subghz_freq_analyzer <trigger> [fast]` |
| Stop | `subghz_stop` |
| Save capture | `subghz_save <mem_idx>` |
| Replay capture | `subghz_tx <mem_idx> mem [raw]` |

Build with `subghz_rf_build_hunter_cmd()`.

### State/cache

- Running flag and hunter status string.
- Last FA hit frequency/RSSI/stage.
- Capturing spinner state: frequency, stage, timeout, mode.
- Capture history (PSRAM dynarr/chunks on touch devices; fixed array on Cardputer).
- Miss/duplicate/error counters if exposed.

### Parser tags

| Tag | Behavior |
|-----|----------|
| `[SUBGHZ_FA_START] trigger=... hunt=... raw=... single=... fast=... tmo=...` | Set mode header. |
| `[SUBGHZ_FA] freq=... rssi=... stage=coarse|fine` | Update last-hit display/waterfall. |
| `[SUBGHZ_FA] hunt capture freq=... timeout=... mode=...` | Spinner ON. |
| `[SUBGHZ_RX]` / `[SUBGHZ_RAW]` | Spinner OFF, append capture row. |
| `[SUBGHZ_RX_DUP]` | Spinner OFF, flash/update duplicate. |
| `[SUBGHZ_FA] hunt timeout` | Spinner OFF, count miss. |
| `[SUBGHZ_FA] hunt duplicate` | Spinner OFF, toast duplicate. |
| `[SUBGHZ_FA] hunt error` | Spinner OFF, error banner. |
| `[SUBGHZ_FA] silent` | Idle indicator / clear active hold. |
| `[KL_DEC]`, `[KAT_RX]`, `[KAT_DBG]` | Detail/debug panel just like Listen. |
| `[SUBGHZ_SAVE]`, `[SUBGHZ_SAVE_ERR]`, `[SUBGHZ_TX]` | Status even if hunt stopped. |

### Concurrency

Hunter can continue while the user saves or replays a captured mem entry on
Tab5/CoreS3; the UART parser must handle SAVE/TX acks before the
`hunter_running` gate. Cardputer usually stops RX while in action menus.

Do not open Manage or settings while Hunter is running without stopping it.
Settings handoff: stop Hunter, open settings, then use a resume entry that keeps
history and restarts if desired.

### Cleanup

`subghz_stop`, kill reader/clear callback, delete timers. If history has captures
and user presses back, Tab5/CoreS3 ask for confirmation before clearing.

---

## 5. Manage / SD Signals

### Entry/preconditions

SD card must be mounted on the JanOS side. Manage operates on the persistent
`sd` library only; mem captures are promoted here via `subghz_save` from Listen
or Hunter.

### Command sequence

| Action | Commands |
|--------|----------|
| Open/refresh | `subghz_list sd` |
| Inspect detail | `subghz_info <idx> sd` |
| Replay | `subghz_tx <idx> sd` |
| Force raw replay | `subghz_tx <idx> sd raw` |
| Rename | `subghz_rename <idx> <new_name>` -> refresh list |
| Delete | `subghz_delete <idx>` -> refresh list |
| Clear all (Cardputer pattern) | loop `subghz_delete 1` until `remaining=0` |

### State/cache

- SD signal list: positional `idx`, type, freq, fields, `name`.
- Selected row / detail panel.
- Mutation status: rename/delete/TX success/error.
- Build timer or virtual row window for large SD libraries.

### Parser tags

| Tag | Behavior |
|-----|----------|
| `[SUBGHZ_LIST] idx=... source implicit` | Append row. |
| `[SUBGHZ_LIST_END] count=N source=sd` | End refresh. |
| `[SUBGHZ_INFO]` / `[SUBGHZ_INFO_RAW]` / `[SUBGHZ_INFO_END]` | Fill detail/raw panel. |
| `[SUBGHZ_INFO_ERR]` | Show error. |
| `[SUBGHZ_RENAME]` / `[SUBGHZ_RENAME_ERR]` | Status; refresh on success. |
| `[SUBGHZ_DELETE]` / `[SUBGHZ_DELETE_ERR]` | Status; refresh on success. |
| `[SUBGHZ_TX]` | Replay toast. |

### Concurrency

Manage is not a continuous radio mode, but it still owns the UART response stream
while listing or mutating. Tab5 has a special coordination pattern: the
background Manage reader handles mutation acks, but is paused while a synchronous
`subghz_list sd` collector runs, so the reader does not steal `[SUBGHZ_LIST]`
lines. CoreS3 uses `uart_start_collect("[SUBGHZ_LIST_END]", cb)` for the list.
Cardputer uses one line callback and routes lines based on a `collecting_list`
flag.

### Cleanup

No `subghz_stop` is required for ordinary list/detail screens unless a repeat TX
or previous mode is still active. Clear callbacks/tasks and free signal arrays on
exit. After every mutation, refresh `subghz_list sd` before trusting indices.

---

## 6. Weather

### Command sequence

| Action | Commands |
|--------|----------|
| Open/start | `subghz_weather` |
| Back/stop | `subghz_stop` |

### State/cache

- Sensor rows keyed by `(proto, id, channel)`.
- Usually 8 visible/LRU slots: protocol, ID, channel, temp, humidity, battery,
  last-seen age.
- Start frequency from `[SUBGHZ_WEATHER_START]`.

### Parser tags

| Tag | Behavior |
|-----|----------|
| `[SUBGHZ_WEATHER_START] freq=433.92` | Set header/listening state. |
| `[SUBGHZ_WEATHER] proto=... id=0x... ch=... temp=... hum=... batt=...` | Upsert sensor row; dedupe by key. |

### Concurrency

Weather is exclusive and continuous. Do not run Manage/List/Hunter/Listen while
Weather is active; send `subghz_stop` first.

### Cleanup

Send `subghz_stop`, clear callback/reader, delete timers and sensor table.

---

## 7. Jammer

### Command sequence

| Action | Commands |
|--------|----------|
| Start | `subghz_freq <MHz>` -> `subghz_jam` |
| Stop/back | `subghz_stop` |
| Change frequency | `subghz_stop` -> update freq -> `subghz_freq <MHz>` -> `subghz_jam` |

### State/cache

- Frequency (shared with Listen on Tab5, screen-local on Cardputer/CoreS3).
- Jamming/running flag.
- Local-only status label; firmware output is usually just the human start line.

### Parser tags

No structured parser required. You can optionally show
`SubGHz jammer ACTIVE on ...`.

### Cleanup

Always send `subghz_stop` if jamming, even if user navigates away.

---

## 8. Tesla

### Command sequence

| Action | Commands |
|--------|----------|
| Fire | `subghz_freq 315.00` -> `subghz_tx tesla` |

No persistent running mode and no parser is required. The UI sets a local
“Signal sent” status. If you want confirmation, watch for `[SUBGHZ_TX]`.

---

## 9. Frequency correction / SubGHz settings

### Command sequence

| Action | Commands |
|--------|----------|
| Open correction screen | `subghz_get_freq_correction` |
| Apply | `subghz_set_freq_correction <signed_mhz>` |

### State/cache

- Current correction in MHz or centi-MHz.
- UI rollers/buttons or keyboard step value.
- Pending status until firmware echoes correction.

### Parser tags

`[SUBGHZ_FREQ_CORRECTION] +0.05` -> update local value and status.

### Cleanup

No `subghz_stop`; this is a one-shot query/set screen. Clear callbacks/tasks on
exit.

---

## 10. RF settings sub-screens

These screens edit local NVS only and send no UART directly.

| Settings screen | Stored fields | Used by |
|-----------------|---------------|---------|
| Listen settings | `listen_rssi_dbm` | `subghz_rx [raw] rssi=<dbm>` |
| Scanner settings | `scanner_dwell_ms`, `scanner_edges`, `scanner_rssi_dbm`, `scanner_fast` | `subghz_rf_build_scanner_cmd()` |
| Hunter settings | `hunter_trigger_dbm`, `hunter_timeout_ms`, `hunter_raw`, `hunter_single`, `hunter_fast` | `subghz_rf_build_hunter_cmd()` |

### Handoff rules

- If opened from a running continuous screen, stop that mode first.
- On return, reload NVS settings.
- Hunter/Scanner can use a resume entry to preserve history/rows and restart the
  command with the new settings.

---

## 11. Cardputer frequency picker

### Entry/preconditions

Cardputer has no touch rollers, so Listen/Jammer push a dedicated frequency
picker screen. It is UI-only.

### Flow

| Step | Action |
|------|--------|
| 1 | Parent stops RX/jam if needed and pushes picker with initial freq + callback. |
| 2 | User selects preset (`315`, `433.92`, `868`, `915`) or Custom. |
| 3 | Custom opens text input, validates `0 < freq <= 9999.99`. |
| 4 | Picker pops and invokes `on_pick(freq, user_data)`. |
| 5 | Parent sends `subghz_freq <freq>` and optionally restarts RX/jam. |

### State/cache

Picker stores only current selection and callback params. Parent owns the actual
frequency state.

---

## 12. UART ownership matrix

| Screen | Continuous radio? | Owns UART how? | Secondary operations |
|--------|-------------------|----------------|----------------------|
| Listen | yes | reader task / line callback | Save/TX can run through same stream on touch; Cardputer stops RX for actions. |
| Scanner | yes | reader task / line callback | Stop before handoff/settings. |
| Hunter | yes | reader task / line callback | Save/TX can run while hunting on touch; stop before settings/manage. |
| Manage | no | collect/list callback | Pause any background reader while collecting list. |
| Weather | yes | reader task / line callback | Exclusive until `subghz_stop`. |
| Jammer | yes | local state, minimal RX | Exclusive until `subghz_stop`. |
| Tesla | no | fire-and-forget | Optional `[SUBGHZ_TX]` ack. |
| Freq correction | no | one-shot callback/task | No `subghz_stop`. |

Practical invariant: before starting any new continuous `subghz_*` mode, send
`subghz_stop`, flush stale UART input if your transport supports it, then start
the new command and install exactly one parser owner.
