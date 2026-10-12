# JanOS SubGHz UART Command Reference

Complete reference of every `subghz_*` command supported by the `janos_subghz` component running on ESP32-C5 with a CC1101 radio, plus related JanOS system commands used by the SubGHz UI.

Commands are sent over UART as plain text terminated with `\r\n`. Responses are line-based text and **all GUI-relevant SubGHz events are tagged with `[SUBGHZ_*]`, `[KAT_RX]`, `[KL_DEC]`, `[KL_GROUND]`, `[KAT_DBG]`** so a UI can `strstr()` them out of the rest of the firmware log.

**Indexing convention**: All key indices are **1-based**.

---

## Storage model (mem vs sd)

Signals live in two independent stores. **Every command that touches an
individual signal — `subghz_list`, `subghz_info`, `subghz_tx` — takes an
explicit `<mem|sd>` source argument.**

| Tier  | Backed by                          | Filled by                                              | `idx=` semantics                                                       | Lifetime                  |
|-------|------------------------------------|--------------------------------------------------------|------------------------------------------------------------------------|---------------------------|
| `mem` | Dynamic PSRAM cache, no fixed cap. | Auto-save inside `subghz_rx` and `subghz_freq_analyzer hunt`. | Monotonic `capture_seq` (1-based) — same number shown in `[SUBGHZ_RX]`. | Wiped by reboot or `subghz_clear`. |
| `sd`  | `/sdcard/lab/subghz/*.sub` text files. | Deliberate `subghz_save <mem_idx>` / `subghz_save all` only. | 1..N positional within the current directory enumeration (sorted by leading `NNNNN_` prefix then alphabetically). | Persistent across reboot. |

Rules:

- `subghz_rx` and `subghz_freq_analyzer hunt` write only to `mem`. There is no
  automatic SD persistence and no `[SUBGHZ_TRACE]` event.
- `subghz_save <mem_idx>|all` is the only way to copy a `mem` signal into the
  SD library. The original `mem` entry is left untouched (you can re-save or
  delete the mem cache later).
- `subghz_delete <sd_idx>` removes a file from the SD library.
- `subghz_rename <sd_idx> <new_name>` renames both the filename and the
  `Name:` field inside the `.sub` file.
- `subghz_clear` empties the mem cache; the SD library is intentionally left
  alone (delete individual files with `subghz_delete`).
- `sd_idx` is positional and changes after every `subghz_save` /
  `subghz_delete` / `subghz_rename`. UIs should re-issue `subghz_list sd`
  right after each mutation.

---

## Boot output (informational only — not GUI events)

When the firmware boots and initializes the SubGHz subsystem you'll see lines like:

```
[BOARD] name=TAB5-CC1101-R2-0042
[subghz] CC1101 chip: PARTNUM=0x00 VERSION=0x14 (expect 0x00/0x14)
[subghz] Capture buffers: 8192 entries (32 KB each) in PSRAM
[subghz] Regs: MDMCFG2=0x30 PKTCTRL0=0x32 AGCCTRL2=0x07 IOCFG0=0x0D MARC=0x0D
[KAT] Keystore loaded: 84 manufacturer keys
[subghz] Timer self-test: 1000us delay measured as 1002 us
[subghz] CC1101 initialized on SPI2 (CS=3 GDO0=4) @ 433.92 MHz
```

These lines are diagnostic. The UI may surface them in a verbose log drawer but should not parse them as SubGHz state. `[BOARD] name=<unset>` means BLK5 / KEY1 does not contain a valid board label.

---

## Status & Frequency

### `subghz_status`
- **Syntax**: `subghz_status`
- **Description**: One-shot status of the CC1101 driver.
- **Output** (single line):
```
[SUBGHZ_STATUS] mode=<Idle|Receive|Transmit|Jam|Analyzer> freq=<MHz> keys=<N> rssi=<dBm>
```
- **Parse**: `sscanf(line, "[SUBGHZ_STATUS] mode=%15s freq=%f keys=%d rssi=%d", mode, &freq, &keys, &rssi);`

### `subghz_freq`
- **Syntax**: `subghz_freq` (read) or `subghz_freq <MHz>` (set)
- **Description**: Reads or sets operating frequency for all SubGHz operations (RX, TX, Jam). Does **not** affect the Frequency Analyzer scan list (the analyzer iterates its own list).
- **Examples**: `subghz_freq`, `subghz_freq 433.92`, `subghz_freq 868.35`, `subghz_freq 315.00`
- **Output**:
```
[SUBGHZ_FREQ] 433.92
```
- **Valid range**: CC1101 supports 300–348, 387–464, 779–928 MHz. Out-of-range values are rejected with an error.

### `subghz_set_freq_correction`
- **Syntax**: `subghz_set_freq_correction <MHz>`
- **Description**: Sets a signed crystal-trim correction (MHz) that is added to the requested carrier before the FREQ2/FREQ1/FREQ0 registers are programmed. Applies transparently to **every** radio operation: `subghz_freq`, `subghz_rx`, `subghz_tx`, `subghz_freq_analyzer` (coarse + fine + hunt), `subghz_scanner`, `subghz_weather`, `subghz_jam`, and the Tesla burst sequence. Persisted in NVS (namespace `"subghz"`, key `"freq_corr_cc"` as int32 in units of 0.01 MHz) and reloaded by `subghz_init()` after every reboot.
- **Examples**: `subghz_set_freq_correction 0.05`, `subghz_set_freq_correction -0.12`, `subghz_set_freq_correction 0.00`
- **Output**:
```
[SUBGHZ_FREQ_CORRECTION] +0.05
```
- **Precision**: input is quantised to 2 decimal places (centi-MHz). `0.00` clears any previous correction.
- **Valid range**: `-5.00..+5.00 MHz`. Out-of-range / NaN / Inf values are rejected with an error and NVS is left untouched.
- **Live re-program**: when called with the radio idle, registers are immediately re-programmed using `current_freq + new_correction`. When called mid-RX/TX/FA, the next register write inside the running task picks up the new offset automatically.

### `subghz_get_freq_correction`
- **Syntax**: `subghz_get_freq_correction`
- **Description**: Prints the current persisted CC1101 frequency correction (MHz). Same output format as the set command.
- **Output**:
```
[SUBGHZ_FREQ_CORRECTION] +0.00
```

---

## Receive

### `subghz_rx`
- **Syntax**: `subghz_rx [raw] [rssi=-DBM|-DBM]`
  - Arguments are positional but order-independent.
  - `raw`: skip decoder dispatch and save raw edges only.
  - `rssi=-DBM`: burst peak RSSI must be `>=` this value or the burst is dropped.
  - Bare negative dBm tokens are also accepted, e.g. `-85` is equivalent to `rssi=-85`.
  - Default RSSI gate: `-80 dBm`.
  - Valid RSSI gate range: `-120..-40`. Invalid values, omitted values, and `0` fall back to `-80`.
