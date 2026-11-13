# JanOS for M5Stack Cardputer Zero

This directory contains the native Cardputer Zero frontend for the JanOS
controller. It is not an ESP32 firmware and must not be built with Arduino,
PlatformIO, or ESP-IDF. Cardputer Zero is an ARM64 Linux computer based on the
Raspberry Pi Compute Module 0, so the application can reuse the canonical
Python implementation instead of maintaining a second copy of JanOS logic.

The root project remains the source of truth:

- `../JanOS_app.py` owns the established terminal controller behaviour;
- `../janos_core.py` is the standard-library-only protocol core imported by
  both frontends;
- `../projectzero_commands.py` owns the declarative projectZero command
  catalog;
- `scripts/sync_from_python.py` derives the Cardputer resources from those
  Python sources and records their source hashes;
- the code under `CardputerZero/app/` contains the small-screen UI, keyboard
  mapping, serial transaction adapter, and Cardputer-specific integration.

Do not edit generated files by hand. A stale generated catalog is treated as a
build and CI error.

## Hardware target

Cardputer Zero is materially different from Cardputer and Cardputer ADV.

| Component | Cardputer Zero |
| --- | --- |
| CPU | Raspberry Pi CM0, RP3A0/BCM2837, quad-core Cortex-A53 at 1 GHz |
| Architecture | ARMv8-A, AArch64 Linux |
| Memory | 512 MB LPDDR2 |
| Display | 1.9-inch ST7789v3, 320 x 170, no touch |
| Keyboard | 46-key TCA8418 matrix keyboard exposed through Linux evdev |
| Storage | microSD |
| Network | 2.4 GHz Wi-Fi, Bluetooth, 10/100 Ethernet |
| Expansion | USB host/device, Grove UART/I2C, SPI/I2C/UART/GPIO Cap bus |

The full model also has an IMX219 camera and BMI270/BMM150 sensors. The Lite
model does not; neither peripheral is required by this application.

The application uses the operating-system drivers rather than addressing the
ST7789 or TCA8418 directly. On a stock image the relevant interfaces are
normally `/dev/fb0` and an evdev node under `/dev/input/`. Device names are
discovered at runtime and must not be hard-coded in user code.

Official references:

- [Cardputer Zero product documentation](https://docs.m5stack.com/en/CardputerZero)
- [Cardputer Zero user guide](https://docs.m5stack.com/en/compute/cardputerzero/usage)
- [Cardputer Zero application template](https://github.com/CardputerZero/Template)
- [APPLaunch and Linux SDK](https://github.com/CardputerZero/launcher)
- [AppBuilder and package format](https://github.com/CardputerZero/AppBuilder)

## Connecting the JanOS board

The application controls a separate MonsterC5/projectZero board. Cardputer
Zero does not replace that board's ESP32-C5 radio.

### USB serial (recommended)

1. Put the Cardputer Zero USB switch in **Host** mode.
2. Connect the MonsterC5 USB serial port to Cardputer Zero USB-A or the
   host-capable USB-C port with a data cable.
3. Open **Connect / board** and select the detected `/dev/ttyACM*` or
   `/dev/ttyUSB*` device.

USB serial provides grounding, device discovery, and the least ambiguous
wiring. Only one program may own the serial device at a time; close terminal
monitors before launching JanOS.

### Grove/direct UART

Cardputer Zero exposes the following default Grove UART signals:

| Signal | Cardputer Zero |
| --- | --- |
| TX | GPIO14 -> Monster RX |
| RX | GPIO15 <- Monster TX |
| Ground | GND <-> GND |
| UART format | 115200 baud, 8 data bits, no parity, 1 stop bit |

The Grove connector can be switched between UART and I2C; UART is the hardware
default. Its 5 V output is disabled by default and is controlled from
`Settings > ExtPort`. Do **not** connect the red 5 V line unless the exact
Monster board revision documents that power path. UART GPIO signalling is
3.3 V. Cross TX/RX and always share ground.

Cap modules are not hot-pluggable. Power the device off before attaching or
removing anything from the top expansion bus.

### Serial permissions

The packaged app runs as a normal user, as required by APPLaunch. That user
must be allowed to access the UART, usually through the `dialout` group:

```bash
sudo usermod -aG dialout "$USER"
```

Log out and back in after changing group membership. Avoid running the app as
root. If an image uses different device permissions, add a narrowly scoped
udev rule for the Monster USB VID/PID rather than making every serial device
world-writable.

## Architecture and source-of-truth contract

```text
JanOS_app.py + projectzero_commands.py       canonical Python sources
                    |
                    | scripts/sync_from_python.py
                    v
        generated command/resource manifest
                    |
       +------------+-------------+
       |                          |
Cardputer UI/input adapter    shared UART/protocol core
       |                          |
       +------------+-------------+
                    |
             MonsterC5 / JanOS
```

The synchronization step is semantic: it imports the canonical Python command
definitions, normalizes them, validates duplicate commands and handler modes,
and writes a deterministic device resource. It also stores hashes of its input
sources. It is not a second hand-maintained list and it is not a blind source
directory copy.

### Automatically synchronized

- command names, labels, groups, argument hints, confirmation requirements,
  and stream/one-shot modes from `projectzero_commands.py`;
- generic raw-command availability and capability matching against the live
  board's `help` response;
- source fingerprints for the terminal app, shared core, and catalog; the
  shared protocol functions themselves are imported directly from
  `janos_core.py`, so there is no generated copy to drift;
- the source fingerprint used by `--check` and CI.

### Deliberately Cardputer-specific

- screen layout, pagination, colors, focus, and 320 x 170 rendering;
- keyboard shortcuts, `Esc`, text entry, and evdev discovery;
- APPLaunch lifecycle and Debian package metadata;
- Linux serial-device selection and permission diagnostics.

### Requires explicit porting when behaviour changes

A new declarative command automatically appears in the generic command browser
after synchronization. A feature needs manual Cardputer work only when it
requires a purpose-built visual workflow, a new structured response parser, a
new binary transfer state machine, or direct use of Cardputer hardware. The
canonical Python implementation must be changed first. The Cardputer adapter
must then be added with a test that uses the same fixtures/contract. The sync
tool intentionally does not claim that arbitrary terminal UI code can be
translated into a graphical screen.

## User interface

The interface is keyboard-first and optimized for the 320 x 170 display:

- arrows move the selection or scroll output;
- `Enter` opens/accepts;
- `Esc` cancels or returns one level; from HOME it exits to APPLaunch;
- printable keys enter command arguments and paths;
- the footer always shows the currently valid actions.

The APPLaunch status area may occupy the top 20 pixels. Views therefore avoid
assuming that all 170 rows are available. Long UART output is bounded and
scrollable instead of being retained indefinitely in the 512 MB address space.

### Implemented control surface

- serial discovery, connect/disconnect, firmware version and live `help`
  capability probing;
- the complete generated command browser (152 JanOS-app entries, including
  all 131 commands registered by the audited projectZero firmware);
- Wi-Fi scan with delayed-result fallback, result browsing, target selection,
  and inspection;
- grouped one-shot and streaming commands, raw console access, confirmation
  for disruptive/unreported commands, bounded logs, and cancellation;
- FS/1 directory listing, safe path encoding, CRC-checked FTB/1 download,
  streaming transactional ACK32 upload, removal, capabilities, and legacy
  absolute-path download;
- resumable CRACK/1 protocol-4 wordlist/HCCAPX upload with prefix CRC,
  block replay, FIN handling, cache probe/reset, shard start/status/cancel,
  and diagnostics;
- negotiated JanOS UART rates from 115200 to 4 Mbaud with automatic fallback
  when confirmation fails.

## Development workflow

Run commands from the repository root.

### 1. Synchronize from canonical Python

```bash
python3 CardputerZero/scripts/sync_from_python.py
```

Verify that a commit contains all required generated updates without modifying
the tree:

```bash
python3 CardputerZero/scripts/sync_from_python.py --check
```

### 2. Run the desktop/development frontend

Run a fully simulated board in the desktop Cardputer window:

```bash
python3 -m CardputerZero.app.main --dev --demo
```

Or use the same desktop UI with a real serial board:

```bash
python3 -m CardputerZero.app.main --dev --device /dev/ttyUSB0
```

The simulator exercises UI and state transitions; it does not emulate the
ESP32-C5 radio.

### 3. Run tests

```bash
python3 -m unittest discover -s CardputerZero/tests -v
```

The repository-level Python tests should also remain green:

```bash
python3 -m unittest discover -s tests -v
```

### 4. Build the ARM64 package

```bash
bash CardputerZero/scripts/build.sh
```

The build reruns synchronization checks and creates:

```text
CardputerZero/dist/janos-cardputer_<version>_arm64.deb
```

The package installs an APPLaunch entry, the application, its generated
resources, and the required canonical Python runtime components. Building a
Python application does not require cross-compiling its source, but the Debian
package architecture is `arm64` because it targets the Cardputer Zero image.

## Install and launch

Copy the package to the device over SSH:

```bash
scp CardputerZero/dist/janos-cardputer_*_arm64.deb \
  <user>@<cardputer-zero-ip>:/tmp/
```

Install it on Cardputer Zero:

```bash
ssh <user>@<cardputer-zero-ip> \
  'sudo apt install --no-install-recommends /tmp/janos-cardputer_*_arm64.deb'
```

Return to HOME, refresh/restart APPLaunch if necessary, and open **JanOS**.
Package upgrades preserve user settings. To test directly over
SSH, run the installed launcher command shown in its `.desktop` file; do not
run a second instance while APPLaunch owns it.

Downloaded board files are stored in
`~/.local/state/janos-cardputer/downloads/`. For FS/1 or crack-worker uploads,
copy source files to `~/.local/state/janos-cardputer/uploads/` and enter their
filename, or enter an absolute local path. `SD files > Crack worker files`
implements the real resumable CRACK/1 protocol-4 transfer for wordlists and
HCCAPX captures; it also exposes cache probe/reset, shard start/status/cancel,
and diagnostics.

## Adding a feature in the future

1. Implement or change the feature in the root Python code first.
2. Express command metadata in the canonical catalog rather than a Cardputer
   list.
3. Run `sync_from_python.py` and inspect the deterministic generated diff.
4. If generic execution is sufficient, no device code is needed.
5. If the feature needs tailored interaction, add a Cardputer view/controller
   that consumes the generated command ID and shared response contract.
6. Add parser/UI tests and run `sync_from_python.py --check`.
7. Build and install a new `.deb`.

CI runs the same check so changing canonical command definitions without
refreshing Cardputer resources cannot silently merge.

## Limits and verification status

- The application can operate without a computer, but JanOS functions still
  require the external MonsterC5/projectZero board to be connected.
- Internet-backed operations such as OTA, WiGLE, WDGWars, and WPA-SEC require
  working network access and their normal credentials.
- The SubGHz section in the root project is a JanosRF/custom-firmware extension
  and is not reported by stock projectZero. Capability discovery marks or hides
  unsupported commands instead of pretending they exist.
- Camera, IMU, audio, IR, and direct Cap-radio drivers are not required for
  UART control and are not used merely because the full Cardputer Zero contains
  them.
- Cardputer Zero Lite is supported for the controller UI, but it needs its own
  microSD card and does not provide the camera or IMU.
- Final serial-node names, Grove power behaviour, and sustained high UART baud
  rates must be verified on the exact physical board/cable combination.
- Automated tests and a desktop frontend validate software contracts; they do
  not replace a final smoke test on Cardputer Zero plus MonsterC5.