- **Description**: Starts CC1101 receiver on the current frequency. Auto-saves new unique signals to NVS. Streams RSSI at ~1 Hz for waterfall display (peak RSSI for the noise gate is still sampled every 10 ms internally). Without `raw`: tries protocol decoding first; on failure falls back to RAW. With `raw`: skips decoding and saves raw edge data only.
- **RSSI noise gate**: cheap / clone / detuned CC1101 modules push their noise floor up to ~-90 dBm, which lets thermal noise cross the OOK slicer and produce 8–60-edge phantom bursts. The default `-80 dBm` gate filters those out without losing real signals (real fobs are typically `-45..-70 dBm`). On a clean module you'll never see `[SUBGHZ_RX_DROP]`; on a noisy one it fires every few seconds. Pass `rssi=-95` (or `rssi=-120` to disable) when you genuinely need weak / far-away signals.
- **Start output**:
```
SubGHz receive mode active on 433.92 MHz (rssi gate=-80 dBm). Use 'subghz_stop' to end.
SubGHz RAW capture mode active on 433.92 MHz (rssi gate=-85 dBm). Use 'subghz_stop' to end.
```
- **Continuous output** (any of these, in any order):
```
[SUBGHZ_RSSI] -45
[SUBGHZ_RX] idx=1 type=HOLTEK freq=433.92 bits=12 id=AABBCC te=270 proto=HOLTEK learn=- mf=- cnt=0
[SUBGHZ_RX] idx=2 type=KeeLoq freq=433.85 bits=65 serial=0x04DEC1 btn=2 proto=KeeLoq learn=MAGIC_XOR_T1 mf=Leopard cnt=37188 te=355
[SUBGHZ_RX_DUP] idx=1 type=HOLTEK freq=433.92 id=AABBCC proto=HOLTEK learn=- mf=- cnt=0
[SUBGHZ_RX_DUP] idx=2 type=KeeLoq freq=433.85 serial=0x04DEC1 cnt=37189 learn=MAGIC_XOR_T1 mf=Leopard
[SUBGHZ_RAW] idx=3 freq=433.92 edges=128
[SUBGHZ_RX_DROP] reason=rssi peak=-87 th=-80 edges=23
[KL_DEC] bits=65 te_auto=400 fix=0x2004DEC1 hop=0x3B760601 plain=0x22C19144 learn=4 mf=Leopard cnt=37188
[KAT_RX] KeeLoq decoded+decrypted: serial=0x04DEC1 btn=2 cnt=37188 mf=Leopard learn=MAGIC_XOR_T1
[KAT_DBG] decode failed: KL step=0 bits=0 hc=0 te_auto=0 | SL step=0 bits=0 hc=0 | FLOR step=0 bits=0 hc=0
```
- **Events**:
  - `[SUBGHZ_RSSI] <dBm>` — RSSI for waterfall (~1 Hz cadence).
  - `[REPLAY_SEG] start=N len=N type=NAME deep=0\|1 static=0\|1 score=N` — one line per successful segmented decode (before `SubGHz: key saved` / `[SUBGHZ_RX]`).
  - `[SUBGHZ_RX]` — new key saved. Two field layouts:
    - **Static / fixed-code**: `idx=N type=NAME freq=MHz bits=N id=HEX te=N proto=NAME learn=NAME mf=NAME cnt=N`
    - **Rolling-code**: `idx=N type=NAME freq=MHz bits=N serial=0xN btn=N proto=NAME learn=NAME mf=NAME cnt=N te=N`
  - `[SUBGHZ_RX_DUP]` — duplicate of an existing saved key. References its `idx`.
  - `[SUBGHZ_RAW]` — saved as raw edges (decoder failed or `raw` mode). Fields: `idx=N freq=MHz edges=N`.
  - `[SUBGHZ_RX_DROP] reason=rssi peak=<dBm> th=<dBm> edges=N` — burst rejected by the noise gate. Fields: `peak` = max RSSI observed during the burst, `th` = current threshold, `edges` = how many edges were in the dropped burst. Safe for the UI to ignore; useful for a debug pane.
  - `[KL_DEC]` — KeeLoq‑specific decoder dump emitted **before** the matching `[KAT_RX]` / `[SUBGHZ_RX]`.
  - `[KAT_RX]` — rolling‑code dispatcher result line ("X decoded+decrypted" or "X captured").
  - `[KAT_DBG]` — informational decode-failure trace (KeeLoq/StarLine/FloR-S all said NONE).
- **Examples**:
  - `subghz_rx` — listen, decode + auto-save, default `-80 dBm` gate.
  - `subghz_rx raw` — raw capture only, default gate.
  - `subghz_rx -65` — decode, stricter gate; only strong bursts pass.
  - `subghz_rx rssi=-85` — decode, looser gate (good antenna, weak fobs).
  - `subghz_rx raw rssi=-85` — raw capture with a looser gate.
  - `subghz_rx raw -120` — raw + gate effectively disabled (capture absolutely everything).
- **Stop**: `subghz_stop`.

---

## Transmit

### `subghz_tx`
- **Syntax**: `subghz_tx <index> <mem|sd> [raw]` or `subghz_tx tesla`
- **Description**: Replays a stored signal. The `<mem|sd>` source selects the store (mem cache or `/sdcard/lab/subghz/` library). With trailing `raw`: re-emits the captured raw edges verbatim, bypassing protocol re-encoding (useful for rolling codes when you want to replay the *exact* OTA frame instead of bumping the counter).
- **Examples**: `subghz_tx 1 mem`, `subghz_tx 1 mem raw`, `subghz_tx 3 sd`, `subghz_tx tesla`
- **Output**:
```
[SUBGHZ_TX] idx=1 source=mem done
```
- **Errors**: `"Invalid source"`, `"Failed to load signal N from <mem|sd>"`, `"SubGHz not initialized"`, `"Key has no transmittable data"`.
- **Notes**: For mem-source TX of a KeeLoq/StarLine key, the rolling counter is bumped and — if a corresponding `.sub` file already exists in `/sdcard/lab/subghz/<name>.sub` — that file is silently rewritten so the saved copy stays in sync.

---

## Jammer

### `subghz_jam`
- **Syntax**: `subghz_jam`
- **Description**: Continuous jamming on the current frequency (CC1101 unmodulated TX). Set the frequency first with `subghz_freq`.
- **Output**:
```
SubGHz jammer ACTIVE on 433.92 MHz. Use 'subghz_stop' to end.
```
- **Stop**: `subghz_stop`.

---

## Frequency Analyzer (Flipper-style scan + auto-capture)

The analyzer is a Flipper Momentum port. It performs a **two-stage scan** identical to Flipper's Frequency Analyzer, with optional auto-capture ("hunt mode") that demodulates a hit, decodes it, and saves it into the keystore — exactly like `subghz_rx` would, but scoped to one captured burst per detected hit.

### `subghz_freq_analyzer`
- **Syntax**: `subghz_freq_analyzer [trigger_dbm] [hunt|raw] [single] [fast] [debug] [timeout=MS|MSms]`
  - All args are positional but order-independent.
  - `trigger_dbm`: negative dBm in **-120 … -40** (e.g. `-85`, `-90`). Default: **-85 dBm**. Other numeric tokens are ignored for trigger.
  - `hunt`: enable auto-capture with **decode** (will save the most likely protocol or fall back to RAW).
  - `raw`: enable auto-capture in **raw-only** mode (skip decoding, save edges).
  - `hunt` and `raw` are mutually exclusive — passing either turns hunt on. `raw` implies `hunt`.
  - `single`: **decode hunt only** (use with `hunt`, not `raw`). Ends capture after **one OOK burst + ~100 ms silence** (raw-edge ISR). Without `single`, decode hunt uses Flipper/RCSwitch **double-gap** framing (typically needs two button presses or a long hold).
  - `fast`: **Shorter RSSI settle** per scan step (~800 µs vs ~2000 µs). With hunt enabled, also enables **sticky** resample: before each coarse pass the last hunt hit frequency is sampled first for faster re-lock.
  - `debug`: emit **`[SUBGHZ_FA_DIAG]`** after each `[SUBGHZ_FA]` hit — raw fine peak, filter/snap pipeline, top-3 fine bins, and RSSI probe on the two adjacent Flipper list entries around the peak. Use to tell **hardware LO offset** from **snap / 20 kHz step** artifacts. Adds ~2 extra tune steps per fine hit.
  - `timeout=MS` or `NNNNms` (e.g. `timeout=3500`, `2500ms`): per-hit capture window **100 … 60000 ms**; invalid or omitted → **2000 ms** default.
  - Plain `hunt` (no `single`): still uses double-gap capture; **RX after hit** uses a lighter preset switch (no full chip `SRES`) for lower latency than older builds.

- **Examples**:
```
subghz_freq_analyzer                      # scan-only, default trigger -85 dBm
subghz_freq_analyzer -90                  # scan-only, sensitive trigger
subghz_freq_analyzer hunt                 # scan + auto-capture + decode (default trigger)
subghz_freq_analyzer hunt single fast     # decode hunt: one press + faster scan + sticky
subghz_freq_analyzer hunt timeout=3000   # decode hunt, 3 s capture window
subghz_freq_analyzer hunt 2500ms         # same (suffix ms)
subghz_freq_analyzer raw                  # scan + auto-capture, raw timings only
subghz_freq_analyzer -80 hunt             # custom trigger + decode
subghz_freq_analyzer raw -75              # custom trigger + raw, args reversible
subghz_freq_analyzer fast                 # scan-only but faster coarse/fine steps
subghz_freq_analyzer -80 debug            # sensitive trigger + MHz diagnostics
```

- **Frequency diagnostics (`debug`)** — emitted only with `debug`, throttled when `fine_peak` is unchanged within **10 kHz**:
```
[SUBGHZ_FA] freq=433.8890 rssi=-72 stage=fine
[SUBGHZ_FA_DIAG] coarse=433.8890 coarse_rssi=-68 fine_peak=433.8890 fine_rssi=-72 top3=433.889:-72,433.909:-75,433.929:-78 filt_hz=433889000 round_hz=433889000 snapped=433.8890 snap_err_hz=0 pair=433.889:-72,433.920:-65 est_offset_khz=31
```

| Field | Meaning |
|-------|---------|
| `coarse` / `coarse_rssi` | Stage-1 list winner (650 kHz BW) |
| `fine_peak` / `fine_rssi` | Stage-2 sweep bin with max RSSI **before** filter/snap |
| `top3` | Three strongest fine bins (20 kHz steps) |
| `filt_hz` / `round_hz` | After Flipper `filVal` and `round_int(3)` |
| `snapped` | Nearest `s_fa_freq_list[]` entry (same as `[SUBGHZ_FA] freq`) |
| `snap_err_hz` | `snapped` minus `round_hz` |
| `pair` | Extra RSSI at the two list entries bracketing `fine_peak` |
| `est_offset_khz` | Offset from `fine_peak` toward the louder `pair` entry (kHz) |

**How to read** (compare with a known TX frequency, e.g. HackRF @ 433.920 MHz):

- **`est_offset_khz` ≈ 31** and **`pair`** shows stronger RSSI on **433.920** than on **433.889** while **`fine_peak`=433.889** → **CC1101 LO offset** (~+31 kHz vs programmed MHz); not a wrong transmitter.
- **`fine_peak`** near **433.909/433.929** but **`snapped`=433.889** → **snap** or filter (check `filt_hz` vs `round_hz`).
- **`top3`** peak on **433.909** with similar **`pair`** RSSI → **20 kHz fine step** quantization; not necessarily hardware offset.

Coarse-only hits with `debug` emit a shorter line: `stage=coarse note=no_fine`.

- **Behaviour**:
  - **Stage 1 — Coarse scan**: iterates the Flipper Momentum default frequency list (length printed as `%u freqs` on task start) with 650 kHz RX bandwidth, skipping a small blacklist (`462.75`, `464.00`, `467.75`, `311.9–312.2 MHz`, anything `>920 MHz`). Tracks the strongest signal above `trigger_dbm`. Per-step RX settle: **~2000 µs** normally, **~800 µs** with `fast`.
  - **Stage 2 — Fine scan**: when a coarse hit is above trigger, sweeps ±300 kHz around it in 20 kHz steps with 58 kHz RX bandwidth and emits the strongest fine bin (same settle timing as coarse).
  - **Frequency processing**: **fine** hits use adaptive averaging in Hz (`filVal`, reset on `silent` or when raw fine jumps >200 kHz from filtered value) → **`round_int` on first lock** (3 Hz digits) → **snap** to `s_fa_freq_list[]`. **Coarse-only** hits use snap/round only (no `filVal` update) so a wrong 650 kHz list neighbour cannot pull fine results to e.g. 433.657 when TX is at 433.92.
  - **Sample-hold**: keeps a hit "active" for a few cycles to debounce dropouts; when it expires without a refresh, emits a `silent` line and clears the frequency filter.
  - **Hunt mode** (when `hunt` or `raw` is set): on each fine/coarse hit the firmware switches the CC1101 from Analyzer preset to the **OOK 650 kHz async RX** preset (without full chip reset), arms the GDO0 ISR, waits up to the configured **timeout** (default **2000 ms**) for a burst, then either runs the decoder pipeline (decode mode) or packages raw edges (raw mode). After the capture window, restores the Analyzer preset and resumes scanning.

- **Lifecycle output**:
```
[subghz] Frequency Analyzer task started (trigger=-85 dBm, 62 freqs, hunt=1 raw=0 single=0 fast=0 debug=0 tmo=2000ms)
[SUBGHZ_FA_START] trigger=-85 hunt=1 raw=0 single=0 fast=0 debug=0 tmo=2000ms
Frequency analyzer active. Use 'subghz_stop' to end.
... (continuous events, see below) ...
[subghz] Frequency Analyzer task stopped
```
  - The `62 freqs` value is illustrative; firmware prints the actual `FA_FREQ_COUNT`. `single`, `fast`, and `tmo` reflect the selected options.

- **Continuous events**:

| Line | Meaning | Parse |
|------|---------|-------|
| `[SUBGHZ_FA_START] trigger=<dBm> hunt=<0\|1> raw=<0\|1> single=<0\|1> fast=<0\|1> debug=<0\|1> tmo=<ms>ms` | Analyzer started (one-shot) | `sscanf(line, "[SUBGHZ_FA_START] trigger=%d hunt=%d raw=%d single=%d fast=%d debug=%d tmo=%dms", ...)` |
| `[SUBGHZ_FA] freq=<MHz> rssi=<dBm> stage=<coarse\|fine>` | Hit above trigger; `freq` is snapped to the nearest Flipper list entry (not the raw fine/coarse bin). `fine` is more accurate before snap. | `sscanf(line, "[SUBGHZ_FA] freq=%f rssi=%d stage=%7s", &f, &rssi, stage)` |
| `[SUBGHZ_FA_DIAG] ...` | Optional MHz pipeline debug (only with CLI `debug`); see table above | grep / manual parse |
| `[SUBGHZ_FA] hunt capture freq=<MHz> stage=<coarse\|fine> timeout=<ms>ms mode=<decode\|raw>` | Hunt mode armed a capture window on this frequency. UI: show "capturing…" indicator. | `sscanf(line, "[SUBGHZ_FA] hunt capture freq=%f stage=%7s timeout=%dms mode=%7s", &f, stage, &to, mode)` |
| `[SUBGHZ_FA] hunt timeout (no burst captured)` | The capture window expired without seeing edges. UI: clear "capturing…" indicator. | literal substring |
| `[SUBGHZ_FA] hunt error (alloc/save)` | Capture buffer alloc failed or NVS save failed. | literal substring |
| `[SUBGHZ_FA] hunt duplicate (already in keystore)` | Burst was captured but matched an existing key (dedup). | literal substring |
| `[SUBGHZ_FA] silent (last freq=<MHz> rssi=<dBm>)` | Sample-hold expired; nothing detected for the cooldown window. | `sscanf(line, "[SUBGHZ_FA] silent (last freq=%f rssi=%d)", &f, &rssi)` |

- **Hunt mode also emits the standard receive events**, exactly as `subghz_rx` would, between `hunt capture` and the terminator (`[SUBGHZ_RX]` / `[SUBGHZ_RAW]` / `[SUBGHZ_RX_DUP]` / `hunt timeout`):
  - `[KL_DEC] ...`
  - `[KAT_RX] ...`
  - `[KAT_DBG] decode failed: ...`
  - `[SUBGHZ_RX] idx=N type=... freq=... ... name=BASENAME` (decode mode, decoded)
  - `[SUBGHZ_RAW] idx=N freq=... edges=N name=BASENAME` (decode failed → raw fallback, or raw mode)
  - `SubGHz: key saved at index N` (legacy human-readable line, optional to parse)
  - `[REPLAY_SEG] start=N len=N type=...` — decode segment summary (one per successful capture).
  - `[subghz]` RCSwitch timing lines (`RAW t[0..9]:`, `TE corrected:`, `Reclassified to proto=...`) — **off by default**; `subghz_debug rc_dbg on` or `subghz_replay_test` only.
  - Every `[SUBGHZ_RX]` / `[SUBGHZ_RAW]` / `[SUBGHZ_RX_DUP]` carries a trailing `name=BASENAME` field — the human-readable name of the in-memory entry, mutable via `subghz_rename`. Use it as a stable display label.

- **Capture window state machine** (per hit, hunt mode; `timeout=` value comes from CLI / defaults):
```
[SUBGHZ_FA] freq=… rssi=… stage=…
[SUBGHZ_FA] hunt capture freq=… stage=… timeout=2000ms mode=decode
   │
   ├─→ (decode success)        [KL_DEC] / [KAT_RX] / [SUBGHZ_RX]
   ├─→ (decode failure → raw)  [KAT_DBG] / [SUBGHZ_RAW]
   ├─→ (no edges)              [SUBGHZ_FA] hunt timeout (no burst captured)
   ├─→ (dedup)                 [SUBGHZ_FA] hunt duplicate (already in keystore)
   └─→ (alloc/save fail)       [SUBGHZ_FA] hunt error (alloc/save)
[SUBGHZ_FA] silent (last freq=… rssi=…)   ← (when sample-hold expires later)
```

- **Annotated hunt-mode example** (matches the user-visible log; `hunt` without `single` — legacy double-gap framing):
```
> subghz_freq_analyzer hunt
[subghz] CC1101 chip: PARTNUM=0x00 VERSION=0x14 (expect 0x00/0x14)            ← boot diag
[subghz] Capture buffers: 8192 entries (32 KB each) in PSRAM                  ← boot diag
[subghz] Regs: MDMCFG2=0x30 PKTCTRL0=0x32 AGCCTRL2=0x07 IOCFG0=0x0D MARC=0x0D ← boot diag
[KAT] Keystore loaded: 84 manufacturer keys                                   ← boot diag
[subghz] Timer self-test: 1000us delay measured as 1002 us                    ← boot diag
[subghz] CC1101 initialized on SPI2 (CS=3 GDO0=4) @ 433.92 MHz                ← boot diag
[subghz] Frequency Analyzer task started (trigger=-85 dBm, 62 freqs, hunt=1 raw=0 single=0 fast=0 tmo=2000ms)  ← lifecycle
[SUBGHZ_FA_START] trigger=-85 hunt=1 raw=0 single=0 fast=0 tmo=2000ms        ← GUI: enter "FA Hunt" state
Frequency analyzer active. Use 'subghz_stop' to end.                          ← human hint
> [SUBGHZ_FA] freq=433.8489 rssi=-50 stage=fine                               ← GUI: hit @ 433.85 MHz
[SUBGHZ_FA] hunt capture freq=433.8489 stage=fine timeout=2000ms mode=decode  ← GUI: spinner ON
[KL_DEC] bits=65 te_auto=400 fix=0x2004DEC1 hop=0x3B760601 plain=0x22C19144 learn=4 mf=Leopard cnt=37188
[KAT_RX] KeeLoq decoded+decrypted: serial=0x04DEC1 btn=2 cnt=37188 mf=Leopard learn=MAGIC_XOR_T1
SubGHz: key saved at index 1                                                  ← legacy human line
[SUBGHZ_RX] idx=1 type=KeeLoq freq=433.85 bits=65 serial=0x04DEC1 btn=2 proto=KeeLoq learn=MAGIC_XOR_T1 mf=Leopard cnt=37188 te=355  ← GUI: spinner OFF, append row idx=1
[SUBGHZ_FA] freq=433.657 rssi=-44 stage=coarse                                ← GUI: hit @ 433.657 MHz
[SUBGHZ_FA] hunt capture freq=433.6571 stage=coarse timeout=2000ms mode=decode← GUI: spinner ON
[SUBGHZ_FA] hunt timeout (no burst captured)                                  ← GUI: spinner OFF, miss
[SUBGHZ_FA] silent (last freq=433.657 rssi=-44)                               ← GUI: idle
[SUBGHZ_FA] freq=433.9088 rssi=-60 stage=fine
[SUBGHZ_FA] hunt capture freq=433.9088 stage=fine timeout=2000ms mode=decode
[REPLAY_SEG] start=317 len=27 type=HOLTEK deep=0 static=0 score=1             ← one line per decode hit
SubGHz: key saved capture_seq=2                                             ← legacy human line
[SUBGHZ_RX] idx=2 type=HOLTEK freq=433.91 bits=12 id=3F0A te=337 proto=HOLTEK learn=UNKNOWN mf=- cnt=0    ← GUI: append row idx=2
[SUBGHZ_FA] freq=433.8950 rssi=-60 stage=fine
[SUBGHZ_FA] hunt capture freq=433.8950 stage=fine timeout=2000ms mode=decode
[SUBGHZ_FA] hunt timeout (no burst captured)
[SUBGHZ_FA] silent (last freq=433.895 rssi=-60)
[SUBGHZ_FA] freq=433.8999 rssi=-54 stage=fine
[SUBGHZ_FA] hunt capture freq=433.8999 stage=fine timeout=2000ms mode=decode
[KAT_DBG] decode failed: KL step=0 bits=0 hc=0 te_auto=0 | SL step=0 bits=0 hc=0 | FLOR step=2 bits=0 hc=1
SubGHz: key saved at index 3
[SUBGHZ_RAW] idx=3 freq=433.90 edges=154                                      ← GUI: append row idx=3 (RAW)
[SUBGHZ_FA] silent (last freq=433.900 rssi=-54)
[SUBGHZ_FA] freq=433.8770 rssi=-60 stage=fine
[SUBGHZ_FA] hunt capture freq=433.8770 stage=fine timeout=2000ms mode=decode
[KAT_RX] Nice FloR-S decoded+decrypted: serial=0x44A2582 btn=1 cnt=3040 mf=Nice One learn=UNKNOWN
SubGHz: key saved at index 4
[SUBGHZ_RX] idx=4 type=Nice FloR-S freq=433.88 bits=72 serial=0x44A2582 btn=1 proto=Nice FloR-S learn=UNKNOWN mf=Nice One cnt=3040 te=0  ← GUI: append row idx=4
> subghz_stop
[subghz] Frequency Analyzer task stopped
SubGHz operations stopped.
> subghz_list mem
[SUBGHZ_LIST] idx=1 type=KeeLoq freq=433.85 bits=65 serial=0x04DEC1 btn=2 cnt=37188 mf=Leopard learn=MAGIC_XOR_T1 name=00001_KeeLoq_433.85_04DEC1
[SUBGHZ_LIST] idx=2 type=HOLTEK freq=433.91 bits=12 id=3F0A te=337 mf=- name=00002_HOLTEK_433.91_3F0A
[SUBGHZ_LIST] idx=3 type=RAW freq=433.90 edges=154 name=00003_raw_433900
[SUBGHZ_LIST] idx=4 type=Nice FloR-S freq=433.88 bits=72 serial=0x44A2582 btn=1 cnt=3040 mf=Nice One learn=- name=00004_Nice_FloR-S_433.88_44A2582
[SUBGHZ_LIST_END] count=4 source=mem
```

- **Stop**: `subghz_stop` (terminates the analyzer task and the active capture window if any).

- **Notes / gotchas (frequency analyzer)**:
  - The trigger value matters a lot: -85 dBm is the safe default for ESP32 + external CC1101 modules whose noise floor is higher than Flipper's internal radio. Drop to -90/-95 only on very clean RF environments.
  - `462.75 / 464.00 / 467.75 MHz` and `311.9–312.2 MHz` are blacklisted because the CC1101 produces persistent in-band birdies on most external modules.
  - **Decode hunt without `single`** expects RCSwitch-style **two matching inter-frame gaps**; a single short click often times out — use `hunt single` (optionally with `fast`) for one-burst + silence capture, or press the remote twice.
  - In hunt mode, between `hunt capture …` and one of the three terminating events (`[SUBGHZ_RX]` / `[SUBGHZ_RAW]` / `hunt timeout|error|duplicate`), the GUI should show a "capturing…" overlay/spinner. After it ends, return to the FA waterfall view.
  - Hunt mode reuses the same in-memory cache as `subghz_rx`, so captured signals show up immediately in `subghz_list mem` (and can be promoted to SD with `subghz_save`).
  - **C API**: extended options are on `subghz_start_analyzer_ex(trigger, hunt, raw, hunt_single_frame, hunt_timeout_ms, fast_scan, freq_debug)`; `subghz_start_analyzer(...)` is equivalent to `ex(..., false, 0, false, false)` (default timeout 2000 ms when `hunt_timeout_ms` is 0).

---

## Traffic Scanner (edge-activity scan over the FA freq list)

A lighter-weight cousin of the Frequency Analyzer: it visits the **same** Flipper Momentum frequency list (`s_fa_freq_list[]`, ~62 entries, 300/430/868 MHz bands), and for each frequency it briefly arms the GDO0 edge-counter to see whether anything is actually transmitting OOK at the moment. There is no fine scan and no hunt — just a continuous "where is something talking right now" loop.

### `subghz_scanner`
- **Syntax**: `subghz_scanner [dwell=MS] [edges=N] [rssi=DBM|-DBM] [fast] [debug]`
  - All args are positional but order-independent.
  - `dwell=MS`: per-frequency listen window (default **80 ms**, range **20…500 ms**).
  - `edges=N`: minimum GDO0 edges in the dwell window to count as traffic (default **4**, range **1…10000**).
  - `rssi=DBM` (or a bare negative-dBm token like `-80`): RSSI floor — hits weaker than this are treated as noise (default **-75 dBm**, range **-120…-40**). Bare-token form mirrors `subghz_freq_analyzer`.
  - `fast`: shorter calibration settle (~0.8 ms vs 2 ms) per frequency tune, like `subghz_freq_analyzer fast`.
  - `debug`: emit **`[SUBGHZ_SCAN_DIAG]`** after each `[SUBGHZ_SCAN_HIT]` with cluster centroid vs snapped frequency.

- **Examples**:
```
subghz_scanner                            # defaults (80 ms dwell, edges>=4, rssi>=-75 dBm)
subghz_scanner dwell=120 edges=8          # less twitchy, fewer false hits
subghz_scanner edges=2 fast               # more sensitive on edges + faster scan
subghz_scanner rssi=-80                   # widen RSSI window (catches weaker bursts)
subghz_scanner -85 edges=8                # Flipper-style trigger + tighter edge gate
subghz_scanner debug dwell=120            # centroid vs snap diagnostics
```

- **Behaviour**:
  - For each non-blacklisted frequency: switch to the standard OOK 650 kHz async RX preset, settle, arm the GDO0 edge ISR, sleep `dwell_ms`, snapshot edge count + RSSI, disable ISR.
  - A frequency qualifies as a **hit** when `count >= edges` **AND** `rssi >= rssi_floor`. The RSSI gate exists because the CC1101 + ESP32 module noise floor pings at ~-85 to -100 dBm, and edge-count alone cannot tell those apart from a real -50 dBm burst.
  - **Adjacent-frequency clustering**: a single transmission lights up every entry of `s_fa_freq_list[]` within ~±500 kHz because the OOK RX preset uses 650 kHz BW. The scanner collapses contiguous in-band hits into one cluster. The reported `freq` applies the same pipeline as FA to the cluster's RSSI-weighted centroid: **Hz smoothing + round_int(3) + snap** to the nearest list entry (not the raw strongest channel). `edges` / `rssi` still come from the strongest channel in the cluster. The filter resets on scanner start and after **2+ silent passes** (new session). A cluster is closed as soon as the next scanned frequency is more than 500 kHz past the last hit — that includes inter-band jumps (e.g. 467 → 779 MHz).
  - **Cross-pass sample-hold dedup**: a cluster representative is only re-emitted on a later pass if either the cluster's centre drifts more than 500 kHz or **2+ consecutive fully-silent passes** broke the streak — so a continuously-active transmitter generates one event per "session", not one per pass.
  - At the end of each full pass: emit `[SUBGHZ_SCAN_PASS] freqs=N hits=N` where `hits` is the number of clusters seen this pass (not the number of raw frequency hits).

- **Lifecycle output**:
```
[subghz] Scanner task started (dwell=80ms edges=4 rssi=-75 freqs=62 fast=0 debug=0)
[SUBGHZ_SCAN_START] dwell=80ms edges=4 rssi=-75 fast=0 debug=0
SubGHz scanner active. Use 'subghz_stop' to end.
... (continuous events, see below) ...
[subghz] Scanner task stopped
```

- **Continuous events**:

| Line | Meaning | Parse |
|------|---------|-------|
| `[SUBGHZ_SCAN_START] dwell=<ms>ms edges=<N> rssi=<dBm> fast=<0\|1> debug=<0\|1>` | Scanner started (one-shot) | `sscanf(line, "[SUBGHZ_SCAN_START] dwell=%dms edges=%d rssi=%d fast=%d debug=%d", ...)` |
| `[SUBGHZ_SCAN_HIT] freq=<MHz> edges=<N> rssi=<dBm>` | Traffic cluster; `freq` is snapped to nearest list entry (4-decimal precision). | `sscanf(line, "[SUBGHZ_SCAN_HIT] freq=%f edges=%u rssi=%d", &f, &edges, &rssi)` |
| `[SUBGHZ_SCAN_DIAG] centroid=... rep=... filt_hz=... snapped=... snap_err_hz=... cluster_span_mhz=...` | Optional (CLI `debug`): RSSI-weighted centroid before snap vs reported `freq` | grep / manual parse |
| `[SUBGHZ_SCAN_PASS] freqs=<N> hits=<N>` | End of a full pass over the freq list (`hits` = clusters this pass) | `sscanf(line, "[SUBGHZ_SCAN_PASS] freqs=%u hits=%d", &nfreqs, &hits)` |

- **Example output** (one transmitter active at 433.92 MHz; `subghz_scanner`):
```
[SUBGHZ_SCAN_START] dwell=80ms edges=4 rssi=-75 fast=0
[SUBGHZ_SCAN_HIT]   freq=433.9200 edges=79 rssi=-39    # cluster snapped to 433.92 (not 433.889)
[SUBGHZ_SCAN_PASS]  freqs=62 hits=1
[SUBGHZ_SCAN_PASS]  freqs=62 hits=0                    # transmitter went quiet
[SUBGHZ_SCAN_PASS]  freqs=62 hits=0
[SUBGHZ_SCAN_HIT]   freq=433.9200 edges=82 rssi=-37    # re-emitted: streak broke (≥2 silent passes)
[SUBGHZ_SCAN_PASS]  freqs=62 hits=1
```

- **Stop**: `subghz_stop`.

- **Notes / gotchas (scanner)**:
  - Same blacklist as the Frequency Analyzer applies (`311.9–312.2 MHz`, `462.75 / 464.00 / 467.75 MHz`, anything `>920 MHz`).
  - The edge-counter is the same `s_isr_edge_count` used by the existing capture pipeline — `subghz_scanner` just reads it after a fixed dwell rather than waiting for a complete RCSwitch double-gap frame, so it picks up burst traffic that the analyzer would only catch through the full coarse → fine → hunt pipeline.
  - `dwell` is the dominant per-frequency cost; with the default 80 ms × 62 frequencies a full pass is ~5 s. Dropping `dwell` to 30 ms and using `fast` gets you ~2 s/pass at the cost of more borderline misses.
  - **Tuning the RSSI floor**: -75 is a safe default that filters every CC1101 noise-floor false positive observed in testing (which typically clusters at -84 to -100 dBm). Drop to `-80` or `-85` only if you are losing real weak hits and can tolerate noise re-appearing.
  - **Two real transmitters within ±500 kHz** of each other will be reported as **one** cluster (the stronger one wins). The cluster window is fixed at 500 kHz today — it is tied to the CC1101 OOK RX BW (650 kHz). Exposing it as a CLI knob is a future option if a real use case appears.
  - **C API**: `subghz_start_scanner(int dwell_ms, int edges_threshold, int min_rssi_dbm, bool fast_scan, bool freq_debug)`. Pass 0 for any default (including `min_rssi_dbm`); values outside `-120…-40` also fall back to default.

---

## Weather Sensor Receiver (433.92 MHz OOK)

Continuously listens on 433.92 MHz with the standard OOK preset and runs each captured burst through a stack of weather-sensor decoders. Loops until `subghz_stop`. No CLI options — everything is auto-detected.

### `subghz_weather`
- **Syntax**: `subghz_weather`

- **Decoded protocols** (all OOK, 433.92 MHz). 24 ports of Flipper Momentum's "Weather Station" decoder set. Acurite first, then Manchester-encoded Oregon, then PWM long-pulse families, then proprietary formats, then no-CRC formats:
  - **Acurite-5n1**, **Acurite-592TXR**, **Acurite-609TXC**, **Acurite-606TX**, **Acurite-986** — Acurite family (56/64-bit PWM with byte-sum + parity).
  - **EMOS-E601x** — 120-bit PWM with byte-sum checksum.
  - **TX_8300** — Ambient Weather TX-8300 / TFA 30.3211 (72-bit PWM with inverted-payload + Fletcher-8).
  - **Oregon-v3.0**, **Oregon2_3**, **Oregon-v1** — Manchester-encoded Oregon Scientific.
  - **ThermoPRO-TX4**, **Bresser-3CH**, **LaCrosse-TX141TH-Bv2**, **LaCrosse-TX**, **GT-WT02**, **GT-WT03** — PWM with proprietary checksums.
  - **Vauno-EN8822C**, **Auriol-AHFL**, **AmbientWeather-F007TH**, **inFactory-TH**, **Kedsum-TH** — fixed-nibble + nibble/byte-sum checksums.
  - **Wendox-W6726** — long-pulse (~5.8 ms) PWM with CRC-4.
  - **Solight-TE44**, **Auriol-TH** — Auriol/Solight family. Solight tested first (CRC8 stricter than HG0601A's fixed-nibble check).
  - **Nexus-TH** — last-resort 36-bit Nexus/Rubicson decoder (no CRC, only sanity checks).

- **Output line**:
```
[SUBGHZ_WEATHER] proto=<NAME> id=0x<HEX> ch=<N|-> temp=<C> hum=<%|-> batt=<ok|low>
```
  - `proto`: one of the 24 names above.
  - `id`: sensor ID (rolling on battery insertion for most). Hex.
  - `ch`: channel `1..3` for sensors that have one, `-` otherwise.
  - `temp`: degrees Celsius with one decimal. `-` if the protocol carries no temperature (e.g. LaCrosse-TX humidity-only frames).
  - `hum`: relative humidity in %. `-` for protocols without humidity.
  - `batt`: `ok` or `low` from the sensor's battery flag.

- **Examples** (illustrative — not a single capture):
```
[SUBGHZ_WEATHER] proto=Acurite-592TXR id=0x12AB ch=1 temp=23.4 hum=48 batt=ok
[SUBGHZ_WEATHER] proto=Acurite-606TX id=0xC1 ch=- temp=-3.2 hum=- batt=ok
[SUBGHZ_WEATHER] proto=Bresser-3CH id=0x12 ch=2 temp=18.1 hum=55 batt=low
[SUBGHZ_WEATHER] proto=LaCrosse-TX141THBv2 id=0x7E ch=1 temp=22.5 hum=43 batt=ok
[SUBGHZ_WEATHER] proto=Oregon-v3.0 id=0xF824 ch=1 temp=19.7 hum=62 batt=ok
```

- **Lifecycle output**:
```
[subghz] Weather task started on 433.92 MHz
[SUBGHZ_WEATHER_START] freq=433.92
SubGHz weather active. Use 'subghz_stop' to end.
... (continuous events) ...
[subghz] Weather task stopped
```

- **Continuous events**:

| Line | Meaning | Parse |
|------|---------|-------|
| `[SUBGHZ_WEATHER_START] freq=<MHz>` | Receiver started (one-shot) | `sscanf(line, "[SUBGHZ_WEATHER_START] freq=%f", &freq)` |
| `[SUBGHZ_WEATHER] proto=<N> id=0x<H> ch=<N\|-> temp=<C> hum=<%\|-> batt=<ok\|low>` | Decoded report (deduplicated) | `sscanf(line, "[SUBGHZ_WEATHER] proto=%31s id=0x%lX ch=%7s temp=%15s hum=%7s batt=%7s", proto, &id, ch, temp, hum, batt)` |

- **Stop**: `subghz_stop`.

- **Notes / gotchas (weather)**:
  - Sensors typically transmit every 30–60 s. The first reading from a given sensor will appear within that window — be patient; an empty log for two minutes is normal if no sensor is in range.
  - Same-(proto, id, ch) packets are **deduplicated** for ~30 s unless `temp` or `hum` changed. The 3–6× repeat that most cheap sensors emit per burst therefore produces **one** `[SUBGHZ_WEATHER]` line, not six.
  - `temp` is always emitted with one decimal; negative values are sign-extended (`temp=-3.2`). `hum` and `ch` can be the literal string `-` for protocols that don't carry them — handle both `%d` and `-` when parsing.
  - 868 MHz FSK weather sensors (LaCrosse TX29/TX35, Bresser 5-in-1) are **not** supported — those need a separate FSK preset and are out of scope for this command.
  - **C API**: `subghz_start_weather()` (no args).

---

## Signal library (mem cache + SD library)

All commands that touch an individual signal take `<mem|sd>` as their source.
See the [Storage model](#storage-model-mem-vs-sd) section at the top for the
full lifetime rules; commands below assume you already know whether you want
the volatile mem cache or the persistent SD library.

### `subghz_list`
- **Syntax**: `subghz_list <mem|sd>`
- **Description**: Lists signals from the chosen source. The row format is identical for both sources so a single UI parser works.
- **Output (mem)**:
```
[SUBGHZ_LIST] idx=1 type=KeeLoq freq=433.85 bits=65 serial=0x04DEC1 btn=2 cnt=37188 mf=Leopard learn=MAGIC_XOR_T1 name=00001_KeeLoq_433.85_04DEC1
[SUBGHZ_LIST] idx=2 type=HOLTEK freq=433.91 bits=12 id=3F0A te=337 mf=- name=00002_HOLTEK_433.91_3F0A
[SUBGHZ_LIST] idx=3 type=RAW freq=433.90 edges=154 name=00003_raw_433900
[SUBGHZ_LIST] idx=4 type=Nice FloR-S freq=433.88 bits=72 serial=0x44A2582 btn=1 cnt=3040 mf=Nice One learn=- name=00004_Nice_FloR-S_433.88_44A2582
[SUBGHZ_LIST_END] count=4 source=mem
```
- **Output (sd)**:
```
[SUBGHZ_LIST] idx=1 type=KeeLoq freq=433.85 bits=65 serial=0x04DEC1 btn=2 cnt=37188 mf=Leopard learn=MAGIC_XOR_T1 name=00001_KeeLoq_433.85_04DEC1
[SUBGHZ_LIST] idx=2 type=HOLTEK freq=433.91 bits=12 id=3F0A te=337 mf=- name=garageMain
[SUBGHZ_LIST_END] count=2 source=sd
```
- **Field layouts** (mirror `[SUBGHZ_RX]` exactly):
  - **Static**: `idx=N type=NAME freq=MHz bits=N id=HEX te=N mf=NAME name=BASENAME`
  - **Rolling**: `idx=N type=NAME freq=MHz bits=N serial=0xN btn=N cnt=N mf=NAME learn=NAME name=BASENAME`
  - **RAW**: `idx=N type=RAW freq=MHz edges=N name=BASENAME`
- **`name=`** is the basename of the corresponding `.sub` file (no directory, no extension). For mem entries it is auto-generated as `NNNNN_<Type>_<freq>_<id>` (or `NNNNN_raw_<freqKHz>` for RAW). For SD entries it reflects the current filename and the `Name:` field inside the file (kept in sync by `subghz_rename`).
- **Empty**: `[SUBGHZ_LIST_END] count=0 source=<mem|sd>`
- **Completion marker**: `[SUBGHZ_LIST_END] count=N source=<mem|sd>`

### `subghz_info`
- **Syntax**: `subghz_info <index> <mem|sd>`
- **Description**: Detailed inspection of one signal. May include a `[SUBGHZ_INFO_RAW]` line with raw timings.
- **Examples**: `subghz_info 1 mem`, `subghz_info 2 sd`
- **Output**:
```
[SUBGHZ_INFO] idx=1 type=KeeLoq freq=433.85 serial=0x04DEC1 btn=2 cnt=37188 mf=Leopard te=355 learn=MAGIC_XOR_T1 name=00001_KeeLoq_433.85_04DEC1
[SUBGHZ_INFO_RAW] -12122 377 -643 346 -341 676 ...
[SUBGHZ_INFO_END]
```
- **Three line formats can appear** (all suffixed with ` name=BASENAME`):
```
[SUBGHZ_INFO] idx=N type=RAW freq=MHz edges=N name=BASENAME
[SUBGHZ_INFO] idx=N type=NAME freq=MHz serial=0xN btn=N cnt=N mf=NAME te=N learn=NAME name=BASENAME       (rolling)
[SUBGHZ_INFO] idx=N type=NAME freq=MHz bits=N id=HEX te=N proto=N mf=NAME name=BASENAME                   (static)
```
- `[SUBGHZ_INFO_RAW]` is optional (present for RAW or where raw timings were retained). Format: tag followed by space-separated signed microsecond timings.
- **Failure**: `[SUBGHZ_INFO_ERR] idx=N reason=<not_found|parse_failed> source=<mem|sd>` followed by `[SUBGHZ_INFO_END]`.
- **Completion marker**: `[SUBGHZ_INFO_END]`

### `subghz_save`
- **Syntax**: `subghz_save <mem_idx>` or `subghz_save all`
- **Description**: Copies a mem-cached signal to SD as `/sdcard/lab/subghz/<name>.sub`. The mem entry is **left in place**. Use `all` to dump the entire mem cache. Filename collisions are refused — call `subghz_delete <sd_idx>` first or `subghz_rename` the mem entry's name (via re-capture / Python tooling) if needed.
- **Examples**: `subghz_save 1`, `subghz_save all`
- **Success output**:
```
[SUBGHZ_SAVE] idx=1 file=/sdcard/lab/subghz/00001_KeeLoq_433.85_04DEC1.sub name=00001_KeeLoq_433.85_04DEC1
[SUBGHZ_SAVE_END] count=1
```
- **Bulk output** (`all`): one `[SUBGHZ_SAVE]` line per copied entry, then `[SUBGHZ_SAVE_END] count=N`.
- **Failure output**: `[SUBGHZ_SAVE_ERR] idx=N reason=<invalid|not_found|collision|write_failed>` followed by `[SUBGHZ_SAVE_END] count=N` (after the loop terminates). On collision the existing file is **not** overwritten.
- **Prerequisites**: SD card mounted.

### `subghz_rename`
- **Syntax**: `subghz_rename <sd_idx> <new_name>`
- **Description**: Renames an SD-library signal: both the filename (`/sdcard/lab/subghz/<old>.sub` → `/sdcard/lab/subghz/<new_name>.sub`) and the `Name:` field inside the `.sub` are updated atomically. Trace files do not exist anymore — this is the only place renaming happens.
- **`new_name` rules**: 1..63 chars, allowed `[A-Za-z0-9_.-]`, no `/` or spaces. Must not collide with an existing file in `/sdcard/lab/subghz/`.
- **Examples**: `subghz_rename 2 garageMain`, `subghz_rename 5 frontDoor.v2`
- **Success output**:
```
[SUBGHZ_RENAME] idx=2 old=00002_HOLTEK_433.91_3F0A new=garageMain file=/sdcard/lab/subghz/garageMain.sub source=sd
```
- **Failure output**: `[SUBGHZ_RENAME_ERR] idx=N reason=<empty|too_long|bad_char|not_found|collision|sd_error|parse_failed|write_failed> source=sd` (extra fields per reason: `max=N`, `file=...`). On `write_failed` the new file is not committed and the old `.sub` file is left untouched.
- **Persistence**: persistent — the file on SD survives reboot.
- **UI note**: `sd_idx` is positional; always re-issue `subghz_list sd` after a rename to refresh the table.

### `subghz_delete`
- **Syntax**: `subghz_delete <sd_idx>`
- **Description**: Deletes one signal file from `/sdcard/lab/subghz/`. The mem cache is untouched.
- **Output**: `[SUBGHZ_DELETE] idx=2 file=/sdcard/lab/subghz/garageMain.sub remaining=N source=sd`
- **Errors**: `[SUBGHZ_DELETE_ERR] idx=N reason=<not_found|sd_error|unlink_failed> source=sd`.
- **UI note**: `sd_idx` is positional; re-issue `subghz_list sd` after a delete.

### `subghz_clear`
- **Syntax**: `subghz_clear`
- **Description**: Wipes the **mem cache only**. The SD library is intentionally untouched — to delete SD files use `subghz_delete <sd_idx>` per file.
- **Output**: `[SUBGHZ_CLEAR] done removed=N source=mem` (`N` = number of mem entries that were dropped; `0` if the cache was already empty).

### Flipper-format compatibility (drop-in `.sub` files)

`.sub` files written by a Flipper Zero with `Filetype: Flipper SubGhz` work
out of the box — copy them into `/sdcard/lab/subghz/` (e.g. over SCP / card
reader). They show up in `subghz_list sd`, can be inspected with
`subghz_info <idx> sd`, replayed with `subghz_tx <idx> sd`, renamed and
deleted like any native entry. Flipper KeeLoq files are decrypted on the fly
using the `Manufacture:` line when present.

---

## Diagnostics

### `subghz_protocols`
- **Syntax**: `subghz_protocols [filter]`
- **Description**: Lists protocols the firmware can decode/encode. Optional substring filter.
- **Output**: `[SUBGHZ_PROTO] name=NAME role=<rx|tx|both>` per protocol, `[SUBGHZ_PROTOS_END] count=N` to terminate.

### `subghz_keys`
- **Syntax**: `subghz_keys`
- **Description**: Dumps loaded manufacturer keys (KeeLoq MF keys etc.).
- **Output**: `[SUBGHZ_KEY] ...` per key, `[SUBGHZ_KEYS_END]` to terminate.

### `subghz_selftest`
- **Syntax**: `subghz_selftest`
- **Description**: Runs internal CC1101 + protocol regression tests. Output is freeform diagnostic; treat as opaque log.

---

## System

### `board_name`
- **Syntax**: `board_name`
- **Description**: Prints the optional per-device board label burned into eFuse BLK5 / KEY1 during provisioning. This is JanOS provisioning metadata, independent of the SubGHz keystore and independent of the license signature in BLK3 / BLK4.
- **Provisioning format**: 1..32 ASCII chars matching `^[A-Z0-9_-]{1,32}$` (uppercase letters, digits, dash, underscore). Lowercase letters, spaces, UTF-8, and punctuation outside `_-` are invalid.
- **Output**:
```
board_name=TAB5-CC1101-R2-0042
board_name=<unset>
```
- **Boot output**: the same value is printed once at startup as `[BOARD] name=...`.

### `subghz_stop`
- **Syntax**: `subghz_stop`
- **Description**: Universal stop — terminates whatever SubGHz task is currently running (`subghz_rx`, `subghz_freq_analyzer`, `subghz_scanner`, `subghz_weather`, `subghz_jam`) and puts CC1101 into idle. Always send before starting a new continuous task.
- **Output**:
```
[subghz] <Task name> task stopped
SubGHz operations stopped.
```

---

## Quick parsing matrix (cheat sheet)

| Tag prefix | Emitted by | Continuous? | Parse priority |
|------------|-----------|-------------|----------------|
| `[SUBGHZ_FA_START]`     | `subghz_freq_analyzer` start (includes `single`/`fast`/`tmo`) | one-shot     | High — UI mode change |
| `[SUBGHZ_FA] freq=`     | analyzer hit                              | continuous   | High — waterfall + last hit |
| `[SUBGHZ_FA] hunt`      | hunt-mode capture window state            | per-hit      | High — spinner state |
| `[SUBGHZ_FA] silent`    | sample-hold expired                       | per-hit      | Medium — idle indicator |
| `[SUBGHZ_SCAN_START]`   | `subghz_scanner` start                    | one-shot     | High — UI mode change |
| `[SUBGHZ_SCAN_HIT]`     | scanner hit on a frequency                | continuous   | High — append/highlight freq row |
| `[SUBGHZ_SCAN_PASS]`    | end of one full pass over the freq list   | per-pass     | Medium — header counter |
| `[SUBGHZ_WEATHER_START]`| `subghz_weather` start                    | one-shot     | High — UI mode change |
| `[SUBGHZ_WEATHER]`      | decoded weather sensor report             | per sensor   | Critical — append/update sensor row |
| `[SUBGHZ_RSSI]`         | `subghz_rx`                               | ~1 Hz        | High — waterfall |
| `[REPLAY_SEG]`          | `subghz_rx`, hunt decode                  | per signal   | Low — debug; GUI uses `[SUBGHZ_RX]` |
| `[SUBGHZ_RX]`           | `subghz_rx`, `subghz_freq_analyzer hunt`  | per signal   | Critical — append to list |
| `[SUBGHZ_RX_DUP]`       | `subghz_rx`, `subghz_freq_analyzer hunt`  | per signal   | Medium — flash existing row |
| `[SUBGHZ_RAW]`          | raw fallback or raw mode                  | per signal   | Critical — append to list |
| `[SUBGHZ_RX_DROP]`      | `subghz_rx` noise gate                    | per drop     | Low — optional debug pane |
| `[SUBGHZ_LIST]`         | `subghz_list <mem\|sd>`                   | per row      | Critical — table fill |
| `[SUBGHZ_LIST_END]`     | `subghz_list <mem\|sd>` (carries `source=`) | one-shot   | High — terminator |
| `[SUBGHZ_INFO]`         | `subghz_info <idx> <mem\|sd>`             | one-shot     | High — detail panel |
| `[SUBGHZ_INFO_RAW]`     | `subghz_info` (RAW or partial)            | one-shot     | Medium — raw timings |
| `[SUBGHZ_INFO_END]`     | `subghz_info`                             | one-shot     | High — terminator |
| `[SUBGHZ_INFO_ERR]`     | `subghz_info` failure                     | one-shot     | High — show error toast |
| `[SUBGHZ_SAVE]`         | `subghz_save` (per saved entry)           | per call     | High — refresh sd list |
| `[SUBGHZ_SAVE_END]`     | `subghz_save` (carries `count=`)          | one-shot     | High — terminator |
| `[SUBGHZ_SAVE_ERR]`     | `subghz_save` failure                     | per entry    | High — show error toast |
| `[SUBGHZ_DELETE]`       | `subghz_delete` success (carries `source=sd`) | one-shot | High — refresh sd list |
| `[SUBGHZ_DELETE_ERR]`   | `subghz_delete` failure                   | one-shot     | High — show error toast |
| `[SUBGHZ_CLEAR]`        | `subghz_clear` (carries `source=mem`)     | one-shot     | High — clear mem list |
| `[SUBGHZ_TX]`           | `subghz_tx` (carries `source=`)           | one-shot     | High — toast/result |
| `[SUBGHZ_FREQ]`         | `subghz_freq` get/set                     | one-shot     | High — confirm freq |
| `[SUBGHZ_FREQ_CORRECTION]` | `subghz_set_freq_correction` / `subghz_get_freq_correction` | one-shot | Medium — show NVS-persisted xtal trim (MHz, signed, 2 decimals) |
| `[SUBGHZ_STATUS]`       | `subghz_status`                           | one-shot     | High — status bar |
| `[BOARD] name=`         | boot                                      | one-shot     | Medium — provisioning label |
| `board_name=`           | `board_name`                              | one-shot     | Medium — provisioning label |
| `[SUBGHZ_RENAME]`       | `subghz_rename` success (carries `source=sd`) | per call | High — refresh sd list row |
| `[SUBGHZ_RENAME_ERR]`   | `subghz_rename` failure                   | per call     | High — show error toast |
| `[KAT_RX]`              | rolling-code dispatcher                   | per signal   | High — decoded panel |
| `[KL_DEC]`              | KeeLoq decoder                            | per signal   | Medium — decrypted detail |
| `[KL_GROUND]`           | KeeLoq dedup verifier                     | per signal   | Low — verbose |
| `[KAT_DBG]`             | rolling-code decode failure trace         | per signal   | Low — verbose |
| `[subghz]` (lowercase)  | firmware diagnostic                       | continuous   | None — opaque log |
| `SubGHz: key saved …`   | legacy human line after auto-save         | per signal   | None — superseded by `[SUBGHZ_RX]` |
