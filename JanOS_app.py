#!/usr/bin/env python3
"""
JanOS App - ESP32-C5 Controller

Usage: ./JanOS_app.py
Optional: ./JanOS_app.py <device>
Example: ./JanOS_app.py /dev/ttyUSB0
"""

import sys
import os
import time
import serial
from serial.tools import list_ports
import threading
import select
import termios
import fcntl
import tempfile
import re
import readline  # For better input handling
import unicodedata
from datetime import datetime
from typing import List, Dict, Tuple, Optional, Any

# ============================================================================
# Configuration
# ============================================================================
BAUD_RATE = 115200
SCAN_TIMEOUT = 15
READ_TIMEOUT = 2
SNIFFER_UPDATE_INTERVAL = 1  # seconds
PORTAL_UPDATE_INTERVAL = 2   # seconds for portal monitoring
EVIL_TWIN_UPDATE_INTERVAL = 2  # seconds for evil twin monitoring

# ============================================================================
# Colors and Styling
# ============================================================================
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[0;33m'
    BLUE = '\033[0;34m'
    MAGENTA = '\033[0;35m'
    CYAN = '\033[0;36m'
    WHITE = '\033[1;37m'
    GRAY = '\033[0;90m'
    NC = '\033[0m'  # No Color
    BOLD = '\033[1m'
    DIM = '\033[2m'

# Box drawing characters
BOX_TL = '╔'
BOX_TR = '╗'
BOX_BL = '╚'
BOX_BR = '╝'
BOX_H = '═'
BOX_V = '║'
BOX_LT = '╠'
BOX_RT = '╣'

# ============================================================================
# Utility Functions
# ============================================================================
def detect_os() -> str:
    """Detect the operating system."""
    if sys.platform.startswith('linux'):
        return 'linux'
    elif sys.platform.startswith('darwin'):
        return 'macos'
    else:
        return 'unknown'

def get_terminal_width() -> int:
    """Get terminal width."""
    try:
        import shutil
        return shutil.get_terminal_size().columns
    except:
        return 80

def center_text(text: str) -> str:
    """Center text in terminal."""
    width = get_terminal_width()
    text_len = len(strip_ansi(text))
    padding = max(0, (width - text_len) // 2)
    return " " * padding + text

def strip_ansi(text: str) -> str:
    """Remove ANSI color codes from text."""
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
    return ansi_escape.sub('', text)

def char_display_width(ch: str) -> int:
    """Estimate display width of one character in terminal."""
    if not ch:
        return 0
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1

def display_width(text: str) -> int:
    """Compute visual width of text (ANSI ignored)."""
    clean = strip_ansi(text)
    return sum(char_display_width(ch) for ch in clean)

def fit_ansi_text(text: str, width: int) -> str:
    """Trim/pad ANSI-colored text to exact display width."""
    if width <= 0:
        return ""

    ansi_re = re.compile(r'(\x1b\[[0-9;]*m)')
    tokens = ansi_re.split(text)
    out = []
    used = 0

    for token in tokens:
        if not token:
            continue
        if ansi_re.fullmatch(token):
            out.append(token)
            continue
        for ch in token:
            w = char_display_width(ch)
            if used + w > width:
                break
            out.append(ch)
            used += w
        if used >= width:
            break

    if used < width:
        out.append(" " * (width - used))
    return "".join(out)

def print_line(char: str = '═') -> None:
    """Print a horizontal line."""
    width = get_terminal_width()
    print(char * width)

def clear_screen() -> None:
    """Clear the terminal screen."""
    os.system('clear' if os.name != 'nt' else 'cls')

def is_probable_esp32(port) -> bool:
    """Heuristic check to guess ESP32 serial adapters."""
    haystack = " ".join(filter(None, [port.description, port.manufacturer, port.hwid])).lower()
    keywords = ["esp32", "cp210", "ch340", "silicon labs", "uart"]
    return any(keyword in haystack for keyword in keywords)

def list_serial_devices() -> List:
    """Return a list of available serial devices."""
    return list(list_ports.comports())

def print_usage() -> None:
    """Print CLI usage."""
    print(f"{Colors.CYAN}JanOS Controller{Colors.NC} - ESP32-C5 Wireless Controller")
    print()
    print("Usage: ./JanOS_app.py")
    print("Optional: ./JanOS_app.py <device>")
    print()
    print("Arguments:")
    print("  device    Serial device path (e.g., /dev/ttyUSB0, /dev/cu.usbserial-*)")
    print()
    print("Examples:")
    print("  ./JanOS_app.py                      # Interactive selector")
    print("  ./JanOS_app.py /dev/ttyUSB0        # Linux")
    print("  ./JanOS_app.py /dev/cu.usbserial-0001  # macOS")
    print()

# ============================================================================
# UI Components
# ============================================================================
COMPACT_BOX_WIDTH = 60

class UI:
    @staticmethod
    def print_box_top() -> None:
        width = get_terminal_width()
        inner_width = max(0, width - 2)
        print(f"{Colors.CYAN}{BOX_TL}{BOX_H * inner_width}{BOX_TR}{Colors.NC}")

    @staticmethod
    def print_box_bottom() -> None:
        width = get_terminal_width()
        inner_width = max(0, width - 2)
        print(f"{Colors.CYAN}{BOX_BL}{BOX_H * inner_width}{BOX_BR}{Colors.NC}")

    @staticmethod
    def print_box_separator() -> None:
        width = get_terminal_width()
        inner_width = max(0, width - 2)
        print(f"{Colors.CYAN}{BOX_LT}{BOX_H * inner_width}{BOX_RT}{Colors.NC}")

    @staticmethod
    def print_box_line() -> None:
        width = get_terminal_width()
        inner_width = max(0, width - 2)
        print(f"{Colors.CYAN}{BOX_V}{Colors.NC}{' ' * inner_width}{Colors.CYAN}{BOX_V}{Colors.NC}")

    @staticmethod
    def print_box_text(text: str, color: str = Colors.NC) -> None:
        width = get_terminal_width()
        inner_width = max(0, width - 4)
        text_clean = strip_ansi(text)
        text_len = len(text_clean)
        padding = max(0, inner_width - text_len)
        print(f"{Colors.CYAN}{BOX_V}{Colors.NC} {color}{text}{Colors.NC}{' ' * padding}{Colors.CYAN}{BOX_V}{Colors.NC}")

    @staticmethod
    def print_box_text_centered(text: str, color: str = Colors.NC) -> None:
        width = get_terminal_width()
        inner_width = max(0, width - 4)
        text_clean = strip_ansi(text)
        text_len = len(text_clean)
        left_pad = max(0, (inner_width - text_len) // 2)
        right_pad = max(0, inner_width - text_len - left_pad)
        print(f"{Colors.CYAN}{BOX_V}{Colors.NC}{' ' * left_pad}{color}{text}{Colors.NC}{' ' * right_pad}{Colors.CYAN}{BOX_V}{Colors.NC}")

    @staticmethod
    def print_banner(device: str, attack_running: bool = False, blackout_running: bool = False, 
                    sniffer_running: bool = False, sae_overflow_running: bool = False,
                    handshake_running: bool = False, portal_running: bool = False,
                    evil_twin_running: bool = False) -> None:
        banner = f"""{Colors.CYAN}
      ██╗ █████╗ ███╗   ██╗ ██████╗ ███████╗
      ██║██╔══██╗████╗  ██║██╔═══██╗██╔════╝
      ██║███████║██╔██╗ ██║██║   ██║███████╗
 ██   ██║██╔══██║██║╚██╗██║██║   ██║╚════██║
 ╚█████╔╝██║  ██║██║ ╚████║╚██████╔╝███████║
  ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝ ╚═════╝ ╚══════╝
{Colors.NC}"""
        print(banner)
        print(f"{Colors.GRAY}              for /LAB5/ devices{Colors.NC}")
        print(f"{Colors.GRAY}              Device: {Colors.WHITE}{device}{Colors.NC}")
        if attack_running:
            print(f"{Colors.RED}              ⚠  DEAUTH ATTACK RUNNING  ⚠{Colors.NC}")
        if blackout_running:
            print(f"{Colors.RED}              ⚠  BLACKOUT ATTACK RUNNING  ⚠{Colors.NC}")
        if sniffer_running:
            print(f"{Colors.CYAN}              📡  SNIFFER RUNNING  📡{Colors.NC}")
        if sae_overflow_running:
            print(f"{Colors.MAGENTA}              ⚠  WPA3 SAE OVERFLOW RUNNING  ⚠{Colors.NC}")
        if handshake_running:
            print(f"{Colors.YELLOW}              ⚠  HANDSHAKE CAPTURE RUNNING  ⚠{Colors.NC}")
        if portal_running:
            print(f"{Colors.BLUE}              🌐  CAPTIVE PORTAL RUNNING  🌐{Colors.NC}")
        if evil_twin_running:
            print(f"{Colors.MAGENTA}              👥  EVIL TWIN ATTACK RUNNING  👥{Colors.NC}")

    @staticmethod
    def print_main_menu() -> None:
        """Print the main menu with categories."""
        lines = [
            "",
            f"{Colors.GREEN}1){Colors.NC} Scan",
            f"{Colors.GREEN}2){Colors.NC} Sniffer",
            f"{Colors.GREEN}3){Colors.NC} Attacks",
            f"{Colors.GREEN}4){Colors.NC} Wardrive",
            f"{Colors.GREEN}5){Colors.NC} SD data",
            "",
            f"{Colors.GRAY}0){Colors.NC} Exit",
        ]
        UI.print_compact_box("MAIN MENU", lines, Colors.CYAN)

    @staticmethod
    def print_scan_menu(network_count: int, selected_networks: str) -> None:
        """Print the scan submenu."""
        lines = [
            "",
            f"{Colors.GREEN}1){Colors.NC} Scan networks",
            f"{Colors.GREEN}2){Colors.NC} Show scan results",
            f"{Colors.GREEN}3){Colors.NC} Select networks",
            "",
            f"{Colors.GRAY}0){Colors.NC} Back to main menu",
        ]
        UI.print_compact_box("SCAN", lines, Colors.CYAN)
        
        # Status line
        if network_count > 0:
            print(f"{Colors.GREEN}[+] Networks found: {network_count}{Colors.NC}")
        else:
            print(f"{Colors.GRAY}[-] No networks scanned{Colors.NC}")
        
        if selected_networks:
            print(f"{Colors.GREEN}[+] Selected: {selected_networks}{Colors.NC}")
        
        print()

    @staticmethod
    def print_sniffer_menu(sniffer_running: bool, packets_captured: int = 0) -> None:
        """Print the sniffer submenu."""
        lines = [
            "",
            f"{Colors.GREEN}1){Colors.NC} Start sniffer",
            f"{Colors.GREEN}2){Colors.NC} Show results",
            f"{Colors.GREEN}3){Colors.NC} Show probes",
            "",
            f"{Colors.GRAY}0){Colors.NC} Back to main menu",
        ]
        UI.print_compact_box("SNIFFER", lines, Colors.CYAN)
        
        # Status line
        if sniffer_running:
            print(f"{Colors.CYAN}[📡] Sniffer is RUNNING{Colors.NC}")
            print(f"{Colors.CYAN}[+] Packets captured: {packets_captured}{Colors.NC}")
        else:
            print(f"{Colors.GRAY}[-] Sniffer not running{Colors.NC}")
        
        print()

    @staticmethod
    def print_attacks_menu(selected_networks: str, attack_running: bool, blackout_running: bool,
                          sae_overflow_running: bool, handshake_running: bool, portal_running: bool,
                          evil_twin_running: bool, beacon_spam_running: bool = False,
                          arp_running: bool = False, mitm_running: bool = False) -> None:
        """Print the attacks submenu."""
        lines = [
            "",
            f"{Colors.GRAY}global WiFi attacks{Colors.NC}",
            f"{Colors.GREEN}1){Colors.NC} Deauth",
            f"{Colors.GREEN}2){Colors.NC} Blackout",
            f"{Colors.GREEN}3){Colors.NC} WPA3 SAE Overflow",
            f"{Colors.GREEN}4){Colors.NC} Handshaker",
            f"{Colors.GREEN}5){Colors.NC} Portal",
            f"{Colors.GREEN}6){Colors.NC} Evil Twin",
            f"{Colors.GREEN}7){Colors.NC} Beacon spam",
            "",
            f"{Colors.GRAY}inside network attacks{Colors.NC}",
            f"{Colors.GREEN}8){Colors.NC} ARP",
            f"{Colors.GREEN}9){Colors.NC} MITM",
            "",
            f"{Colors.RED}10){Colors.NC} Stop ALL actions",
            f"{Colors.GRAY}0){Colors.NC} Back to main menu",
        ]
        UI.print_compact_box("ATTACKS", lines, Colors.CYAN)
        
        # Status line
        if selected_networks:
            print(f"{Colors.GREEN}[+] Selected: {selected_networks}{Colors.NC}")
        else:
            print(f"{Colors.YELLOW}[!] No networks selected{Colors.NC}")
        
        if attack_running:
            print(f"{Colors.RED}[!] Deauth Attack is RUNNING{Colors.NC}")
        if blackout_running:
            print(f"{Colors.RED}[!] Blackout Attack is RUNNING{Colors.NC}")
        if sae_overflow_running:
            print(f"{Colors.MAGENTA}[!] WPA3 SAE Overflow is RUNNING{Colors.NC}")
        if handshake_running:
            print(f"{Colors.YELLOW}[!] Handshake Capture is RUNNING{Colors.NC}")
        if portal_running:
            print(f"{Colors.BLUE}[!] Captive Portal is RUNNING{Colors.NC}")
        if evil_twin_running:
            print(f"{Colors.MAGENTA}[!] Evil Twin Attack is RUNNING{Colors.NC}")
        if beacon_spam_running:
            print(f"{Colors.YELLOW}[!] Beacon spam is RUNNING{Colors.NC}")
        if arp_running:
            print(f"{Colors.YELLOW}[!] ARP attack is RUNNING{Colors.NC}")
        if mitm_running:
            print(f"{Colors.CYAN}[!] MITM attack is RUNNING{Colors.NC}")
        if not attack_running and not blackout_running and not sae_overflow_running and not handshake_running and not portal_running and not evil_twin_running and not beacon_spam_running and not arp_running and not mitm_running:
            print(f"{Colors.GRAY}[-] No attacks running{Colors.NC}")
        
        print()

    @staticmethod
    def print_portal_menu() -> None:
        """Print the portal setup submenu."""
        lines = [
            "",
            f"{Colors.GREEN}1){Colors.NC} Setup and start captive portal",
            f"{Colors.GREEN}2){Colors.NC} Show captured data",
            "",
            f"{Colors.GRAY}0){Colors.NC} Back to attacks",
        ]
        UI.print_compact_box("PORTAL", lines, Colors.CYAN)

    @staticmethod
    def print_evil_twin_menu() -> None:
        """Print the evil twin setup submenu."""
        lines = [
            "",
            f"{Colors.GREEN}1){Colors.NC} Setup and start evil twin",
            f"{Colors.GREEN}2){Colors.NC} Show captured data",
            "",
            f"{Colors.GRAY}0){Colors.NC} Back to attacks",
        ]
        UI.print_compact_box("EVIL TWIN", lines, Colors.CYAN)

    @staticmethod
    def print_system_menu() -> None:
        """Print the system submenu."""
        lines = [
            "",
            f"{Colors.GREEN}1){Colors.NC} Reboot device",
            f"{Colors.GREEN}2){Colors.NC} Ping host",
            f"{Colors.GREEN}3){Colors.NC} List SD card",
            "",
            f"{Colors.GRAY}0){Colors.NC} Back to main menu",
        ]
        UI.print_compact_box("SYSTEM", lines, Colors.CYAN)

    @staticmethod
    def print_wardrive_menu() -> None:
        """Print the wardrive submenu."""
        lines = [
            "",
            f"{Colors.GREEN}1){Colors.NC} Start wardrive",
            f"{Colors.GREEN}2){Colors.NC} GPS setup",
            "",
            f"{Colors.GRAY}0){Colors.NC} Back to main menu",
        ]
        UI.print_compact_box("WARDRIVE", lines, Colors.CYAN)

    @staticmethod
    def print_gps_setup_menu() -> None:
        """Print GPS setup submenu."""
        lines = [
            "",
            f"{Colors.GREEN}1){Colors.NC} Read current GPS module",
            f"{Colors.GREEN}2){Colors.NC} Set GPS module: m5",
            f"{Colors.GREEN}3){Colors.NC} Set GPS module: atgm",
            f"{Colors.GREEN}4){Colors.NC} Set GPS module: tab5",
            f"{Colors.GREEN}5){Colors.NC} Set GPS module: cap",
            f"{Colors.GREEN}6){Colors.NC} Start GPS raw monitor",
            "",
            f"{Colors.GRAY}0){Colors.NC} Back to wardrive menu",
        ]
        UI.print_compact_box("GPS SETUP", lines, Colors.CYAN)

    @staticmethod
    def print_sd_data_menu() -> None:
        """Print SD data submenu."""
        lines = [
            "",
            f"{Colors.GREEN}1){Colors.NC} htmls",
            f"{Colors.GREEN}2){Colors.NC} evil twin & portal",
            f"{Colors.GREEN}3){Colors.NC} warlogs",
            f"{Colors.GREEN}4){Colors.NC} handshakes",
            "",
            f"{Colors.GRAY}0){Colors.NC} Back to main menu",
        ]
        UI.print_compact_box("SD DATA", lines, Colors.CYAN)

    @staticmethod
    def print_beacon_spam_menu() -> None:
        """Print beacon spam submenu."""
        lines = [
            "",
            f"{Colors.GREEN}1){Colors.NC} Start",
            f"{Colors.GREEN}2){Colors.NC} SSID list",
            "",
            f"{Colors.GRAY}0){Colors.NC} Back to attacks",
        ]
        UI.print_compact_box("BEACON SPAM", lines, Colors.CYAN)

    @staticmethod
    def print_compact_box(title: str, lines: List[str], color: str = Colors.CYAN,
                          width: int = COMPACT_BOX_WIDTH) -> None:
        """Print a compact fixed-width box with centered title."""
        width = max(30, width)
        inner = width - 2
        print(f"{color}╔{'═' * inner}╗{Colors.NC}")
        title_text = f" {title} "
        title_len = display_width(title_text)
        if title_len > inner:
            title_text = fit_ansi_text(title_text, inner)
            title_len = display_width(title_text)
        left_pad = max(0, (inner - title_len) // 2)
        right_pad = max(0, inner - title_len - left_pad)
        print(f"{color}║{Colors.NC}{' ' * left_pad}{Colors.WHITE}{Colors.BOLD}{title_text}{Colors.NC}{' ' * right_pad}{color}║{Colors.NC}")
        print(f"{color}╠{'═' * inner}╣{Colors.NC}")
        for line in lines:
            fitted = fit_ansi_text(line, inner - 2)
            print(f"{color}║{Colors.NC} {fitted} {color}║{Colors.NC}")
        print(f"{color}╚{'═' * inner}╝{Colors.NC}")
        print()

def select_device_interactive() -> str:
    """Interactive ESP32-C5 device selector."""
    while True:
        clear_screen()
        UI.print_banner("Device setup", False, False, False, False, False, False, False)
        print(f"{Colors.GRAY}Select the ESP32-C5 device to connect{Colors.NC}")
        print()
        
        ports = list_serial_devices()
        if not ports:
            print(f"{Colors.RED}[!] No serial devices found{Colors.NC}")
            print("Options: [r] rescan, [m] manual path, [q] quit")
            choice = input("Select option: ").strip().lower()
            if choice == 'r':
                continue
            if choice == 'm':
                manual = input("Enter device path: ").strip()
                if manual:
                    return manual
                continue
            if choice == 'q':
                sys.exit(0)
            continue
        
        print(f"{Colors.CYAN}Available USB/UART devices:{Colors.NC}")
        for idx, port in enumerate(ports, 1):
            mark = (
                f"{Colors.GREEN}ESP32-C5 candidate{Colors.NC}"
                if is_probable_esp32(port)
                else f"{Colors.GRAY}other USB/UART{Colors.NC}"
            )
            desc = port.description or "Unknown"
            manuf = port.manufacturer or ""
            hwid = port.hwid or ""
            extra = f" - {manuf}" if manuf else ""
            print(f"  {idx}) {port.device}  {Colors.GRAY}{desc}{extra}{Colors.NC}  [{mark}]")
            if hwid:
                print(f"      {Colors.DIM}{hwid}{Colors.NC}")
        
        print()
        choice = input("Select device number, [r] rescan, [m] manual, [q] quit: ").strip().lower()
        if choice == 'r':
            continue
        if choice == 'm':
            manual = input("Enter device path: ").strip()
            if manual:
                return manual
            continue
        if choice == 'q':
            sys.exit(0)
        
        if not choice.isdigit():
            print(f"{Colors.RED}Invalid selection{Colors.NC}")
            time.sleep(1)
            continue
        
        index = int(choice) - 1
        if index < 0 or index >= len(ports):
            print(f"{Colors.RED}Selection out of range{Colors.NC}")
            time.sleep(1)
            continue
        
        selected = ports[index]
        desc = selected.description or "Unknown"
        confirm = input(f"Use {selected.device} ({desc})? [Y/n]: ").strip().lower()
        if confirm in ['', 'y', 'yes']:
            return selected.device

# ============================================================================
# Serial Communication
# ============================================================================
class SerialManager:
    def __init__(self, device: str):
        self.device = device
        self.serial_conn = None
        self.baud_rate = BAUD_RATE
        self.os_type = detect_os()
        self.setup_serial()
    
    def setup_serial(self) -> None:
        """Setup serial connection."""
        if not os.path.exists(self.device):
            print(f"{Colors.RED}Error: Device {self.device} does not exist{Colors.NC}")
            sys.exit(1)
        
        # Check permissions
        if not os.access(self.device, os.R_OK | os.W_OK):
            print(f"{Colors.RED}Error: No read/write access to '{self.device}'{Colors.NC}")
            print()
            print("Try running with sudo or add your user to the dialout group:")
            print("  sudo usermod -a -G dialout $USER  # Linux")
            print("  # Then log out and log back in")
            sys.exit(1)
        
        try:
            # Use Python's serial library for better cross-platform support
            self.serial_conn = serial.Serial(
                port=self.device,
                baudrate=self.baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=READ_TIMEOUT,
                write_timeout=2
            )
            # Clear any existing data
            self.serial_conn.reset_input_buffer()
            self.serial_conn.reset_output_buffer()
            
        except Exception as e:
            print(f"{Colors.RED}Error opening serial port: {e}{Colors.NC}")
            sys.exit(1)
    
    def send_command(self, command: str) -> None:
        """Send command to ESP32."""
        if not self.serial_conn:
            print(f"{Colors.RED}Serial connection not established{Colors.NC}")
            return
        
        try:
            full_command = command + "\r\n"
            self.serial_conn.write(full_command.encode('utf-8'))
            self.serial_conn.flush()
            time.sleep(0.1)
        except Exception as e:
            print(f"{Colors.RED}Error sending command: {e}{Colors.NC}")

    def clear_input(self) -> None:
        """Drop stale UART input so next read belongs to next command."""
        if not self.serial_conn:
            return
        try:
            self.serial_conn.reset_input_buffer()
        except Exception:
            pass
    
    def read_response(self, timeout: float = SCAN_TIMEOUT) -> List[str]:
        """Read response from ESP32 with timeout."""
        if not self.serial_conn:
            return []
        
        lines = []
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self.serial_conn.in_waiting:
                try:
                    line = self.serial_conn.readline().decode('utf-8', errors='replace').strip()
                    if line:
                        lines.append(line)
                except Exception as e:
                    print(f"{Colors.YELLOW}Read error: {e}{Colors.NC}")
                    continue
            else:
                # Small sleep to prevent CPU spinning
                time.sleep(0.1)
        
        return lines

    def read_until_silence(self, max_wait: float = 8.0, idle_timeout: float = 1.2) -> List[str]:
        """Read lines until no new data appears for idle_timeout seconds."""
        if not self.serial_conn:
            return []

        lines = []
        start_time = time.time()
        last_data_time = start_time

        while time.time() - start_time < max_wait:
            if self.serial_conn.in_waiting:
                try:
                    line = self.serial_conn.readline().decode('utf-8', errors='replace').strip()
                    if line:
                        lines.append(line)
                        last_data_time = time.time()
                except Exception:
                    continue
            else:
                if lines and (time.time() - last_data_time) >= idle_timeout:
                    break
                time.sleep(0.05)

        return lines
    
    def read_sniffer_data(self, update_callback, stop_event) -> None:
        """Read sniffer data with dynamic update."""
        if not self.serial_conn:
            return
        
        while not stop_event.is_set():
            if self.serial_conn.in_waiting:
                try:
                    line = self.serial_conn.readline().decode('utf-8', errors='replace').strip()
                    if line:
                        update_callback(line)
                except Exception:
                    pass
            time.sleep(0.1)
    
    def read_portal_data(self, update_callback, stop_event) -> None:
        """Read portal data with real-time updates."""
        if not self.serial_conn:
            return
        
        while not stop_event.is_set():
            if self.serial_conn.in_waiting:
                try:
                    line = self.serial_conn.readline().decode('utf-8', errors='replace').strip()
                    if line:
                        update_callback(line)
                except Exception:
                    pass
            time.sleep(0.1)
    
    def read_evil_twin_data(self, update_callback, stop_event) -> None:
        """Read evil twin data with real-time updates."""
        if not self.serial_conn:
            return
        
        while not stop_event.is_set():
            if self.serial_conn.in_waiting:
                try:
                    line = self.serial_conn.readline().decode('utf-8', errors='replace').strip()
                    if line:
                        update_callback(line)
                except Exception:
                    pass
            time.sleep(0.1)
    
    def close(self) -> None:
        """Close serial connection."""
        if self.serial_conn:
            self.serial_conn.close()

# ============================================================================
# Network Management
# ============================================================================
class NetworkManager:
    def __init__(self):
        self.networks: List[Dict[str, str]] = []
        self.network_count = 0
        self.selected_networks = ""
        self.scan_done = False
    
    def parse_network_line(self, line: str) -> Optional[Dict[str, str]]:
        """Parse a network line from ESP32 output."""
        # Expected format: "index","ssid","vendor","bssid","channel","auth","rssi","band"
        if not line.startswith('"'):
            return None
        
        try:
            # Simple CSV parsing
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) < 8:
                return None
            
            network = {
                'index': parts[0],
                'ssid': parts[1] if parts[1] else "<hidden>",
                'vendor': parts[2],
                'bssid': parts[3],
                'channel': parts[4],
                'auth': parts[5],
                'rssi': parts[6],
                'band': parts[7]
            }
            return network
        except:
            return None
    
    def add_network(self, line: str) -> None:
        """Add a network from parsed line."""
        network = self.parse_network_line(line)
        if network:
            self.networks.append(network)
            self.network_count += 1
    
    def clear_networks(self) -> None:
        """Clear all networks."""
        self.networks.clear()
        self.network_count = 0
        self.scan_done = False
    
    def set_selected_networks(self, selection: str) -> None:
        """Set selected networks."""
        self.selected_networks = selection
    
    def get_rssi_color(self, rssi_str: str) -> str:
        """Get color code for RSSI value."""
        if not rssi_str:
            return Colors.GRAY
        
        try:
            # Extract numeric value
            rssi_num = int(rssi_str.replace('dBm', '').strip())
            if rssi_num < -70:
                return Colors.RED
            elif rssi_num < -50:
                return Colors.YELLOW
            else:
                return Colors.GREEN
        except:
            return Colors.GRAY
    
    def display_networks(self) -> None:
        """Display networks in a table."""
        if self.network_count == 0:
            print(f"{Colors.YELLOW}[!] No networks scanned yet. Run a scan first.{Colors.NC}")
            print()
            input("Press Enter to continue...")
            return
        
        clear_screen()
        terminal_width = get_terminal_width()
        table_width = max(40, min(terminal_width - 4, 110))
        lines = [
            f"{Colors.WHITE}#   SSID                      BSSID              CH  RSSI   Auth{Colors.NC}",
            ""
        ]

        for network in self.networks:
            idx = network.get('index', '?')
            ssid = network.get('ssid', '?')
            bssid = network.get('bssid', '?')
            channel = network.get('channel', '?')
            auth = network.get('auth', '?')
            rssi = network.get('rssi', '?')
            
            # Truncate SSID if too long
            if len(ssid) > 24:
                ssid = ssid[:21] + "..."
            
            # Truncate auth if too long
            if len(auth) > 12:
                auth = auth[:10] + ".."
            
            rssi_color = self.get_rssi_color(rssi)
            row = (
                f"{Colors.GREEN}{idx:<3}{Colors.NC} "
                f"{ssid:<25} "
                f"{Colors.GRAY}{bssid:<17}{Colors.NC} "
                f"{channel:<3} "
                f"{rssi_color}{rssi:<6}{Colors.NC} "
                f"{auth:<12}"
            )
            lines.append(row)

        UI.print_compact_box("SCAN RESULTS", lines, Colors.CYAN, width=table_width)
        
        if self.selected_networks:
            print(f"{Colors.GREEN}[+] Selected networks: {Colors.WHITE}{self.selected_networks}{Colors.NC}")
        
        print()
        input("Press Enter to continue...")

# ============================================================================
# Main Application
# ============================================================================
class JanOS:
    def __init__(self, device: str):
        self.device = device
        self.serial_mgr = SerialManager(device)
        self.network_mgr = NetworkManager()
        self.attack_running = False
        self.blackout_running = False
        self.sniffer_running = False
        self.sae_overflow_running = False
        self.handshake_running = False
        self.portal_running = False
        self.evil_twin_running = False
        self.wardrive_running = False
        self.beacon_spam_running = False
        self.arp_running = False
        self.mitm_running = False
        self.wifi_connected = False
        self.connected_ssid = ""
        self.sniffer_packets = 0
        self.sniffer_thread = None
        self.stop_sniffer_event = threading.Event()
        self.portal_thread = None
        self.stop_portal_event = threading.Event()
        self.evil_twin_thread = None
        self.stop_evil_twin_event = threading.Event()
        self.wardrive_thread = None
        self.stop_wardrive_event = threading.Event()
        self.portal_html_files = []
        self.selected_html_index = -1
        self.selected_html_name = ""
        self.portal_ssid = ""
        self.submitted_forms = 0
        self.last_submitted_data = ""
        self.client_count = 0
        self.evil_twin_ssid = ""
        self.evil_twin_captured_data = []
        self.evil_twin_client_count = 0
        self.wardrive_logged_networks = 0
        self.wardrive_last_file = ""
        self.handshake_capture_count = 0
        self.handshake_last_file = ""
        self.handshake_last_ssid = ""
        self.last_handshake_line = ""
        self.wardrive_last_lat = ""
        self.wardrive_last_lon = ""
        self.wardrive_last_alt = ""
        self.wardrive_last_acc = ""
        self.wardrive_waiting_for_fix = False
        self.last_wardrive_line = ""
        self.os_type = detect_os()
        self.last_sniffer_line = ""
        
        if self.os_type == 'unknown':
            print(f"{Colors.RED}Error: Unsupported operating system{Colors.NC}")
            sys.exit(1)
    
    def show_usage(self) -> None:
        """Show usage information."""
        print_usage()
    
    def update_sniffer_display(self, data: str) -> None:
        """Update sniffer packet count from received data."""
        # Try to extract packet count from various formats
        import re
        if not data or data == self.last_sniffer_line:
            return
        self.last_sniffer_line = data

        match = re.search(r'(?:packets?|pkts?)\s*[:=]\s*(\d+)', data, re.IGNORECASE)
        if not match:
            match = re.search(r'(?:captured|capture)\s*[:=]?\s*(\d+)', data, re.IGNORECASE)
        if not match:
            match = re.search(r'(\d+)\s*(?:packets?|pkts?)', data, re.IGNORECASE)
        if match:
            self.sniffer_packets = int(match.group(1))
            return

        # Fallback: count lines that look like packet data
        if re.search(r'([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})', data):
            self.sniffer_packets += 1
            return

        lower = data.lower()
        ignore_prefixes = (
            "sniffer", "total", "starting", "stopping", "scan",
            "wifi", "channel", "packets", "probe", "error", "failed"
        )
        if lower.startswith(ignore_prefixes) or data.startswith(">"):
            return

        if data.strip():
            self.sniffer_packets += 1
    
    def update_portal_display(self, data: str) -> None:
        """Update portal display with real-time data."""
        # Check for client connections
        if "Client connected" in data:
            self.client_count += 1
            print(f"\n{Colors.GREEN}[+] {data}{Colors.NC}")
        
        # Check for client count updates
        elif "Client count" in data:
            match = re.search(r'Client count = (\d+)', data)
            if match:
                self.client_count = int(match.group(1))
                print(f"{Colors.BLUE}[*] Connected clients: {self.client_count}{Colors.NC}")
        
        # Check for password submissions
        elif "Password:" in data:
            self.submitted_forms += 1
            # Extract password from the line
            password_match = re.search(r'Password:\s*(.+)$', data)
            if password_match:
                password = password_match.group(1)
                self.last_submitted_data = f"Password: {password}"
                print(f"\n{Colors.GREEN}[+] Form submitted!{Colors.NC}")
                print(f"{Colors.GREEN}[+] Password captured: {password}{Colors.NC}")
        
        # Check for form data with other fields
        elif "Form data:" in data or "username:" in data.lower() or "email:" in data.lower():
            self.submitted_forms += 1
            self.last_submitted_data = data
            print(f"\n{Colors.GREEN}[+] Form submitted!{Colors.NC}")
            print(f"{Colors.GREEN}[+] {data}{Colors.NC}")
        
        # Check for data saved to file
        elif "Portal data saved" in data:
            print(f"{Colors.BLUE}[*] {data}{Colors.NC}")
        
        # Check for portal errors or status
        elif "error" in data.lower() or "failed" in data.lower():
            print(f"{Colors.RED}[!] {data}{Colors.NC}")
        elif "started successfully" in data or "enabled" in data:
            print(f"{Colors.GREEN}[+] {data}{Colors.NC}")
    
    def update_evil_twin_display(self, data: str) -> None:
        """Update evil twin display with real-time data."""
        # Check for client connections
        if "Client connected" in data:
            self.evil_twin_client_count += 1
            print(f"\n{Colors.GREEN}[+] {data}{Colors.NC}")
        
        # Check for client trying to connect to evil twin
        elif "trying to connect" in data.lower() or "association" in data.lower():
            print(f"{Colors.MAGENTA}[*] {data}{Colors.NC}")
        
        # Check for password submissions or handshake captures
        elif "Password:" in data or "Handshake captured" in data:
            self.evil_twin_captured_data.append(data)
            print(f"\n{Colors.MAGENTA}[+] {data}{Colors.NC}")
        
        # Check for handshake files
        elif ".pcap" in data or ".cap" in data or "handshake saved" in data.lower():
            print(f"{Colors.GREEN}[+] {data}{Colors.NC}")
        
        # Check for evil twin errors or status
        elif "error" in data.lower() or "failed" in data.lower():
            print(f"{Colors.RED}[!] {data}{Colors.NC}")
        elif "started successfully" in data or "broadcasting" in data:
            print(f"{Colors.GREEN}[+] {data}{Colors.NC}")

    def update_wardrive_display(self, data: str) -> None:
        """Update wardrive status from UART output."""
        if not data:
            return
        data = data.strip()
        if not data or data == self.last_wardrive_line:
            return
        self.last_wardrive_line = data

        # Parse and cache GPS fields from any line that contains them.
        lat_match = re.search(r'Lat=([-+]?\d+(?:\.\d+)?)', data)
        lon_match = re.search(r'Lon=([-+]?\d+(?:\.\d+)?)', data)
        alt_match = re.search(r'Alt=([-+]?\d+(?:\.\d+)?m?)', data)
        acc_match = re.search(r'Acc=([-+]?\d+(?:\.\d+)?m?)', data)
        if lat_match and lon_match:
            self.wardrive_last_lat = lat_match.group(1)
            self.wardrive_last_lon = lon_match.group(1)
            if alt_match:
                self.wardrive_last_alt = alt_match.group(1)
            if acc_match:
                self.wardrive_last_acc = acc_match.group(1)

        # Keep repetitive "waiting for GPS fix" messages to one line.
        if "Waiting for GPS fix" in data:
            if not self.wardrive_waiting_for_fix:
                self.wardrive_waiting_for_fix = True
                print(f"\n{Colors.YELLOW}[*] Waiting for GPS fix...{Colors.NC}")
            return

        if "GPS fix obtained" in data or "GPS fix recovered" in data:
            self.wardrive_waiting_for_fix = False
            print(f"\n{Colors.GREEN}{Colors.BOLD}[+] {data}{Colors.NC}")
            return

        if "GPS fix lost" in data:
            self.wardrive_waiting_for_fix = True
            print(f"\n{Colors.RED}{Colors.BOLD}[!] {data}{Colors.NC}")
            return

        if "Logged" in data and "/sdcard/lab/wardrives/" in data:
            logged_match = re.search(r'Logged\s+(\d+)\s+networks', data, re.IGNORECASE)
            if logged_match:
                self.wardrive_logged_networks = int(logged_match.group(1))
            file_match = re.search(r'(/sdcard/lab/wardrives/\S+)', data)
            if file_match:
                self.wardrive_last_file = file_match.group(1)
            print(f"\n{Colors.CYAN}{Colors.BOLD}[+] {data}{Colors.NC}")
            return

        lower = data.lower()

        # Keep very verbose CSV/network lines out of the terminal.
        if "," in data and data.count(",") >= 8:
            return

        # Suppress noisy informational traces that are visible in the status line.
        if lower.startswith("wardrive started") or lower.startswith("wardrive:"):
            return
        if lower.startswith("gps:"):
            return

        # Always surface actual problems.
        if "error" in lower or "failed" in lower:
            print(f"\n{Colors.RED}{Colors.BOLD}[!] {data}{Colors.NC}")

    def update_handshake_display(self, data: str) -> None:
        """Update handshake monitor from UART output."""
        if not data:
            return
        data = data.strip()
        if not data or data.startswith(">") or data == self.last_handshake_line:
            return
        self.last_handshake_line = data

        lower = data.lower()

        captured_match = re.search(r'Handshake\s*#\s*(\d+)\s*captured', data, re.IGNORECASE)
        if captured_match:
            self.handshake_capture_count = max(self.handshake_capture_count, int(captured_match.group(1)))
            print(f"\n{Colors.GREEN}{Colors.BOLD}[+] {data}{Colors.NC}")
            return

        if "handshake is complete and valid" in lower:
            print(f"\n{Colors.GREEN}{Colors.BOLD}[+] {data}{Colors.NC}")
            return

        pcap_match = re.search(r'PCAP saved:\s*(/sdcard/\S+)', data, re.IGNORECASE)
        if pcap_match:
            self.handshake_last_file = pcap_match.group(1)
            print(f"\n{Colors.GREEN}{Colors.BOLD}[+] {data}{Colors.NC}")
            return

        ssid_match = re.search(r'SSID:\s*([^,(]+)', data, re.IGNORECASE)
        if ssid_match and "handshake saved for ssid" in lower:
            self.handshake_last_ssid = ssid_match.group(1).strip()
            print(f"\n{Colors.CYAN}[*] {data}{Colors.NC}")
            return

        if "error" in lower or "failed" in lower:
            print(f"\n{Colors.RED}{Colors.BOLD}[!] {data}{Colors.NC}")
            return

        if any(key in lower for key in ("handshake", "deauth", "target", "scan", "channel", "captur", "pcap")):
            print(f"\n{Colors.CYAN}[*] {data}{Colors.NC}")
            return

    def wait_for_enter_with_status(self, status_builder, poll_interval: float = 1.0,
                                   prompt: str = "Press Enter to stop...") -> None:
        """Show status line in loop until user presses Enter."""
        print(f"{Colors.WHITE}{prompt}{Colors.NC}")
        while True:
            status = status_builder()
            print(f"\r{fit_ansi_text(status, max(20, get_terminal_width() - 1))}", end="", flush=True)
            try:
                ready, _, _ = select.select([sys.stdin], [], [], poll_interval)
                if ready:
                    sys.stdin.readline()
                    print()
                    return
            except (OSError, ValueError):
                # Non-interactive stdin: keep running until Ctrl+C.
                time.sleep(poll_interval)
    
    def do_scan(self) -> None:
        """Perform network scan."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        print()
        print(f"{Colors.YELLOW}[*] Initiating network scan...{Colors.NC}")
        print(f"{Colors.GRAY}    This may take up to {SCAN_TIMEOUT} seconds{Colors.NC}")
        print()
        
        # Clear previous networks
        self.network_mgr.clear_networks()
        
        # Send scan command
        self.serial_mgr.send_command("scan_networks")
        
        # Read response with progress display
        start_time = time.time()
        
        # Read lines from serial
        try:
            while time.time() - start_time < SCAN_TIMEOUT:
                elapsed = int(time.time() - start_time)
                print(f"\r    Elapsed: {elapsed}s / {SCAN_TIMEOUT}s  ", end="", flush=True)
                
                lines = self.serial_mgr.read_until_silence(max_wait=1.0, idle_timeout=0.4)
                for line in lines:
                    # Parse network lines
                    if line.startswith('"'):
                        self.network_mgr.add_network(line)
                    
                    # Check if scan is complete
                    if "Scan results printed" in line:
                        print(f"\n{Colors.GREEN}[+] Scan complete!{Colors.NC}")
                        self.network_mgr.scan_done = True
                        print()
                        input("Press Enter to continue...")
                        return
                
                if self.network_mgr.scan_done:
                    break
                
                time.sleep(0.1)
            
            if not self.network_mgr.scan_done:
                print(f"\n{Colors.YELLOW}[!] Timeout reached{Colors.NC}")
            
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}[!] Scan interrupted{Colors.NC}")
        
        print()
        
        if self.network_mgr.network_count > 0:
            print(f"{Colors.GREEN}[+] Found {self.network_mgr.network_count} networks!{Colors.NC}")
        else:
            print(f"{Colors.YELLOW}[!] No networks found{Colors.NC}")
        
        print()
        input("Press Enter to continue...")

    def show_scan_results(self) -> None:
        """Fetch and display latest scan results from device."""
        print(f"{Colors.YELLOW}[*] Requesting scan results from device...{Colors.NC}")
        self.serial_mgr.send_command("show_scan_results")
        lines = self.serial_mgr.read_until_silence(max_wait=6, idle_timeout=1.0)

        parsed_networks = 0
        for line in lines:
            if line.startswith('"'):
                if parsed_networks == 0:
                    self.network_mgr.clear_networks()
                self.network_mgr.add_network(line)
                parsed_networks += 1

        if parsed_networks == 0 and self.network_mgr.network_count == 0:
            print(f"{Colors.YELLOW}[!] No scan results available. Run scan first.{Colors.NC}")
            print()
            input("Press Enter to continue...")
            return

        self.network_mgr.display_networks()
    
    def select_networks_menu(self) -> None:
        """Network selection menu."""
        if self.network_mgr.network_count == 0:
            print(f"{Colors.YELLOW}[!] No networks scanned yet. Run a scan first.{Colors.NC}")
            print()
            input("Press Enter to continue...")
            return
        
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        print()
        
        # Display networks briefly
        print(f"{Colors.CYAN}Available networks:{Colors.NC}")
        print()
        for network in self.network_mgr.networks:
            idx = network.get('index', '?')
            ssid = network.get('ssid', '?')
            rssi = network.get('rssi', '?')
            print(f"  {Colors.GREEN}[{idx}]{Colors.NC} {ssid} {Colors.GRAY}(RSSI: {rssi}){Colors.NC}")
        
        print()
        print(f"{Colors.WHITE}Enter network numbers separated by spaces (e.g., 1 3 5){Colors.NC}")
        print(f"{Colors.GRAY}Or enter 'all' to select all networks{Colors.NC}")
        print()
        
        try:
            selection = input("Selection: ").strip()
        except EOFError:
            return
        
        if not selection:
            print(f"{Colors.YELLOW}[!] No selection made{Colors.NC}")
            time.sleep(1)
            return
        
        # Handle 'all' selection
        if selection.lower() == 'all':
            selection = ' '.join(str(i+1) for i in range(self.network_mgr.network_count))
        
        # Validate selection (basic check for numbers and spaces)
        if not re.match(r'^[\d\s]+$', selection):
            print(f"{Colors.RED}[!] Invalid selection. Use numbers separated by spaces.{Colors.NC}")
            time.sleep(2)
            return
        
        self.network_mgr.set_selected_networks(selection)
        
        print()
        print(f"{Colors.YELLOW}[*] Sending selection to device...{Colors.NC}")
        self.serial_mgr.send_command(f"select_networks {selection}")
        time.sleep(1)
        
        print(f"{Colors.GREEN}[+] Networks selected: {Colors.WHITE}{selection}{Colors.NC}")
        time.sleep(1)
    
    def start_sniffer(self) -> None:
        """Start sniffer with stable live counter and Enter-to-stop."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        UI.print_compact_box(
            "SNIFFER MODE",
            [
                f"{Colors.YELLOW}Starting sniffer...{Colors.NC}",
                f"{Colors.GRAY}Press any key to stop{Colors.NC}"
            ],
            Colors.CYAN
        )
        
        # Check if we have scanned networks
        if self.network_mgr.network_count > 0:
            print(f"{Colors.YELLOW}[*] Using existing scan results{Colors.NC}")
            self.serial_mgr.send_command("start_sniffer_noscan")
        else:
            print(f"{Colors.YELLOW}[*] Scanning before start...{Colors.NC}")
            self.serial_mgr.send_command("start_sniffer")
        
        # Reset packet counter
        self.sniffer_packets = 0
        self.last_sniffer_line = ""
        self.sniffer_running = True
        
        # Start background thread for reading sniffer data
        self.stop_sniffer_event.clear()
        self.sniffer_thread = threading.Thread(
            target=self.serial_mgr.read_sniffer_data,
            args=(self.update_sniffer_display, self.stop_sniffer_event)
        )
        self.sniffer_thread.daemon = True
        self.sniffer_thread.start()
        
        print(f"{Colors.CYAN}[+] Sniffer running{Colors.NC}")
        start_time = time.time()
        
        try:
            self.wait_for_enter_with_status(
                lambda: (
                    f"{Colors.CYAN}Sniffer packets: {Colors.WHITE}{self.sniffer_packets}"
                    f"{Colors.CYAN} | Time: {int(time.time() - start_time)}s{Colors.NC}"
                ),
                poll_interval=SNIFFER_UPDATE_INTERVAL
            )
        except KeyboardInterrupt:
            pass
        
        finally:
            # Stop sniffer
            print(f"\n{Colors.YELLOW}[*] Stopping sniffer...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.sniffer_running = False
            self.stop_sniffer_event.set()
            
            if self.sniffer_thread:
                self.sniffer_thread.join(timeout=2)
            
            print(f"{Colors.GREEN}[+] Sniffer stopped ({self.sniffer_packets} packets){Colors.NC}")
            input("Press Enter to continue...")
    
    def show_sniffer_results(self) -> None:
        """Show sniffer AP-client results."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        
        # Stop sniffer if it's running to get results
        if self.sniffer_running:
            print(f"{Colors.YELLOW}[*] Stopping sniffer...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.sniffer_running = False
            self.stop_sniffer_event.set()
            if self.sniffer_thread:
                self.sniffer_thread.join(timeout=2)
            time.sleep(1)
        
        # Request results from ESP32
        print(f"{Colors.CYAN}[*] Requesting results...{Colors.NC}")
        self.serial_mgr.send_command("show_sniffer_results")
        
        lines = self.serial_mgr.read_until_silence(max_wait=8, idle_timeout=1.0)
        filtered = [
            line for line in lines
            if line and not line.startswith(">") and "show_sniffer_results" not in line.lower()
        ]

        ap_count = 0
        client_count = 0
        display_lines: List[str] = []
        for line in filtered:
            if line.startswith("No APs with clients"):
                display_lines.append(f"{Colors.YELLOW}{line}{Colors.NC}")
                continue
            if line.startswith(" "):
                client_count += 1
                display_lines.append(f"{Colors.GRAY}{line}{Colors.NC}")
                continue
            ap_count += 1
            display_lines.append(f"{Colors.GREEN}{line}{Colors.NC}")

        if client_count > 0:
            self.sniffer_packets = max(self.sniffer_packets, client_count)

        summary_lines = [
            f"{Colors.YELLOW}APs: {ap_count}{Colors.NC}",
            f"{Colors.YELLOW}Clients: {client_count}{Colors.NC}",
            f"{Colors.YELLOW}Live packets counter: {self.sniffer_packets}{Colors.NC}",
        ]
        UI.print_compact_box("SNIFFER RESULTS", summary_lines, Colors.CYAN)

        if display_lines:
            print(f"{Colors.CYAN}Output:{Colors.NC}")
            for line in display_lines:
                print(line)
        else:
            print(f"{Colors.YELLOW}[!] No results received from device{Colors.NC}")
            print(f"{Colors.YELLOW}[*] Try starting the sniffer first to capture packets{Colors.NC}")
        
        print()
        input("Press Enter to continue...")
    
    def show_sniffer_probes(self) -> None:
        """Show probe requests captured by sniffer."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        print()
        
        # Stop sniffer if it's running to get results
        if self.sniffer_running:
            print(f"{Colors.YELLOW}[*] Stopping sniffer to show probe requests...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.sniffer_running = False
            self.stop_sniffer_event.set()
            if self.sniffer_thread:
                self.sniffer_thread.join(timeout=2)
            time.sleep(1)
        
        # Request probe results from ESP32
        print(f"{Colors.CYAN}[*] Requesting probe requests from device...{Colors.NC}")
        self.serial_mgr.send_command("show_probes")
        
        lines = self.serial_mgr.read_until_silence(max_wait=8, idle_timeout=1.0)
        probe_lines = []
        announced_total = None
        for line in lines:
            if not line or line.startswith(">"):
                continue
            if "show_probes" in line.lower():
                continue
            total_match = re.search(r'Probe requests:\s*(\d+)', line, re.IGNORECASE)
            if total_match:
                announced_total = int(total_match.group(1))
                continue
            probe_lines.append(line)

        UI.print_compact_box(
            "PROBE REQUESTS",
            [f"{Colors.YELLOW}Probes: {len(probe_lines)}{Colors.NC}"]
            + ([f"{Colors.YELLOW}Reported by device: {announced_total}{Colors.NC}"] if announced_total is not None else []),
            Colors.CYAN
        )
        
        if probe_lines:
            print(f"{Colors.CYAN}Output:{Colors.NC}")
            for idx, line in enumerate(probe_lines, start=1):
                print(f"{Colors.GREEN}{idx:>2}.{Colors.NC} {line}")
        else:
            print(f"{Colors.YELLOW}[!] No probe requests received from device{Colors.NC}")
            print(f"{Colors.YELLOW}[*] Try starting the sniffer first to capture probe requests{Colors.NC}")
        
        print()
        input("Press Enter to continue...")
    
    def start_deauth_attack(self) -> None:
        """Start deauth attack."""
        if not self.network_mgr.selected_networks:
            print(f"{Colors.YELLOW}[!] No networks selected. Select networks first.{Colors.NC}")
            print()
            input("Press Enter to continue...")
            return
        
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        print()
        print(f"{Colors.RED}╔══════════════════════════════════════════════════════════════════════════════╗{Colors.NC}")
        print(f"{Colors.RED}║{Colors.NC}                      {Colors.WHITE}{Colors.BOLD}⚠  DEAUTH ATTACK  ⚠{Colors.NC}                                  {Colors.RED}║{Colors.NC}")
        print(f"{Colors.RED}╠══════════════════════════════════════════════════════════════════════════════╣{Colors.NC}")
        print(f"{Colors.RED}║{Colors.NC}                                                                              {Colors.RED}║{Colors.NC}")
        
        # Calculate padding for selected networks display
        selected_len = len(self.network_mgr.selected_networks)
        padding = max(0, 45 - selected_len)
        
        print(f"{Colors.RED}║{Colors.NC}  {Colors.YELLOW}Target networks: {Colors.WHITE}{self.network_mgr.selected_networks}{Colors.NC}{' ' * padding}{Colors.RED}║{Colors.NC}")
        print(f"{Colors.RED}║{Colors.NC}                                                                              {Colors.RED}║{Colors.NC}")
        print(f"{Colors.RED}║{Colors.NC}  {Colors.GRAY}This attack will send deauthentication frames to disconnect{Colors.NC}              {Colors.RED}║{Colors.NC}")
        print(f"{Colors.RED}║{Colors.NC}  {Colors.GRAY}clients from the selected access points.{Colors.NC}                                  {Colors.RED}║{Colors.NC}")
        print(f"{Colors.RED}║{Colors.NC}                                                                              {Colors.RED}║{Colors.NC}")
        print(f"{Colors.RED}╚══════════════════════════════════════════════════════════════════════════════╝{Colors.NC}")
        print()
        
        try:
            confirm = input("Start attack? [y/N]: ").strip().lower()
        except EOFError:
            return
        
        if confirm not in ['y', 'yes']:
            print(f"{Colors.YELLOW}[!] Attack cancelled{Colors.NC}")
            time.sleep(1)
            return
        
        print()
        print(f"{Colors.RED}[*] Starting deauth attack...{Colors.NC}")
        self.serial_mgr.send_command("start_deauth")
        self.attack_running = True
        
        print(f"{Colors.RED}[+] Attack is running!{Colors.NC}")
        print()
        print(f"{Colors.WHITE}Press Enter to return to menu (attack continues in background){Colors.NC}")
        input()
    
    def start_blackout_attack(self) -> None:
        """Start blackout attack."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        print()
        print(f"{Colors.RED}╔══════════════════════════════════════════════════════════════════════════════╗{Colors.NC}")
        print(f"{Colors.RED}║{Colors.NC}                     {Colors.WHITE}{Colors.BOLD}⚠  BLACKOUT ATTACK  ⚠{Colors.NC}                                 {Colors.RED}║{Colors.NC}")
        print(f"{Colors.RED}╠══════════════════════════════════════════════════════════════════════════════╣{Colors.NC}")
        print(f"{Colors.RED}║{Colors.NC}                                                                              {Colors.RED}║{Colors.NC}")
        print(f"{Colors.RED}║{Colors.NC}  {Colors.YELLOW}Blackout Attack will jam all WiFi networks in range{Colors.NC}                          {Colors.RED}║{Colors.NC}")
        print(f"{Colors.RED}║{Colors.NC}  {Colors.YELLOW}creating complete wireless blackout.{Colors.NC}                                           {Colors.RED}║{Colors.NC}")
        print(f"{Colors.RED}║{Colors.NC}                                                                              {Colors.RED}║{Colors.NC}")
        print(f"{Colors.RED}║{Colors.NC}  {Colors.RED}⚠  WARNING: This affects ALL networks in range!{Colors.NC}                                 {Colors.RED}║{Colors.NC}")
        print(f"{Colors.RED}║{Colors.NC}                                                                              {Colors.RED}║{Colors.NC}")
        print(f"{Colors.RED}╚══════════════════════════════════════════════════════════════════════════════╝{Colors.NC}")
        print()
        
        try:
            confirm = input("Start Blackout attack? [y/N]: ").strip().lower()
        except EOFError:
            return
        
        if confirm not in ['y', 'yes']:
            print(f"{Colors.YELLOW}[!] Attack cancelled{Colors.NC}")
            time.sleep(1)
            return
        
        print()
        print(f"{Colors.RED}[*] Starting blackout attack...{Colors.NC}")
        self.serial_mgr.send_command("start_blackout")
        self.blackout_running = True
        
        print(f"{Colors.RED}[+] Blackout attack is running!{Colors.NC}")
        print()
        print(f"{Colors.WHITE}Press Enter to return to menu (attack continues in background){Colors.NC}")
        input()
    
    def start_sae_overflow_attack(self, target_network: Optional[Dict[str, str]] = None) -> None:
        """Start WPA3 SAE Overflow attack for a single selected network."""
        selected_indices = self.network_mgr.selected_networks.split()
        if len(selected_indices) != 1:
            print(f"{Colors.YELLOW}[!] SAE Overflow requires exactly ONE selected network.{Colors.NC}")
            print(f"{Colors.YELLOW}[*] Use option 3 in Attacks Menu to pick one target.{Colors.NC}")
            print()
            input("Press Enter to continue...")
            return
        
        target_index = selected_indices[0]
        if not target_network:
            for network in self.network_mgr.networks:
                if network.get('index') == target_index:
                    target_network = network
                    break
        
        target_ssid = target_network.get('ssid', f"Network #{target_index}") if target_network else f"Network #{target_index}"
        target_channel = target_network.get('channel', '?') if target_network else '?'
        target_auth = target_network.get('auth', '?') if target_network else '?'
        
        if len(target_ssid) > 40:
            target_ssid = target_ssid[:37] + "..."
        
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        print()
        print(f"{Colors.MAGENTA}╔══════════════════════════════════════════════════════════════════════════════╗{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}                   {Colors.WHITE}{Colors.BOLD}⚠  WPA3 SAE OVERFLOW  ⚠{Colors.NC}                                 {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}╠══════════════════════════════════════════════════════════════════════════════╣{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}                                                                              {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}  {Colors.GREEN}Target: {target_ssid} (#{target_index}){Colors.NC}{' ' * max(0, 51 - len(target_ssid) - len(target_index))}{Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}  {Colors.GREEN}Channel: {target_channel} | Auth: {target_auth}{Colors.NC}{' ' * max(0, 47 - len(str(target_channel)) - len(target_auth))}{Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}                                                                              {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}  {Colors.YELLOW}WPA3 SAE Overflow attack targets WPA3 networks{Colors.NC}                                 {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}  {Colors.YELLOW}using Simultaneous Authentication of Equals (SAE).{Colors.NC}                              {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}                                                                              {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}  {Colors.CYAN}UART command: sae_overflow{Colors.NC}                                                     {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}                                                                              {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}  {Colors.RED}⚠  WARNING: This attack is for educational purposes only!{Colors.NC}                       {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}                                                                              {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}╚══════════════════════════════════════════════════════════════════════════════╝{Colors.NC}")
        print()
        
        try:
            confirm = input("Start WPA3 SAE Overflow attack? [y/N]: ").strip().lower()
        except EOFError:
            return
        
        if confirm not in ['y', 'yes']:
            print(f"{Colors.YELLOW}[!] Attack cancelled{Colors.NC}")
            time.sleep(1)
            return
        
        print()
        print(f"{Colors.MAGENTA}[*] Starting WPA3 SAE Overflow attack...{Colors.NC}")
        self.serial_mgr.send_command("sae_overflow")
        self.sae_overflow_running = True
        
        print(f"{Colors.MAGENTA}[+] WPA3 SAE Overflow attack is running!{Colors.NC}")
        print()
        print(f"{Colors.WHITE}Press Enter to return to menu (attack continues in background){Colors.NC}")
        input()
    
    def start_handshake_attack(self) -> None:
        """Start WPA Handshake Capture attack."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        lines = []
        if self.network_mgr.selected_networks:
            lines.append(f"{Colors.GREEN}Target networks: {Colors.WHITE}{self.network_mgr.selected_networks}{Colors.NC}")
            lines.append(f"{Colors.GRAY}Mode: target ONLY selected networks{Colors.NC}")
        else:
            lines.append(f"{Colors.YELLOW}No networks selected{Colors.NC}")
            lines.append(f"{Colors.GRAY}Mode: scan every 5 min, target ALL networks{Colors.NC}")
        lines += [
            "",
            f"{Colors.YELLOW}Captures WPA/WPA2 handshakes for cracking.{Colors.NC}",
            f"{Colors.GRAY}Use tools like hashcat/aircrack-ng on saved PCAPs.{Colors.NC}",
            "",
            f"{Colors.CYAN}Live monitor starts after confirmation.{Colors.NC}",
            f"{Colors.GRAY}Enter = back to menu (attack keeps running).{Colors.NC}",
        ]
        UI.print_compact_box(
            "WPA HANDSHAKE CAPTURE",
            lines,
            Colors.YELLOW,
            width=max(40, min(get_terminal_width() - 4, 110))
        )
        print()
        
        try:
            confirm = input("Start Handshake Capture attack? [y/N]: ").strip().lower()
        except EOFError:
            return
        
        if confirm not in ['y', 'yes']:
            print(f"{Colors.YELLOW}[!] Attack cancelled{Colors.NC}")
            time.sleep(1)
            return
        
        self.handshake_capture_count = 0
        self.handshake_last_file = ""
        self.handshake_last_ssid = ""
        self.last_handshake_line = ""

        print(f"{Colors.YELLOW}[*] Starting Handshake Capture attack...{Colors.NC}")
        self.serial_mgr.clear_input()
        self.serial_mgr.send_command("start_handshake")
        self.handshake_running = True

        stop_event = threading.Event()
        monitor_thread = threading.Thread(
            target=self.serial_mgr.read_sniffer_data,
            args=(self.update_handshake_display, stop_event),
            daemon=True
        )
        monitor_thread.start()

        start_time = time.time()
        print(f"{Colors.CYAN}[+] Live handshake monitor active{Colors.NC}")
        try:
            self.wait_for_enter_with_status(
                lambda: (
                    f"{Colors.YELLOW}Handshaker: {int(time.time() - start_time)}s{Colors.NC}"
                    f"{Colors.CYAN} | Captured: {self.handshake_capture_count}{Colors.NC}"
                    + (
                        f"{Colors.GREEN} | SSID: {self.handshake_last_ssid}{Colors.NC}"
                        if self.handshake_last_ssid else ""
                    )
                    + (
                        f"{Colors.GREEN} | File: {self.handshake_last_file.replace('/sdcard/', '')}{Colors.NC}"
                        if self.handshake_last_file else ""
                    )
                ),
                poll_interval=1.0,
                prompt="Press Enter to go back to attacks menu (monitor closes, attack keeps running)..."
            )
        except KeyboardInterrupt:
            pass
        finally:
            stop_event.set()
            monitor_thread.join(timeout=2)

        print()
        print(f"{Colors.YELLOW}[*] Returning to attacks menu. Handshake attack remains active on ESP.{Colors.NC}")
        if self.handshake_capture_count > 0:
            print(f"{Colors.GREEN}[+] Captured handshakes in this session: {self.handshake_capture_count}{Colors.NC}")
        if self.handshake_last_file:
            print(f"{Colors.GREEN}[+] Last saved file: {self.handshake_last_file}{Colors.NC}")
        print()
        input("Press Enter to continue...")
    
    def get_html_files_from_sd(self) -> bool:
        """Get HTML files from SD card and parse them."""
        print(f"{Colors.BLUE}[*] Requesting list of HTML files from SD card...{Colors.NC}")
        self.serial_mgr.send_command("list_sd")
        
        # Wait a moment for the command to be processed
        time.sleep(1)
        
        # Read response
        lines = self.serial_mgr.read_response(timeout=3)
        
        self.portal_html_files = []
        file_count = 0
        
        if lines:
            print(f"{Colors.BLUE}[*] Parsing HTML files...{Colors.NC}")
            for line in lines:
                # Look for file entries (lines with numbers and .html extension)
                if re.search(r'^\s*\d+\s+\S+\.html\s*$', line):
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        file_num = parts[0]
                        file_name = parts[1]
                        self.portal_html_files.append({
                            'number': file_num,
                            'name': file_name,
                            'display': line.strip()
                        })
                        file_count += 1
                elif "HTML files found on SD card:" in line:
                    print(f"{Colors.GREEN}[+] {line}{Colors.NC}")
        
        if file_count > 0:
            print(f"{Colors.GREEN}[+] Found {file_count} HTML files on SD card{Colors.NC}")
            return True
        else:
            print(f"{Colors.YELLOW}[!] No HTML files found on SD card{Colors.NC}")
            print(f"{Colors.YELLOW}[*] Make sure SD card is inserted and contains HTML files{Colors.NC}")
            return False
    
    def select_html_file_menu(self) -> bool:
        """Display HTML file selection menu and get user choice."""
        if not self.portal_html_files:
            print(f"{Colors.YELLOW}[!] No HTML files available. Run list_sd first.{Colors.NC}")
            return False
        
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        terminal_width = get_terminal_width()
        table_width = max(40, min(terminal_width - 4, 110))
        lines = [
            f"{Colors.YELLOW}Available HTML files:{Colors.NC}",
            ""
        ]

        # Show available files
        for i, file_info in enumerate(self.portal_html_files, 1):
            if i <= 15:  # Show first 15 files
                display_text = file_info['display']
                if len(display_text) > 60:
                    display_text = display_text[:57] + "..."
                lines.append(f"{Colors.GREEN}{file_info['number']:>2}){Colors.NC} {display_text}")
        
        if len(self.portal_html_files) > 15:
            lines.append(f"{Colors.GRAY}... and {len(self.portal_html_files) - 15} more files{Colors.NC}")

        UI.print_compact_box("SELECT HTML FILE", lines, Colors.BLUE, width=table_width)
        
        try:
            selection = input("Enter file number to select (0 to cancel): ").strip()
        except EOFError:
            return False
        
        if not selection or selection == '0':
            print(f"{Colors.YELLOW}[!] Selection cancelled{Colors.NC}")
            time.sleep(1)
            return False
        
        try:
            index = int(selection)
            # Find the file with this number
            for file_info in self.portal_html_files:
                if file_info['number'] == selection:
                    self.selected_html_index = index
                    self.selected_html_name = file_info['name']
                    
                    print(f"{Colors.BLUE}[*] Selecting file: {file_info['name']}{Colors.NC}")
                    self.serial_mgr.send_command(f"select_html {index}")
                    
                    # Wait for response
                    time.sleep(1)
                    lines = self.serial_mgr.read_response(timeout=2)
                    for line in lines:
                        if "Loaded HTML file" in line or "Portal will now use" in line:
                            print(f"{Colors.GREEN}[+] {line}{Colors.NC}")
                    
                    print(f"{Colors.GREEN}[+] File selected: {file_info['name']}{Colors.NC}")
                    print(f"{Colors.GREEN}[+] Use 'Start Captive Portal' to launch with this HTML{Colors.NC}")
                    return True
            
            print(f"{Colors.RED}[!] File number {selection} not found{Colors.NC}")
            time.sleep(1)
            return False
        except ValueError:
            print(f"{Colors.RED}[!] Please enter a valid number{Colors.NC}")
            time.sleep(1)
            return False
    
    def select_target_network_menu(self) -> Optional[Dict[str, str]]:
        """Display network selection menu for Evil Twin target."""
        if self.network_mgr.network_count == 0:
            print(f"{Colors.YELLOW}[!] No networks scanned yet. Run a scan first.{Colors.NC}")
            return None
        
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        terminal_width = get_terminal_width()
        table_width = max(40, min(terminal_width - 4, 110))
        lines = [
            f"{Colors.YELLOW}Select a target network for Evil Twin attack:{Colors.NC}",
            "",
            f"{Colors.WHITE}#   SSID                      CH  RSSI   Auth{Colors.NC}",
            ""
        ]

        # Display networks
        for network in self.network_mgr.networks:
            idx = network.get('index', '?')
            ssid = network.get('ssid', '?')
            channel = network.get('channel', '?')
            auth = network.get('auth', '?')
            rssi = network.get('rssi', '?')
            
            # Truncate SSID if too long
            if len(ssid) > 24:
                ssid = ssid[:21] + "..."
            
            # Truncate auth if too long
            if len(auth) > 12:
                auth = auth[:10] + ".."
            
            rssi_color = self.network_mgr.get_rssi_color(rssi)
            lines.append(f"{Colors.GREEN}{idx:<3}{Colors.NC} {ssid:<25} {channel:<3} {rssi_color}{rssi:<6}{Colors.NC} {auth:<12}")

        UI.print_compact_box("SELECT TARGET NETWORK", lines, Colors.MAGENTA, width=table_width)
        
        try:
            selection = input("Enter network number to target (0 to cancel): ").strip()
        except EOFError:
            return None
        
        if not selection or selection == '0':
            print(f"{Colors.YELLOW}[!] Selection cancelled{Colors.NC}")
            time.sleep(1)
            return None
        
        try:
            index = int(selection)
            # Find the network with this index
            for network in self.network_mgr.networks:
                if network.get('index') == selection:
                    print(f"{Colors.GREEN}[+] Selected network: {network.get('ssid')} (Channel: {network.get('channel')}){Colors.NC}")
                    return network
            
            print(f"{Colors.RED}[!] Network number {selection} not found{Colors.NC}")
            time.sleep(1)
            return None
        except ValueError:
            print(f"{Colors.RED}[!] Please enter a valid number{Colors.NC}")
            time.sleep(1)
            return None

    def select_sae_target_network_menu(self) -> Optional[Dict[str, str]]:
        """Display network selection menu for SAE Overflow target."""
        if self.network_mgr.network_count == 0:
            print(f"{Colors.YELLOW}[!] No networks scanned yet. Run a scan first.{Colors.NC}")
            return None
        
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        terminal_width = get_terminal_width()
        table_width = max(40, min(terminal_width - 4, 110))
        lines = [
            f"{Colors.YELLOW}Select ONE target network for SAE Overflow attack:{Colors.NC}",
            "",
            f"{Colors.WHITE}#   SSID                      CH  RSSI   Auth{Colors.NC}",
            ""
        ]

        for network in self.network_mgr.networks:
            idx = network.get('index', '?')
            ssid = network.get('ssid', '?')
            channel = network.get('channel', '?')
            auth = network.get('auth', '?')
            rssi = network.get('rssi', '?')
            
            if len(ssid) > 24:
                ssid = ssid[:21] + "..."
            if len(auth) > 12:
                auth = auth[:10] + ".."
            
            rssi_color = self.network_mgr.get_rssi_color(rssi)
            lines.append(f"{Colors.GREEN}{idx:<3}{Colors.NC} {ssid:<25} {channel:<3} {rssi_color}{rssi:<6}{Colors.NC} {auth:<12}")

        UI.print_compact_box("SELECT SAE TARGET", lines, Colors.MAGENTA, width=table_width)
        
        try:
            selection = input("Enter ONE network number for SAE Overflow (0 to cancel): ").strip()
        except EOFError:
            return None
        
        if not selection or selection == '0':
            print(f"{Colors.YELLOW}[!] Selection cancelled{Colors.NC}")
            time.sleep(1)
            return None
        
        try:
            int(selection)
            for network in self.network_mgr.networks:
                if network.get('index') == selection:
                    print(f"{Colors.GREEN}[+] Selected SAE target: {network.get('ssid')} (Channel: {network.get('channel')}){Colors.NC}")
                    return network
            
            print(f"{Colors.RED}[!] Network number {selection} not found{Colors.NC}")
            time.sleep(1)
            return None
        except ValueError:
            print(f"{Colors.RED}[!] Please enter a valid number{Colors.NC}")
            time.sleep(1)
            return None

    def setup_and_start_sae_overflow(self) -> None:
        """Select one target network and start SAE Overflow."""
        if self.network_mgr.network_count == 0:
            print(f"{Colors.YELLOW}[!] No networks scanned yet. Run a scan first.{Colors.NC}")
            print()
            input("Press Enter to continue...")
            return
        
        target_network = None
        selected_indices = self.network_mgr.selected_networks.split()
        if len(selected_indices) == 1:
            selected_index = selected_indices[0]
            for network in self.network_mgr.networks:
                if network.get('index') == selected_index:
                    target_network = network
                    break
        
        if not target_network:
            clear_screen()
            UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                           self.sniffer_running, self.sae_overflow_running,
                           self.handshake_running, self.portal_running,
                           self.evil_twin_running)
            print()
            print(f"{Colors.MAGENTA}╔══════════════════════════════════════════════════════════════════════════════╗{Colors.NC}")
            print(f"{Colors.MAGENTA}║{Colors.NC}                {Colors.WHITE}{Colors.BOLD}⚠  SAE OVERFLOW ATTACK SETUP  ⚠{Colors.NC}                           {Colors.MAGENTA}║{Colors.NC}")
            print(f"{Colors.MAGENTA}╠══════════════════════════════════════════════════════════════════════════════╣{Colors.NC}")
            print(f"{Colors.MAGENTA}║{Colors.NC}                                                                              {Colors.MAGENTA}║{Colors.NC}")
            print(f"{Colors.MAGENTA}║{Colors.NC}  {Colors.YELLOW}Step 1: Select one target network{Colors.NC}                                              {Colors.MAGENTA}║{Colors.NC}")
            print(f"{Colors.MAGENTA}║{Colors.NC}                                                                              {Colors.MAGENTA}║{Colors.NC}")
            print(f"{Colors.MAGENTA}╚══════════════════════════════════════════════════════════════════════════════╝{Colors.NC}")
            print()
            
            target_network = self.select_sae_target_network_menu()
            if not target_network:
                print(f"{Colors.YELLOW}[!] SAE Overflow setup cancelled{Colors.NC}")
                time.sleep(1)
                return
        
        target_index = target_network.get('index', '').strip()
        if not target_index:
            print(f"{Colors.RED}[!] Selected network has no valid index{Colors.NC}")
            print()
            input("Press Enter to continue...")
            return
        
        print()
        print(f"{Colors.MAGENTA}[*] Step 2: Sync selected network to device...{Colors.NC}")
        print(f"{Colors.MAGENTA}[*] Sending: select_networks {target_index}{Colors.NC}")
        self.serial_mgr.send_command(f"select_networks {target_index}")
        self.network_mgr.set_selected_networks(target_index)
        time.sleep(1)
        
        lines = self.serial_mgr.read_response(timeout=2)
        for line in lines:
            if "selected" in line.lower() or "network" in line.lower():
                print(f"{Colors.GREEN}[+] {line}{Colors.NC}")
        
        print(f"{Colors.GREEN}[+] SAE target set to network #{target_index}{Colors.NC}")
        time.sleep(0.8)
        
        self.start_sae_overflow_attack(target_network)
    
    def setup_and_start_portal(self) -> None:
        """Full portal setup and start workflow."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        print()
        print(f"{Colors.BLUE}╔══════════════════════════════════════════════════════════════════════════════╗{Colors.NC}")
        print(f"{Colors.BLUE}║{Colors.NC}                 {Colors.WHITE}{Colors.BOLD}🌐  CAPTIVE PORTAL SETUP  🌐{Colors.NC}                               {Colors.BLUE}║{Colors.NC}")
        print(f"{Colors.BLUE}╠══════════════════════════════════════════════════════════════════════════════╣{Colors.NC}")
        print(f"{Colors.BLUE}║{Colors.NC}                                                                              {Colors.BLUE}║{Colors.NC}")
        print(f"{Colors.BLUE}║{Colors.NC}  {Colors.YELLOW}Step 1: Enter SSID name for the captive portal{Colors.NC}                                    {Colors.BLUE}║{Colors.NC}")
        print(f"{Colors.BLUE}║{Colors.NC}                                                                              {Colors.BLUE}║{Colors.NC}")
        print(f"{Colors.BLUE}╚══════════════════════════════════════════════════════════════════════════════╝{Colors.NC}")
        print()
        
        # Step 1: Get SSID name
        try:
            ssid_name = input("SSID Name (e.g., 'Free WiFi'): ").strip()
        except EOFError:
            print(f"{Colors.YELLOW}[!] Portal setup cancelled{Colors.NC}")
            time.sleep(1)
            return
        
        if not ssid_name:
            print(f"{Colors.YELLOW}[!] No SSID name entered. Using default: 'Free WiFi'{Colors.NC}")
            ssid_name = "Free WiFi"
            time.sleep(1)
        
        self.portal_ssid = ssid_name
        print(f"{Colors.GREEN}[+] SSID set to: {ssid_name}{Colors.NC}")
        print()
        
        # Step 2: Get HTML files from SD card
        print(f"{Colors.BLUE}[*] Step 2: Loading HTML files from SD card...{Colors.NC}")
        if not self.get_html_files_from_sd():
            print(f"{Colors.YELLOW}[!] Cannot proceed without HTML files{Colors.NC}")
            print()
            input("Press Enter to continue...")
            return
        
        # Step 3: Select HTML file
        print(f"{Colors.BLUE}[*] Step 3: Select HTML file for the portal{Colors.NC}")
        if not self.select_html_file_menu():
            print(f"{Colors.YELLOW}[!] No HTML file selected{Colors.NC}")
            print()
            input("Press Enter to continue...")
            return
        
        # Step 4: Confirm and start portal
        print()
        print(f"{Colors.BLUE}[*] Step 4: Starting captive portal...{Colors.NC}")
        print(f"{Colors.BLUE}[*] SSID: {self.portal_ssid}{Colors.NC}")
        print(f"{Colors.BLUE}[*] HTML file: {self.selected_html_name}{Colors.NC}")
        print()
        
        try:
            confirm = input("Start Captive Portal? [y/N]: ").strip().lower()
        except EOFError:
            print(f"{Colors.YELLOW}[!] Portal start cancelled{Colors.NC}")
            time.sleep(1)
            return
        
        if confirm not in ['y', 'yes']:
            print(f"{Colors.YELLOW}[!] Portal start cancelled{Colors.NC}")
            time.sleep(1)
            return
        
        # Start the portal
        self.start_portal_monitoring()
    
    def start_portal_monitoring(self) -> None:
        """Start portal and monitor its activity."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        print()
        print(f"{Colors.BLUE}╔══════════════════════════════════════════════════════════════════════════════╗{Colors.NC}")
        print(f"{Colors.BLUE}║{Colors.NC}                 {Colors.WHITE}{Colors.BOLD}🌐  CAPTIVE PORTAL RUNNING  🌐{Colors.NC}                              {Colors.BLUE}║{Colors.NC}")
        print(f"{Colors.BLUE}╠══════════════════════════════════════════════════════════════════════════════╣{Colors.NC}")
        print(f"{Colors.BLUE}║{Colors.NC}                                                                              {Colors.BLUE}║{Colors.NC}")
        print(f"{Colors.BLUE}║{Colors.NC}  {Colors.GREEN}SSID: {self.portal_ssid}{Colors.NC}{' ' * (70 - len(self.portal_ssid))}{Colors.BLUE}║{Colors.NC}")
        print(f"{Colors.BLUE}║{Colors.NC}  {Colors.GREEN}HTML file: {self.selected_html_name}{Colors.NC}{' ' * (65 - len(self.selected_html_name))}{Colors.BLUE}║{Colors.NC}")
        print(f"{Colors.BLUE}║{Colors.NC}                                                                              {Colors.BLUE}║{Colors.NC}")
        print(f"{Colors.BLUE}║{Colors.NC}  {Colors.YELLOW}Starting captive portal...{Colors.NC}                                                     {Colors.BLUE}║{Colors.NC}")
        print(f"{Colors.BLUE}║{Colors.NC}                                                                              {Colors.BLUE}║{Colors.NC}")
        print(f"{Colors.BLUE}╚══════════════════════════════════════════════════════════════════════════════╝{Colors.NC}")
        print()
        
        # Send start portal command
        print(f"{Colors.BLUE}[*] Sending: start_portal {self.portal_ssid}{Colors.NC}")
        self.serial_mgr.send_command(f"start_portal {self.portal_ssid}")
        
        # Wait for portal to start
        print(f"{Colors.BLUE}[*] Waiting for portal to initialize...{Colors.NC}")
        time.sleep(2)
        
        # Read initial response
        lines = self.serial_mgr.read_response(timeout=3)
        for line in lines:
            if "error" in line.lower() or "failed" in line.lower():
                print(f"{Colors.RED}[!] {line}{Colors.NC}")
                self.portal_running = False
                print()
                input("Press Enter to continue...")
                return
            elif "started successfully" in line.lower():
                print(f"{Colors.GREEN}[+] {line}{Colors.NC}")
                self.portal_running = True
            else:
                print(f"{Colors.BLUE}[*] {line}{Colors.NC}")
        
        if not self.portal_running:
            print(f"{Colors.YELLOW}[!] Portal may not have started correctly{Colors.NC}")
            print()
            input("Press Enter to continue...")
            return
        
        # Reset counters
        self.submitted_forms = 0
        self.last_submitted_data = ""
        self.client_count = 0
        
        # Start background thread for reading portal data
        self.stop_portal_event.clear()
        self.portal_thread = threading.Thread(
            target=self.serial_mgr.read_portal_data,
            args=(self.update_portal_display, self.stop_portal_event)
        )
        self.portal_thread.daemon = True
        self.portal_thread.start()
        
        print(f"{Colors.GREEN}[+] Captive portal started successfully!{Colors.NC}")
        print(f"{Colors.GREEN}[+] SSID: {self.portal_ssid}{Colors.NC}")
        print(f"{Colors.GREEN}[+] Clients can connect and will see the HTML form{Colors.NC}")
        print()
        print(f"{Colors.YELLOW}[*] Monitoring portal activity...{Colors.NC}")
        print(f"{Colors.YELLOW}[*] Press Enter to stop the portal{Colors.NC}")
        print()
        
        # Display status
        start_time = time.time()
        
        try:
            # Monitor portal activity
            while True:
                elapsed = int(time.time() - start_time)
                
                # Clear lines and update display
                print("\033[2A", end="")  # Move up 2 lines
                print("\033[2K", end="")  # Clear line
                print(f"{Colors.BLUE}[*] Portal running for: {elapsed}s{Colors.NC}")
                print("\033[2K", end="")  # Clear line
                print(f"{Colors.BLUE}[*] Submitted forms: {self.submitted_forms} | Connected clients: {self.client_count}{Colors.NC}")
                
                if self.last_submitted_data:
                    # Truncate if too long
                    display_data = self.last_submitted_data
                    if len(display_data) > 60:
                        display_data = display_data[:57] + "..."
                    print("\033[2K", end="")  # Clear line
                    print(f"{Colors.GREEN}[*] Last data: {display_data}{Colors.NC}")
                
                print()
                print(f"{Colors.YELLOW}[*] Press Enter to stop the portal{Colors.NC}")
                
                # Check for Enter key press (non-blocking)
                import sys
                import select
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    key = sys.stdin.readline()
                    if key:  # Enter pressed
                        break
                
                time.sleep(PORTAL_UPDATE_INTERVAL)
        
        except KeyboardInterrupt:
            pass
        
        finally:
            # Stop portal
            print(f"\n{Colors.YELLOW}[*] Stopping portal...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.portal_running = False
            self.stop_portal_event.set()
            
            if self.portal_thread:
                self.portal_thread.join(timeout=2)
            
            print(f"{Colors.GREEN}[+] Portal stopped{Colors.NC}")
            print(f"{Colors.GREEN}[+] Total forms submitted: {self.submitted_forms}{Colors.NC}")
            print()
            input("Press Enter to continue...")
    
    def setup_and_start_evil_twin(self) -> None:
        """Full Evil Twin setup and start workflow."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        print()
        print(f"{Colors.MAGENTA}╔══════════════════════════════════════════════════════════════════════════════╗{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}                {Colors.WHITE}{Colors.BOLD}👥  EVIL TWIN ATTACK SETUP  👥{Colors.NC}                              {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}╠══════════════════════════════════════════════════════════════════════════════╣{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}                                                                              {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}  {Colors.YELLOW}Step 1: Select target network for Evil Twin attack{Colors.NC}                                {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}                                                                              {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}╚══════════════════════════════════════════════════════════════════════════════╝{Colors.NC}")
        print()
        
        # Step 1: Select target network
        target_network = self.select_target_network_menu()
        if not target_network:
            print(f"{Colors.YELLOW}[!] Evil Twin setup cancelled{Colors.NC}")
            time.sleep(1)
            return
        
        target_ssid = target_network.get('ssid', 'Unknown')
        target_channel = target_network.get('channel', '1')
        target_index = target_network.get('index', '')
        
        print(f"{Colors.GREEN}[+] Target network selected: {target_ssid} (Channel: {target_channel}){Colors.NC}")
        print()
        
        # Ensure device has fresh scan data and selected target
        print(f"{Colors.MAGENTA}[*] Step 2: Sync target selection to device...{Colors.NC}")
        print(f"{Colors.MAGENTA}[*] Sending: scan_networks{Colors.NC}")
        self.serial_mgr.send_command("scan_networks")
        scan_complete = False
        start_time = time.time()
        while time.time() - start_time < SCAN_TIMEOUT:
            lines = self.serial_mgr.read_response(timeout=1)
            for line in lines:
                if "Scan results printed" in line:
                    scan_complete = True
                    break
            if scan_complete:
                break
        if not scan_complete:
            print(f"{Colors.YELLOW}[!] Scan may not have completed (continuing)...{Colors.NC}")
        
        if target_index:
            print(f"{Colors.MAGENTA}[*] Sending: select_networks {target_index}{Colors.NC}")
            self.serial_mgr.send_command(f"select_networks {target_index}")
            time.sleep(1)
            lines = self.serial_mgr.read_response(timeout=2)
            for line in lines:
                if "selected" in line.lower():
                    print(f"{Colors.GREEN}[+] {line}{Colors.NC}")
        else:
            print(f"{Colors.YELLOW}[!] No target index available for select_networks{Colors.NC}")
        
        # Step 2: Get HTML files from SD card
        print(f"{Colors.MAGENTA}[*] Step 3: Loading HTML files from SD card...{Colors.NC}")
        if not self.get_html_files_from_sd():
            print(f"{Colors.YELLOW}[!] Cannot proceed without HTML files{Colors.NC}")
            print()
            input("Press Enter to continue...")
            return
        
        # Step 3: Select HTML file
        print(f"{Colors.MAGENTA}[*] Step 4: Select HTML file for Evil Twin portal{Colors.NC}")
        if not self.select_html_file_menu():
            print(f"{Colors.YELLOW}[!] No HTML file selected{Colors.NC}")
            print()
            input("Press Enter to continue...")
            return
        
        # Step 4: Confirm and start Evil Twin
        print()
        print(f"{Colors.MAGENTA}[*] Step 5: Starting Evil Twin attack...{Colors.NC}")
        print(f"{Colors.MAGENTA}[*] Target SSID: {target_ssid}{Colors.NC}")
        print(f"{Colors.MAGENTA}[*] Target Channel: {target_channel}{Colors.NC}")
        print(f"{Colors.MAGENTA}[*] HTML file: {self.selected_html_name}{Colors.NC}")
        print()
        
        try:
            confirm = input("Start Evil Twin Attack? [y/N]: ").strip().lower()
        except EOFError:
            print(f"{Colors.YELLOW}[!] Evil Twin start cancelled{Colors.NC}")
            time.sleep(1)
            return
        
        if confirm not in ['y', 'yes']:
            print(f"{Colors.YELLOW}[!] Evil Twin start cancelled{Colors.NC}")
            time.sleep(1)
            return
        
        # Start the Evil Twin
        self.start_evil_twin_monitoring(target_ssid)
    
    def start_evil_twin_monitoring(self, target_ssid: str) -> None:
        """Start Evil Twin and monitor its activity."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        print()
        print(f"{Colors.MAGENTA}╔══════════════════════════════════════════════════════════════════════════════╗{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}                {Colors.WHITE}{Colors.BOLD}👥  EVIL TWIN ATTACK RUNNING  👥{Colors.NC}                             {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}╠══════════════════════════════════════════════════════════════════════════════╣{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}                                                                              {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}  {Colors.GREEN}Target SSID: {target_ssid}{Colors.NC}{' ' * (65 - len(target_ssid))}{Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}  {Colors.GREEN}HTML file: {self.selected_html_name}{Colors.NC}{' ' * (65 - len(self.selected_html_name))}{Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}                                                                              {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}  {Colors.YELLOW}Starting Evil Twin attack...{Colors.NC}                                                   {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}                                                                              {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}╚══════════════════════════════════════════════════════════════════════════════╝{Colors.NC}")
        print()
        
        # Send start evil twin command
        print(f"{Colors.MAGENTA}[*] Sending: start_evil_twin{Colors.NC}")
        self.serial_mgr.send_command("start_evil_twin")
        
        # Wait for Evil Twin to start
        print(f"{Colors.MAGENTA}[*] Waiting for Evil Twin to initialize...{Colors.NC}")
        time.sleep(2)
        
        # Read initial response
        lines = self.serial_mgr.read_response(timeout=3)
        for line in lines:
            if "error" in line.lower() or "failed" in line.lower():
                print(f"{Colors.RED}[!] {line}{Colors.NC}")
                self.evil_twin_running = False
                print()
                input("Press Enter to continue...")
                return
            elif "started successfully" in line.lower() or "broadcasting" in line.lower():
                print(f"{Colors.GREEN}[+] {line}{Colors.NC}")
                self.evil_twin_running = True
            else:
                print(f"{Colors.MAGENTA}[*] {line}{Colors.NC}")
        
        if not self.evil_twin_running:
            print(f"{Colors.YELLOW}[!] Evil Twin may not have started correctly{Colors.NC}")
            print()
            input("Press Enter to continue...")
            return
        
        # Reset counters
        self.evil_twin_captured_data = []
        self.evil_twin_client_count = 0
        self.evil_twin_ssid = target_ssid
        
        # Start background thread for reading evil twin data
        self.stop_evil_twin_event.clear()
        self.evil_twin_thread = threading.Thread(
            target=self.serial_mgr.read_evil_twin_data,
            args=(self.update_evil_twin_display, self.stop_evil_twin_event)
        )
        self.evil_twin_thread.daemon = True
        self.evil_twin_thread.start()
        
        print(f"{Colors.GREEN}[+] Evil Twin attack started successfully!{Colors.NC}")
        print(f"{Colors.GREEN}[+] Target SSID: {target_ssid}{Colors.NC}")
        print(f"{Colors.GREEN}[+] Clients will connect to fake access point{Colors.NC}")
        print(f"{Colors.GREEN}[+] Handshakes and passwords will be captured{Colors.NC}")
        print()
        print(f"{Colors.YELLOW}[*] Monitoring Evil Twin activity...{Colors.NC}")
        print(f"{Colors.YELLOW}[*] Press Enter to stop the attack{Colors.NC}")
        print()
        
        # Display status
        start_time = time.time()
        
        try:
            # Monitor Evil Twin activity
            while True:
                elapsed = int(time.time() - start_time)
                
                # Clear lines and update display
                print("\033[2A", end="")  # Move up 2 lines
                print("\033[2K", end="")  # Clear line
                print(f"{Colors.MAGENTA}[*] Evil Twin running for: {elapsed}s{Colors.NC}")
                print("\033[2K", end="")  # Clear line
                print(f"{Colors.MAGENTA}[*] Captured data: {len(self.evil_twin_captured_data)} | Connected clients: {self.evil_twin_client_count}{Colors.NC}")
                
                if self.evil_twin_captured_data:
                    # Show last captured data
                    last_data = self.evil_twin_captured_data[-1]
                    # Truncate if too long
                    if len(last_data) > 60:
                        last_data = last_data[:57] + "..."
                    print("\033[2K", end="")  # Clear line
                    print(f"{Colors.GREEN}[*] Last captured: {last_data}{Colors.NC}")
                
                print()
                print(f"{Colors.YELLOW}[*] Press Enter to stop the attack{Colors.NC}")
                
                # Check for Enter key press (non-blocking)
                import sys
                import select
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    key = sys.stdin.readline()
                    if key:  # Enter pressed
                        break
                
                time.sleep(EVIL_TWIN_UPDATE_INTERVAL)
        
        except KeyboardInterrupt:
            pass
        
        finally:
            # Stop Evil Twin
            print(f"\n{Colors.YELLOW}[*] Stopping Evil Twin attack...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.evil_twin_running = False
            self.stop_evil_twin_event.set()
            
            if self.evil_twin_thread:
                self.evil_twin_thread.join(timeout=2)
            
            print(f"{Colors.GREEN}[+] Evil Twin attack stopped{Colors.NC}")
            print(f"{Colors.GREEN}[+] Total data captured: {len(self.evil_twin_captured_data)}{Colors.NC}")
            print()
            input("Press Enter to continue...")
    
    def show_portal_captured_data(self) -> None:
        """Show captured data from portal."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        print()
        print(f"{Colors.BLUE}╔══════════════════════════════════════════════════════════════════════════════╗{Colors.NC}")
        print(f"{Colors.BLUE}║{Colors.NC}                   {Colors.WHITE}{Colors.BOLD}🔐  CAPTURED PORTAL DATA  🔐{Colors.NC}                              {Colors.BLUE}║{Colors.NC}")
        print(f"{Colors.BLUE}╠══════════════════════════════════════════════════════════════════════════════╣{Colors.NC}")
        print(f"{Colors.BLUE}║{Colors.NC}                                                                              {Colors.BLUE}║{Colors.NC}")
        
        if self.submitted_forms == 0:
            print(f"{Colors.BLUE}║{Colors.NC}  {Colors.YELLOW}No forms submitted yet.{Colors.NC}                                                     {Colors.BLUE}║{Colors.NC}")
        else:
            print(f"{Colors.BLUE}║{Colors.NC}  {Colors.GREEN}Total forms submitted: {self.submitted_forms}{Colors.NC}{' ' * (45 - len(str(self.submitted_forms)))}{Colors.BLUE}║{Colors.NC}")
            print(f"{Colors.BLUE}║{Colors.NC}  {Colors.GREEN}Connected clients: {self.client_count}{Colors.NC}{' ' * (48 - len(str(self.client_count)))}{Colors.BLUE}║{Colors.NC}")
            
            if self.last_submitted_data:
                print(f"{Colors.BLUE}║{Colors.NC}                                                                              {Colors.BLUE}║{Colors.NC}")
                print(f"{Colors.BLUE}║{Colors.NC}  {Colors.YELLOW}Last submitted data:{Colors.NC}                                                       {Colors.BLUE}║{Colors.NC}")
                print(f"{Colors.BLUE}║{Colors.NC}  {Colors.WHITE}{self.last_submitted_data}{Colors.NC}{' ' * (70 - len(self.last_submitted_data))}{Colors.BLUE}║{Colors.NC}")
        
        print(f"{Colors.BLUE}║{Colors.NC}                                                                              {Colors.BLUE}║{Colors.NC}")
        print(f"{Colors.BLUE}╚══════════════════════════════════════════════════════════════════════════════╝{Colors.NC}")
        print()
        
        # Request password log from device
        if self.portal_running:
            print(f"{Colors.YELLOW}[*] Portal is running. Data is being captured in real-time.{Colors.NC}")
        else:
            print(f"{Colors.YELLOW}[*] Requesting password log from device...{Colors.NC}")
            self.serial_mgr.send_command("show_pass")
            
            lines = self.serial_mgr.read_response(timeout=3)
            if lines:
                print(f"{Colors.CYAN}╔══════════════════════════════════════════════════════════════════════════════╗{Colors.NC}")
                print(f"{Colors.CYAN}║{Colors.NC}  {Colors.WHITE}Time{Colors.NC}           {Colors.WHITE}SSID{Colors.NC}                        {Colors.WHITE}Password/Data{Colors.NC}         {Colors.CYAN}║{Colors.NC}")
                print(f"{Colors.CYAN}╠══════════════════════════════════════════════════════════════════════════════╣{Colors.NC}")
                
                for line in lines:
                    if line and not line.startswith("Password") and not line.startswith("Log"):
                        # Parse log entry
                        parts = line.split()
                        if len(parts) >= 3:
                            timestamp = parts[0]
                            ssid = parts[1]
                            data = " ".join(parts[2:])
                            
                            # Truncate if too long
                            if len(ssid) > 20:
                                ssid = ssid[:17] + "..."
                            if len(data) > 25:
                                data = data[:22] + "..."
                            
                            print(f"{Colors.CYAN}║{Colors.NC}  {timestamp:<12} {ssid:<20} {data:<25} {Colors.CYAN}║{Colors.NC}")
                        else:
                            print(f"{Colors.CYAN}║{Colors.NC}  {Colors.GRAY}{line:<70}{Colors.NC}  {Colors.CYAN}║{Colors.NC}")
                
                print(f"{Colors.CYAN}╚══════════════════════════════════════════════════════════════════════════════╝{Colors.NC}")
            else:
                print(f"{Colors.YELLOW}[!] No password log entries found{Colors.NC}")
        
        print()
        input("Press Enter to continue...")
    
    def show_evil_twin_captured_data(self) -> None:
        """Show captured data from Evil Twin attack."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        print()
        print(f"{Colors.MAGENTA}╔══════════════════════════════════════════════════════════════════════════════╗{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}                 {Colors.WHITE}{Colors.BOLD}👥  EVIL TWIN CAPTURED DATA  👥{Colors.NC}                              {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}╠══════════════════════════════════════════════════════════════════════════════╣{Colors.NC}")
        print(f"{Colors.MAGENTA}║{Colors.NC}                                                                              {Colors.MAGENTA}║{Colors.NC}")
        
        if len(self.evil_twin_captured_data) == 0:
            print(f"{Colors.MAGENTA}║{Colors.NC}  {Colors.YELLOW}No data captured yet.{Colors.NC}                                                       {Colors.MAGENTA}║{Colors.NC}")
        else:
            print(f"{Colors.MAGENTA}║{Colors.NC}  {Colors.GREEN}Total data captured: {len(self.evil_twin_captured_data)}{Colors.NC}{' ' * (43 - len(str(len(self.evil_twin_captured_data))))}{Colors.MAGENTA}║{Colors.NC}")
            print(f"{Colors.MAGENTA}║{Colors.NC}  {Colors.GREEN}Connected clients: {self.evil_twin_client_count}{Colors.NC}{' ' * (48 - len(str(self.evil_twin_client_count)))}{Colors.MAGENTA}║{Colors.NC}")
            
            if self.evil_twin_ssid:
                print(f"{Colors.MAGENTA}║{Colors.NC}  {Colors.GREEN}Target SSID: {self.evil_twin_ssid}{Colors.NC}{' ' * (55 - len(self.evil_twin_ssid))}{Colors.MAGENTA}║{Colors.NC}")
        
        print(f"{Colors.MAGENTA}║{Colors.NC}                                                                              {Colors.MAGENTA}║{Colors.NC}")
        print(f"{Colors.MAGENTA}╚══════════════════════════════════════════════════════════════════════════════╝{Colors.NC}")
        print()
        
        if self.evil_twin_captured_data:
            print(f"{Colors.CYAN}╔══════════════════════════════════════════════════════════════════════════════╗{Colors.NC}")
            print(f"{Colors.CYAN}║{Colors.NC}  {Colors.WHITE}#{Colors.NC}  {Colors.WHITE}Captured Data{Colors.NC}                                                      {Colors.CYAN}║{Colors.NC}")
            print(f"{Colors.CYAN}╠══════════════════════════════════════════════════════════════════════════════╣{Colors.NC}")
            
            for i, data in enumerate(self.evil_twin_captured_data[-10:], 1):  # Show last 10 entries
                display_data = data
                if len(display_data) > 70:
                    display_data = display_data[:67] + "..."
                print(f"{Colors.CYAN}║{Colors.NC}  {Colors.GREEN}{i:2}){Colors.NC} {display_data:<70}{Colors.CYAN}║{Colors.NC}")
            
            print(f"{Colors.CYAN}╚══════════════════════════════════════════════════════════════════════════════╝{Colors.NC}")
            print()
        
        if self.evil_twin_running:
            print(f"{Colors.YELLOW}[*] Evil Twin is running. Data is being captured in real-time.{Colors.NC}")
        else:
            print(f"{Colors.YELLOW}[*] Evil Twin is not running. Start the attack to capture data.{Colors.NC}")
        
        print()
        input("Press Enter to continue...")

    def _extract_numbered_entries(self, lines: List[str]) -> List[str]:
        """Extract numbered entries in form: '1 value' or '1) value'."""
        entries: List[str] = []
        for line in lines:
            if not line or line.startswith(">"):
                continue
            match = re.match(r'^\s*(\d+)[\)\.]?\s+(.+)$', line)
            if not match:
                continue
            value = match.group(2).strip()
            if value:
                entries.append(value)
        return entries

    def _run_ssid_list_command(self) -> Tuple[List[str], List[str]]:
        """Return SSID list from /sdcard/lab/ssids.txt and raw lines."""
        self.serial_mgr.clear_input()
        self.serial_mgr.send_command("list_ssids")
        time.sleep(0.4)
        lines = self.serial_mgr.read_until_silence(max_wait=4, idle_timeout=0.8)

        lower_text = "\n".join(line.lower() for line in lines)
        unknown_markers = (
            "unknown command",
            "command not found",
            "not recognized",
            "invalid command",
        )
        # Fallback for older firmware where only list_ssid exists.
        if any(marker in lower_text for marker in unknown_markers):
            self.serial_mgr.clear_input()
            self.serial_mgr.send_command("list_ssid")
            time.sleep(0.4)
            lines = self.serial_mgr.read_until_silence(max_wait=4, idle_timeout=0.8)

        return self._extract_numbered_entries(lines), lines

    def start_beacon_spam_attack(self) -> None:
        """Start beacon spam using SSIDs from /sdcard/lab/ssids.txt."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running,
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        UI.print_compact_box(
            "BEACON SPAM",
            [
                f"{Colors.YELLOW}Starting from /sdcard/lab/ssids.txt{Colors.NC}",
                f"{Colors.GRAY}Edit SSID list in: Attacks > Beacon spam > SSID list{Colors.NC}",
            ],
            Colors.CYAN
        )

        self.serial_mgr.clear_input()
        self.serial_mgr.send_command("start_beacon_spam_ssids")
        time.sleep(0.6)
        lines = self.serial_mgr.read_until_silence(max_wait=6, idle_timeout=1.0)

        for line in lines:
            if line and not line.startswith(">"):
                print(f"{Colors.CYAN}{line}{Colors.NC}")

        lower_text = "\n".join(line.lower() for line in lines)
        fail_markers = (
            "not found",
            "is empty",
            "failed",
            "usage:",
            "already running",
            "error",
        )
        has_failure = any(marker in lower_text for marker in fail_markers)
        has_success = "beacon spam started" in lower_text

        if has_success or (lines and not has_failure):
            self.beacon_spam_running = True
            print(f"{Colors.GREEN}[+] Beacon spam is running{Colors.NC}")
            print(f"{Colors.GRAY}Use 'Stop ALL actions' to stop it.{Colors.NC}")
        else:
            self.beacon_spam_running = False
            print(f"{Colors.YELLOW}[!] Beacon spam was not started{Colors.NC}")

        print()
        input("Press Enter to continue...")

    def beacon_spam_ssid_list_menu(self) -> None:
        """Manage SSIDs stored in /sdcard/lab/ssids.txt."""
        while True:
            clear_screen()
            UI.print_banner(self.device, self.attack_running, self.blackout_running,
                           self.sniffer_running, self.sae_overflow_running,
                           self.handshake_running, self.portal_running,
                           self.evil_twin_running)

            ssids, lines = self._run_ssid_list_command()
            box_lines: List[str] = []

            if ssids:
                for idx, ssid in enumerate(ssids, 1):
                    box_lines.append(f"{Colors.GREEN}{idx:>2}){Colors.NC} {ssid}")
            else:
                no_file = any("not found" in line.lower() for line in lines if line)
                if no_file:
                    box_lines.append(f"{Colors.YELLOW}ssids.txt not found on SD card{Colors.NC}")
                else:
                    box_lines.append(f"{Colors.YELLOW}No SSIDs in /sdcard/lab/ssids.txt{Colors.NC}")

            UI.print_compact_box("SSID LIST", box_lines, Colors.CYAN, width=max(40, min(get_terminal_width() - 4, 110)))
            print(f"{Colors.GREEN}1){Colors.NC} Add SSID")
            print(f"{Colors.GREEN}2){Colors.NC} Remove SSID")
            print(f"{Colors.GRAY}0){Colors.NC} Back")
            print()

            choice = input("Select option: ").strip()
            if choice == '0':
                return
            if choice == '1':
                new_ssid = input("SSID to add: ").strip()
                clean_ssid = new_ssid.replace('"', '').strip()
                if not clean_ssid:
                    print(f"{Colors.YELLOW}[!] SSID cannot be empty{Colors.NC}")
                    time.sleep(1)
                    continue
                if len(clean_ssid) > 32:
                    print(f"{Colors.YELLOW}[!] SSID too long, trimmed to 32 chars{Colors.NC}")
                    clean_ssid = clean_ssid[:32]

                self.serial_mgr.clear_input()
                self.serial_mgr.send_command(f'add_ssid "{clean_ssid}"')
                time.sleep(0.4)
                resp = self.serial_mgr.read_until_silence(max_wait=4, idle_timeout=0.8)
                print()
                for line in resp:
                    if line and not line.startswith(">"):
                        print(f"{Colors.CYAN}{line}{Colors.NC}")
                print()
                input("Press Enter to continue...")
                continue
            if choice == '2':
                if not ssids:
                    print(f"{Colors.YELLOW}[!] No SSIDs to remove{Colors.NC}")
                    time.sleep(1)
                    continue

                idx_text = input("SSID number to remove: ").strip()
                if not idx_text.isdigit():
                    print(f"{Colors.RED}[!] Invalid number{Colors.NC}")
                    time.sleep(1)
                    continue

                idx = int(idx_text)
                if idx < 1 or idx > len(ssids):
                    print(f"{Colors.RED}[!] Number out of range{Colors.NC}")
                    time.sleep(1)
                    continue

                confirm = input(f"Remove '{ssids[idx - 1]}'? [y/N]: ").strip().lower()
                if confirm not in ['y', 'yes']:
                    print(f"{Colors.YELLOW}[!] Remove cancelled{Colors.NC}")
                    time.sleep(1)
                    continue

                self.serial_mgr.clear_input()
                self.serial_mgr.send_command(f"remove_ssid {idx}")
                time.sleep(0.4)
                resp = self.serial_mgr.read_until_silence(max_wait=4, idle_timeout=0.8)
                print()
                for line in resp:
                    if line and not line.startswith(">"):
                        print(f"{Colors.CYAN}{line}{Colors.NC}")
                print()
                input("Press Enter to continue...")
                continue

            print(f"{Colors.RED}Invalid option{Colors.NC}")
            time.sleep(1)

    def beacon_spam_menu(self) -> None:
        """Beacon spam submenu."""
        while True:
            try:
                clear_screen()
                UI.print_banner(self.device, self.attack_running, self.blackout_running,
                               self.sniffer_running, self.sae_overflow_running,
                               self.handshake_running, self.portal_running,
                               self.evil_twin_running)
                UI.print_beacon_spam_menu()
                if self.beacon_spam_running:
                    print(f"{Colors.YELLOW}[!] Beacon spam is RUNNING{Colors.NC}")
                    print()

                choice = input("Select option: ").strip()
                if choice == '1':
                    self.start_beacon_spam_attack()
                elif choice == '2':
                    self.beacon_spam_ssid_list_menu()
                elif choice == '0':
                    return
                else:
                    print(f"{Colors.RED}Invalid option{Colors.NC}")
                    time.sleep(1)
            except (KeyboardInterrupt, EOFError):
                print(f"\n{Colors.YELLOW}[*] Returning to attacks menu{Colors.NC}")
                time.sleep(1)
                return

    def _parse_host_entries(self, lines: List[str]) -> List[Tuple[str, str]]:
        """Parse list_hosts output into unique (ip, mac) entries."""
        hosts: List[Tuple[str, str]] = []
        seen = set()
        for line in lines:
            if not line or line.startswith(">"):
                continue

            match = re.search(
                r'(\d{1,3}(?:\.\d{1,3}){3})\s*->\s*(([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})',
                line
            )
            if not match:
                continue

            ip = match.group(1)
            mac = match.group(2).upper()
            key = (ip, mac)
            if key in seen:
                continue
            seen.add(key)
            hosts.append(key)

        return hosts

    def _scan_networks_for_connect(self) -> List[Dict[str, str]]:
        """Scan nearby WiFi networks and return parsed entries."""
        print(f"{Colors.YELLOW}[*] Scanning nearby WiFi networks...{Colors.NC}")
        print(f"{Colors.GRAY}    This may take up to {SCAN_TIMEOUT} seconds{Colors.NC}")
        print()

        self.serial_mgr.clear_input()
        self.serial_mgr.send_command("scan_networks")

        start_time = time.time()
        complete = False
        networks_by_index: Dict[str, Dict[str, str]] = {}

        while time.time() - start_time < SCAN_TIMEOUT:
            elapsed = int(time.time() - start_time)
            print(f"\r    Elapsed: {elapsed}s / {SCAN_TIMEOUT}s  ", end="", flush=True)
            lines = self.serial_mgr.read_until_silence(max_wait=1.0, idle_timeout=0.4)

            for line in lines:
                if line.startswith('"'):
                    parsed = self.network_mgr.parse_network_line(line)
                    if parsed:
                        key = parsed.get('index', '').strip() or str(len(networks_by_index) + 1)
                        networks_by_index[key] = parsed

                if "Scan results printed" in line:
                    complete = True

            if complete:
                break
            time.sleep(0.1)

        print()

        if not networks_by_index:
            # Fallback when scan output was delayed but results are already cached on ESP.
            print(f"{Colors.YELLOW}[*] No direct scan output, requesting cached results...{Colors.NC}")
            self.serial_mgr.clear_input()
            self.serial_mgr.send_command("show_scan_results")
            time.sleep(0.5)
            lines = self.serial_mgr.read_until_silence(max_wait=6, idle_timeout=1.0)
            for line in lines:
                if line.startswith('"'):
                    parsed = self.network_mgr.parse_network_line(line)
                    if parsed:
                        key = parsed.get('index', '').strip() or str(len(networks_by_index) + 1)
                        networks_by_index[key] = parsed

        networks = list(networks_by_index.values())

        def _sort_key(network: Dict[str, str]) -> Tuple[int, int]:
            index = network.get('index', '').strip()
            if index.isdigit():
                return (0, int(index))
            return (1, 9999)

        networks.sort(key=_sort_key)

        # Keep global scan cache in sync for other menus.
        if networks:
            self.network_mgr.networks = [dict(network) for network in networks]
            self.network_mgr.network_count = len(networks)
            self.network_mgr.scan_done = True

        return networks

    def _select_network_for_connect(self, networks: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
        """Show scanned networks and return selected entry."""
        lines = [
            f"{Colors.WHITE}#   SSID                     CH  RSSI  Auth{Colors.NC}",
            "",
        ]

        for position, network in enumerate(networks[:30], start=1):
            index = network.get('index', str(position))
            ssid = network.get('ssid', '<hidden>')
            channel = network.get('channel', '?')
            auth = network.get('auth', '?')
            rssi = network.get('rssi', '?')

            if len(ssid) > 24:
                ssid = ssid[:21] + "..."
            if len(auth) > 14:
                auth = auth[:12] + ".."

            rssi_color = self.network_mgr.get_rssi_color(rssi)
            lines.append(
                f"{Colors.GREEN}{index:<3}{Colors.NC} "
                f"{ssid:<24} {channel:<3} {rssi_color}{rssi:<5}{Colors.NC} {auth:<14}"
            )

        if len(networks) > 30:
            lines.append(f"{Colors.GRAY}... and {len(networks) - 30} more networks{Colors.NC}")

        UI.print_compact_box(
            "SELECT WIFI NETWORK",
            lines,
            Colors.CYAN,
            width=max(40, min(get_terminal_width() - 4, 110))
        )

        try:
            selection = input("Choose network number (0 to cancel): ").strip()
        except EOFError:
            return None

        if not selection or selection == '0':
            return None

        for network in networks:
            if network.get('index', '').strip() == selection:
                return network

        # Fallback by position if ESP index does not match visible order.
        if selection.isdigit():
            position = int(selection)
            if 1 <= position <= len(networks):
                return networks[position - 1]

        print(f"{Colors.RED}[!] Invalid network selection{Colors.NC}")
        time.sleep(1)
        return None

    def _connect_wifi_sta(self, ssid: str, password: str) -> bool:
        """Connect device to WiFi STA mode."""
        clean_ssid = ssid.replace('"', '').strip()
        clean_password = password.replace('"', '')
        if not clean_ssid:
            print(f"{Colors.RED}[!] SSID cannot be empty{Colors.NC}")
            time.sleep(1)
            return False

        command_variants = [f'wifi_connect "{clean_ssid}" "{clean_password}"']
        if " " not in clean_ssid and " " not in clean_password:
            if clean_password:
                command_variants.append(f"wifi_connect {clean_ssid} {clean_password}")
            else:
                command_variants.append(f'wifi_connect {clean_ssid} ""')

        for attempt_index, command in enumerate(command_variants, start=1):
            print(f"{Colors.YELLOW}[*] Sending: {command}{Colors.NC}")
            self.serial_mgr.clear_input()
            self.serial_mgr.send_command(command)
            time.sleep(0.6)
            lines = self.serial_mgr.read_until_silence(max_wait=14, idle_timeout=1.2)
            clean_lines = [line for line in lines if line and not line.startswith(">")]

            for line in clean_lines:
                print(f"{Colors.CYAN}{line}{Colors.NC}")

            lower_text = "\n".join(line.lower() for line in clean_lines)
            has_success = (
                "success" in lower_text
                or "connected to ssid" in lower_text
                or "wi-fi: connected" in lower_text
                or "wifi: connected" in lower_text
            )
            has_failure = any(
                marker in lower_text
                for marker in (
                    "failed",
                    "error",
                    "usage:",
                    "invalid",
                    "wrong password",
                    "auth fail",
                    "no ap found",
                )
            )

            if has_success and not has_failure:
                self.wifi_connected = True
                self.connected_ssid = clean_ssid
                print(f"{Colors.GREEN}[+] Connected to WiFi: {clean_ssid}{Colors.NC}")
                return True

            if attempt_index < len(command_variants):
                print(f"{Colors.YELLOW}[*] Retrying with alternate command format...{Colors.NC}")

        self.wifi_connected = False
        self.connected_ssid = ""
        print(f"{Colors.RED}[!] WiFi connection failed{Colors.NC}")
        return False

    def _prepare_inside_network_access(self, attack_name: str) -> bool:
        """Ensure WiFi connection before ARP/MITM attack."""
        while True:
            clear_screen()
            UI.print_banner(self.device, self.attack_running, self.blackout_running,
                           self.sniffer_running, self.sae_overflow_running,
                           self.handshake_running, self.portal_running,
                           self.evil_twin_running)

            setup_lines = [
                f"{Colors.YELLOW}{attack_name} requires active WiFi STA connection.{Colors.NC}",
                f"{Colors.GRAY}Choose how to connect before starting the attack.{Colors.NC}",
                "",
                f"{Colors.GREEN}1){Colors.NC} Scan nearby networks and choose target",
                f"{Colors.GREEN}2){Colors.NC} Enter SSID and password manually",
                "",
                f"{Colors.GRAY}0){Colors.NC} Cancel",
            ]
            if self.wifi_connected and self.connected_ssid:
                setup_lines.insert(2, f"{Colors.CYAN}Current session SSID: {self.connected_ssid}{Colors.NC}")

            UI.print_compact_box(
                "INSIDE NETWORK SETUP",
                setup_lines,
                Colors.CYAN,
                width=max(40, min(get_terminal_width() - 4, 110))
            )

            try:
                choice = input("Select option: ").strip()
            except EOFError:
                return False

            if choice == '0':
                return False

            if choice == '1':
                networks = self._scan_networks_for_connect()
                if not networks:
                    print(f"{Colors.YELLOW}[!] No networks found. Try manual SSID/password.{Colors.NC}")
                    print()
                    input("Press Enter to continue...")
                    continue

                selected_network = self._select_network_for_connect(networks)
                if not selected_network:
                    continue

                ssid = selected_network.get('ssid', '').strip()
                auth = selected_network.get('auth', '').strip()
                if not ssid or ssid == "<hidden>":
                    print(f"{Colors.YELLOW}[!] Selected network has hidden SSID. Use manual mode.{Colors.NC}")
                    print()
                    input("Press Enter to continue...")
                    continue

                is_open_network = any(token in auth.lower() for token in ("open", "none"))
                print(f"{Colors.GREEN}[+] Selected SSID: {ssid}{Colors.NC}")
                if auth:
                    print(f"{Colors.GRAY}[*] Auth: {auth}{Colors.NC}")
                try:
                    if is_open_network:
                        password = input("Password (Enter for open network): ")
                    else:
                        password = input("Password: ")
                except EOFError:
                    return False

                if not is_open_network and not password:
                    print(f"{Colors.YELLOW}[!] Password is required for this network{Colors.NC}")
                    time.sleep(1)
                    continue

                if self._connect_wifi_sta(ssid, password):
                    return True

                print()
                input("Press Enter to retry setup...")
                continue

            if choice == '2':
                try:
                    ssid = input("SSID: ").strip()
                    password = input("Password (leave empty for open network): ")
                except EOFError:
                    return False

                if not ssid:
                    print(f"{Colors.RED}[!] SSID cannot be empty{Colors.NC}")
                    time.sleep(1)
                    continue

                if self._connect_wifi_sta(ssid, password):
                    return True

                print()
                input("Press Enter to retry setup...")
                continue

            print(f"{Colors.RED}Invalid option{Colors.NC}")
            time.sleep(1)

    def start_arp_attack(self) -> None:
        """Start ARP poisoning attack against selected host."""
        if not self._prepare_inside_network_access("ARP"):
            print(f"{Colors.YELLOW}[!] ARP setup cancelled{Colors.NC}")
            time.sleep(1)
            return

        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running,
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        UI.print_compact_box(
            "ARP ATTACK",
            [
                f"{Colors.YELLOW}Inside-network attack (requires WiFi STA connection).{Colors.NC}",
                f"{Colors.GRAY}Workflow: list_hosts -> choose target -> arp_ban.{Colors.NC}",
                f"{Colors.CYAN}Connected SSID: {self.connected_ssid or 'unknown'}{Colors.NC}",
            ],
            Colors.CYAN,
            width=max(40, min(get_terminal_width() - 4, 110))
        )

        print(f"{Colors.YELLOW}[*] Scanning local network hosts...{Colors.NC}")
        self.serial_mgr.clear_input()
        self.serial_mgr.send_command("list_hosts")
        time.sleep(0.6)
        lines = self.serial_mgr.read_until_silence(max_wait=8, idle_timeout=1.0)
        clean_lines = [line for line in lines if line and not line.startswith(">")]

        hosts = self._parse_host_entries(clean_lines)
        lower_text = "\n".join(line.lower() for line in clean_lines)
        if not hosts:
            if clean_lines:
                for line in clean_lines:
                    print(f"{Colors.CYAN}{line}{Colors.NC}")
            if "not connected" in lower_text or "wifi_connect" in lower_text:
                self.wifi_connected = False
                self.connected_ssid = ""
                print(f"{Colors.YELLOW}[!] Device is not connected to WiFi. Run setup again.{Colors.NC}")
            else:
                print(f"{Colors.YELLOW}[!] No hosts discovered on local network{Colors.NC}")
            print()
            input("Press Enter to continue...")
            return

        host_lines = [
            f"{Colors.WHITE}#   IP Address        MAC Address{Colors.NC}",
            "",
        ]
        for idx, (ip, mac) in enumerate(hosts, start=1):
            host_lines.append(f"{Colors.GREEN}{idx:<3}{Colors.NC} {ip:<16} {Colors.GRAY}{mac}{Colors.NC}")
        UI.print_compact_box(
            "DISCOVERED HOSTS",
            host_lines,
            Colors.CYAN,
            width=max(40, min(get_terminal_width() - 4, 110))
        )

        try:
            target_choice = input("Select host number to ban (0 to cancel): ").strip()
        except EOFError:
            return

        if target_choice in ['', '0']:
            print(f"{Colors.YELLOW}[!] ARP attack cancelled{Colors.NC}")
            time.sleep(1)
            return

        if not target_choice.isdigit():
            print(f"{Colors.RED}[!] Invalid host number{Colors.NC}")
            time.sleep(1)
            return

        target_index = int(target_choice)
        if target_index < 1 or target_index > len(hosts):
            print(f"{Colors.RED}[!] Host number out of range{Colors.NC}")
            time.sleep(1)
            return

        target_ip, target_mac = hosts[target_index - 1]
        try:
            confirm = input(f"Start ARP ban on {target_ip} ({target_mac})? [y/N]: ").strip().lower()
        except EOFError:
            return

        if confirm not in ['y', 'yes']:
            print(f"{Colors.YELLOW}[!] ARP attack cancelled{Colors.NC}")
            time.sleep(1)
            return

        print(f"{Colors.YELLOW}[*] Sending: arp_ban {target_mac} {target_ip}{Colors.NC}")
        self.serial_mgr.clear_input()
        self.serial_mgr.send_command(f"arp_ban {target_mac} {target_ip}")
        time.sleep(0.5)
        response = self.serial_mgr.read_until_silence(max_wait=5, idle_timeout=0.8)

        for line in response:
            if line and not line.startswith(">"):
                print(f"{Colors.CYAN}{line}{Colors.NC}")

        lower_resp = "\n".join(line.lower() for line in response)
        fail_markers = ("usage:", "not connected", "failed", "error", "invalid", "unknown command")
        has_failure = any(marker in lower_resp for marker in fail_markers)

        if has_failure:
            self.arp_running = False
            print(f"{Colors.YELLOW}[!] ARP attack was not started{Colors.NC}")
        else:
            self.arp_running = True
            print(f"{Colors.GREEN}[+] ARP attack is running{Colors.NC}")
            print(f"{Colors.GRAY}Use 'Stop ALL actions' to stop it.{Colors.NC}")

        print()
        input("Press Enter to continue...")

    def start_mitm_attack(self) -> None:
        """Start MITM mode via PCAP net capture."""
        if not self._prepare_inside_network_access("MITM"):
            print(f"{Colors.YELLOW}[!] MITM setup cancelled{Colors.NC}")
            time.sleep(1)
            return

        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running,
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        UI.print_compact_box(
            "MITM ATTACK",
            [
                f"{Colors.YELLOW}Starts MITM in net mode via: start_pcap net{Colors.NC}",
                f"{Colors.GRAY}Requires active WiFi STA connection (wifi_connect).{Colors.NC}",
                f"{Colors.CYAN}Connected SSID: {self.connected_ssid or 'unknown'}{Colors.NC}",
            ],
            Colors.CYAN,
            width=max(40, min(get_terminal_width() - 4, 110))
        )

        try:
            confirm = input("Start MITM attack now? [y/N]: ").strip().lower()
        except EOFError:
            return

        if confirm not in ['y', 'yes']:
            print(f"{Colors.YELLOW}[!] MITM attack cancelled{Colors.NC}")
            time.sleep(1)
            return

        print(f"{Colors.YELLOW}[*] Sending: start_pcap net{Colors.NC}")
        self.serial_mgr.clear_input()
        self.serial_mgr.send_command("start_pcap net")
        time.sleep(0.6)
        lines = self.serial_mgr.read_until_silence(max_wait=8, idle_timeout=1.0)

        for line in lines:
            if line and not line.startswith(">"):
                print(f"{Colors.CYAN}{line}{Colors.NC}")

        lower_text = "\n".join(line.lower() for line in lines)
        fail_markers = ("usage:", "not connected", "failed", "error", "invalid", "unknown command")
        has_failure = any(marker in lower_text for marker in fail_markers)
        has_success = "pcap net capture started" in lower_text

        if has_success or (lines and not has_failure):
            self.mitm_running = True
            print(f"{Colors.GREEN}[+] MITM attack is running{Colors.NC}")
            print(f"{Colors.GRAY}Use 'Stop ALL actions' to stop it.{Colors.NC}")
        else:
            self.mitm_running = False
            if "not connected" in lower_text or "wifi_connect" in lower_text:
                self.wifi_connected = False
                self.connected_ssid = ""
            print(f"{Colors.YELLOW}[!] MITM attack was not started{Colors.NC}")

        print()
        input("Press Enter to continue...")

    def run_gps_module_command(self, command: str) -> None:
        """Send GPS module command and print response."""
        print(f"{Colors.YELLOW}[*] Sending: {command}{Colors.NC}")
        self.serial_mgr.send_command(command)
        time.sleep(0.5)
        lines = self.serial_mgr.read_until_silence(max_wait=5, idle_timeout=1.0)
        if not lines:
            print(f"{Colors.GRAY}[-] No response{Colors.NC}")
        else:
            for line in lines:
                print(line)
        print()
        input("Press Enter to continue...")

    def start_gps_raw_monitor(self) -> None:
        """Start raw GPS monitor until Enter is pressed."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running,
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        UI.print_compact_box(
            "GPS RAW",
            [
                f"{Colors.YELLOW}Reading raw NMEA output...{Colors.NC}",
                f"{Colors.GRAY}Press Enter to stop{Colors.NC}",
            ],
            Colors.CYAN
        )

        self.stop_wardrive_event.clear()

        def gps_callback(line: str) -> None:
            if line and not line.startswith(">"):
                print(f"\n{Colors.GRAY}{line}{Colors.NC}")

        self.serial_mgr.send_command("start_gps_raw")
        gps_thread = threading.Thread(
            target=self.serial_mgr.read_sniffer_data,
            args=(gps_callback, self.stop_wardrive_event),
            daemon=True
        )
        gps_thread.start()

        try:
            self.wait_for_enter_with_status(
                lambda: f"{Colors.CYAN}Monitoring GPS raw stream...{Colors.NC}",
                poll_interval=0.5
            )
        except KeyboardInterrupt:
            pass
        finally:
            print(f"{Colors.YELLOW}[*] Stopping GPS raw monitor...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.stop_wardrive_event.set()
            gps_thread.join(timeout=2)
            input("Press Enter to continue...")

    def gps_setup_menu(self) -> None:
        """GPS setup submenu for wardrive."""
        while True:
            clear_screen()
            UI.print_banner(self.device, self.attack_running, self.blackout_running,
                           self.sniffer_running, self.sae_overflow_running,
                           self.handshake_running, self.portal_running,
                           self.evil_twin_running)
            UI.print_gps_setup_menu()

            choice = input("Select option: ").strip()
            if choice == '1':
                self.run_gps_module_command("gps_set")
            elif choice == '2':
                self.run_gps_module_command("gps_set m5")
            elif choice == '3':
                self.run_gps_module_command("gps_set atgm")
            elif choice == '4':
                self.run_gps_module_command("gps_set tab5")
            elif choice == '5':
                self.run_gps_module_command("gps_set cap")
            elif choice == '6':
                self.start_gps_raw_monitor()
            elif choice == '0':
                return
            else:
                print(f"{Colors.RED}Invalid option{Colors.NC}")
                time.sleep(1)

    def start_wardrive(self) -> None:
        """Start wardrive and monitor until Enter is pressed."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running,
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        UI.print_compact_box(
            "WARDRIVE",
            [
                f"{Colors.YELLOW}Starting wardrive...{Colors.NC}",
                f"{Colors.GRAY}Wait for GPS fix and logging messages{Colors.NC}",
                f"{Colors.GRAY}Press Enter to stop{Colors.NC}",
            ],
            Colors.CYAN
        )

        self.wardrive_logged_networks = 0
        self.wardrive_last_file = ""
        self.wardrive_last_lat = ""
        self.wardrive_last_lon = ""
        self.wardrive_last_alt = ""
        self.wardrive_last_acc = ""
        self.wardrive_waiting_for_fix = False
        self.last_wardrive_line = ""
        self.wardrive_running = True
        self.stop_wardrive_event.clear()

        self.serial_mgr.send_command("start_wardrive")
        self.wardrive_thread = threading.Thread(
            target=self.serial_mgr.read_sniffer_data,
            args=(self.update_wardrive_display, self.stop_wardrive_event),
            daemon=True
        )
        self.wardrive_thread.start()

        start_time = time.time()
        try:
            self.wait_for_enter_with_status(
                lambda: (
                    f"{Colors.CYAN}{Colors.BOLD}Wardrive: {int(time.time() - start_time)}s"
                    f" | Logged: {self.wardrive_logged_networks}{Colors.NC}"
                    + (
                        f"{Colors.GREEN}{Colors.BOLD} | GPS: {self.wardrive_last_lat},{self.wardrive_last_lon}{Colors.NC}"
                        if self.wardrive_last_lat and self.wardrive_last_lon
                        else (
                            f"{Colors.YELLOW} | GPS: waiting fix{Colors.NC}"
                            if self.wardrive_waiting_for_fix else ""
                        )
                    )
                ),
                poll_interval=1.0
            )
        except KeyboardInterrupt:
            pass
        finally:
            print(f"{Colors.YELLOW}[*] Stopping wardrive...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.wardrive_running = False
            self.stop_wardrive_event.set()
            if self.wardrive_thread:
                self.wardrive_thread.join(timeout=2)
            if self.wardrive_last_file:
                print(f"{Colors.GREEN}[+] Last log file: {self.wardrive_last_file}{Colors.NC}")
            input("Press Enter to continue...")

    def wardrive_menu(self) -> None:
        """Wardrive submenu."""
        while True:
            try:
                clear_screen()
                UI.print_banner(self.device, self.attack_running, self.blackout_running,
                               self.sniffer_running, self.sae_overflow_running,
                               self.handshake_running, self.portal_running,
                               self.evil_twin_running)
                UI.print_wardrive_menu()
                if self.wardrive_running:
                    print(f"{Colors.CYAN}[!] Wardrive is RUNNING{Colors.NC}")
                choice = input("Select option: ").strip()
                if choice == '1':
                    self.start_wardrive()
                elif choice == '2':
                    self.gps_setup_menu()
                elif choice == '0':
                    return
                else:
                    print(f"{Colors.RED}Invalid option{Colors.NC}")
                    time.sleep(1)
            except (KeyboardInterrupt, EOFError):
                print(f"\n{Colors.YELLOW}[*] Returning to main menu{Colors.NC}")
                time.sleep(1)
                return

    def list_dir_entries(self, command: str, title: str, base_path: str) -> None:
        """List SD entries for a path and optionally delete one."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running,
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)

        # Clear stale logs from previous operations (e.g. stop/wardrive traces)
        # so only current command output is parsed.
        self.serial_mgr.clear_input()
        self.serial_mgr.send_command(command)
        time.sleep(0.5)
        lines = self.serial_mgr.read_until_silence(max_wait=6, idle_timeout=1.0)

        files: List[str] = []
        list_lines: List[str] = []
        reading_file_block = False
        is_html_listing = command.strip().startswith("list_sd")
        is_dir_listing = command.strip().startswith("list_dir")

        for line in lines:
            if not line or line.startswith(">"):
                continue

            lower = line.lower()
            if is_html_listing and "html files found" in lower:
                reading_file_block = True
                continue
            if is_dir_listing and lower.startswith("files in "):
                reading_file_block = True
                continue

            # For list_sd/list_dir we only want numbered file rows.
            if is_html_listing or is_dir_listing:
                if not reading_file_block:
                    continue

            m = re.match(r'^\s*(\d+)[\)\.]?\s+(.+)$', line)
            if not m:
                continue

            name = m.group(2).strip()
            if not name or name.lower().startswith("file(s)"):
                continue

            files.append(name)
            list_lines.append(f"{Colors.GREEN}{len(files):>2}){Colors.NC} {name}")

        if not list_lines:
            list_lines = [f"{Colors.YELLOW}No entries found{Colors.NC}"]

        UI.print_compact_box(title, list_lines, Colors.CYAN, width=max(40, min(get_terminal_width() - 4, 110)))
        if not files:
            input("Press Enter to continue...")
            return

        print(f"{Colors.GRAY}Type file number to delete or press Enter to go back.{Colors.NC}")
        choice = input("Delete #: ").strip()
        if not choice:
            return
        if not choice.isdigit():
            print(f"{Colors.RED}[!] Invalid number{Colors.NC}")
            time.sleep(1)
            return
        idx = int(choice) - 1
        if idx < 0 or idx >= len(files):
            print(f"{Colors.RED}[!] Number out of range{Colors.NC}")
            time.sleep(1)
            return

        target_path = f"{base_path.rstrip('/')}/{files[idx]}"
        confirm = input(f"Delete {files[idx]}? [y/N]: ").strip().lower()
        if confirm not in ['y', 'yes']:
            print(f"{Colors.YELLOW}[!] Deletion cancelled{Colors.NC}")
            time.sleep(1)
            return

        self.serial_mgr.send_command(f"file_delete {target_path}")
        resp = self.serial_mgr.read_until_silence(max_wait=4, idle_timeout=0.8)
        for line in resp:
            print(line)
        input("Press Enter to continue...")

    def sd_data_show_pass_menu(self) -> None:
        """Show compromised portal/evil credentials."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running,
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        UI.print_compact_box(
            "EVIL TWIN & PORTAL",
            [
                f"{Colors.GREEN}1){Colors.NC} show_pass portal",
                f"{Colors.GREEN}2){Colors.NC} show_pass evil",
                f"{Colors.GRAY}0){Colors.NC} Back",
            ],
            Colors.CYAN
        )
        choice = input("Select option: ").strip()
        if choice == '1':
            self.serial_mgr.send_command("show_pass portal")
        elif choice == '2':
            self.serial_mgr.send_command("show_pass evil")
        else:
            return

        lines = self.serial_mgr.read_until_silence(max_wait=6, idle_timeout=1.0)
        print()
        if not lines:
            print(f"{Colors.YELLOW}[!] No data returned{Colors.NC}")
        else:
            for line in lines:
                print(line)
        print()
        input("Press Enter to continue...")

    def sd_data_menu(self) -> None:
        """SD data submenu."""
        while True:
            try:
                clear_screen()
                UI.print_banner(self.device, self.attack_running, self.blackout_running,
                               self.sniffer_running, self.sae_overflow_running,
                               self.handshake_running, self.portal_running,
                               self.evil_twin_running)
                UI.print_sd_data_menu()
                choice = input("Select option: ").strip()
                if choice == '1':
                    self.list_dir_entries("list_sd", "SD HTMLS", "lab/htmls")
                elif choice == '2':
                    self.sd_data_show_pass_menu()
                elif choice == '3':
                    self.list_dir_entries("list_dir /sdcard/lab/wardrives", "SD WARLOGS", "lab/wardrives")
                elif choice == '4':
                    self.list_dir_entries("list_dir /sdcard/lab/handshakes", "SD HANDSHAKES", "lab/handshakes")
                elif choice == '0':
                    return
                else:
                    print(f"{Colors.RED}Invalid option{Colors.NC}")
                    time.sleep(1)
            except (KeyboardInterrupt, EOFError):
                print(f"\n{Colors.YELLOW}[*] Returning to main menu{Colors.NC}")
                time.sleep(1)
                return
    
    def stop_all_attacks(self) -> None:
        """Stop all running attacks."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        print()
        
        if not self.attack_running and not self.blackout_running and not self.sniffer_running and not self.sae_overflow_running and not self.handshake_running and not self.portal_running and not self.evil_twin_running and not self.wardrive_running and not self.beacon_spam_running and not self.arp_running and not self.mitm_running:
            print(f"{Colors.YELLOW}[!] No attacks are currently running{Colors.NC}")
            print()
            input("Press Enter to continue...")
            return
        
        print(f"{Colors.YELLOW}[*] Sending stop command to all attacks...{Colors.NC}")
        
        if self.attack_running:
            print(f"{Colors.YELLOW}    Stopping deauth attack...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.attack_running = False
        
        if self.blackout_running:
            print(f"{Colors.YELLOW}    Stopping blackout attack...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.blackout_running = False
        
        if self.sniffer_running:
            print(f"{Colors.YELLOW}    Stopping sniffer...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.sniffer_running = False
            self.stop_sniffer_event.set()
            if self.sniffer_thread:
                self.sniffer_thread.join(timeout=2)
        
        if self.sae_overflow_running:
            print(f"{Colors.YELLOW}    Stopping WPA3 SAE Overflow attack...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.sae_overflow_running = False
        
        if self.handshake_running:
            print(f"{Colors.YELLOW}    Stopping Handshake Capture attack...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.handshake_running = False
        
        if self.portal_running:
            print(f"{Colors.YELLOW}    Stopping Captive Portal...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.portal_running = False
            self.stop_portal_event.set()
            if self.portal_thread:
                self.portal_thread.join(timeout=2)
        
        if self.evil_twin_running:
            print(f"{Colors.YELLOW}    Stopping Evil Twin attack...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.evil_twin_running = False
            self.stop_evil_twin_event.set()
            if self.evil_twin_thread:
                self.evil_twin_thread.join(timeout=2)

        if self.wardrive_running:
            print(f"{Colors.YELLOW}    Stopping wardrive...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.wardrive_running = False
            self.stop_wardrive_event.set()
            if self.wardrive_thread:
                self.wardrive_thread.join(timeout=2)

        if self.beacon_spam_running:
            print(f"{Colors.YELLOW}    Stopping beacon spam...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.beacon_spam_running = False

        if self.arp_running:
            print(f"{Colors.YELLOW}    Stopping ARP attack...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.arp_running = False

        if self.mitm_running:
            print(f"{Colors.YELLOW}    Stopping MITM attack...{Colors.NC}")
            self.serial_mgr.send_command("stop")
            self.mitm_running = False
        
        print(f"{Colors.GREEN}[+] All attacks stopped{Colors.NC}")
        print()
        input("Press Enter to continue...")
    
    def portal_menu(self) -> None:
        """Portal setup menu."""
        while True:
            try:
                clear_screen()
                UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                              self.sniffer_running, self.sae_overflow_running,
                              self.handshake_running, self.portal_running,
                              self.evil_twin_running)
                UI.print_portal_menu()
                
                # Status line
                if self.portal_running:
                    print(f"{Colors.BLUE}[!] Captive Portal is RUNNING{Colors.NC}")
                    print(f"{Colors.BLUE}[+] SSID: {self.portal_ssid}{Colors.NC}")
                    print(f"{Colors.BLUE}[+] HTML: {self.selected_html_name}{Colors.NC}")
                    print(f"{Colors.BLUE}[+] Forms submitted: {self.submitted_forms}{Colors.NC}")
                    print(f"{Colors.BLUE}[+] Connected clients: {self.client_count}{Colors.NC}")
                else:
                    print(f"{Colors.GRAY}[-] Portal not running{Colors.NC}")
                
                print()
                
                choice = input("Select option: ").strip()
                
                if choice == '1':
                    self.setup_and_start_portal()
                elif choice == '2':
                    self.show_portal_captured_data()
                elif choice == '0':
                    return  # Back to attacks menu
                else:
                    print(f"{Colors.RED}Invalid option{Colors.NC}")
                    time.sleep(1)
                    
            except KeyboardInterrupt:
                print(f"\n{Colors.YELLOW}[*] Returning to attacks menu{Colors.NC}")
                time.sleep(1)
                break
            except EOFError:
                print(f"\n{Colors.YELLOW}[*] Returning to attacks menu{Colors.NC}")
                time.sleep(1)
                break
    
    def evil_twin_menu(self) -> None:
        """Evil Twin setup menu."""
        while True:
            try:
                clear_screen()
                UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                              self.sniffer_running, self.sae_overflow_running,
                              self.handshake_running, self.portal_running,
                              self.evil_twin_running)
                UI.print_evil_twin_menu()
                
                # Status line
                if self.evil_twin_running:
                    print(f"{Colors.MAGENTA}[!] Evil Twin Attack is RUNNING{Colors.NC}")
                    if self.evil_twin_ssid:
                        print(f"{Colors.MAGENTA}[+] Target SSID: {self.evil_twin_ssid}{Colors.NC}")
                    print(f"{Colors.MAGENTA}[+] HTML: {self.selected_html_name}{Colors.NC}")
                    print(f"{Colors.MAGENTA}[+] Data captured: {len(self.evil_twin_captured_data)}{Colors.NC}")
                    print(f"{Colors.MAGENTA}[+] Connected clients: {self.evil_twin_client_count}{Colors.NC}")
                else:
                    print(f"{Colors.GRAY}[-] Evil Twin not running{Colors.NC}")
                
                print()
                
                choice = input("Select option: ").strip()
                
                if choice == '1':
                    self.setup_and_start_evil_twin()
                elif choice == '2':
                    self.show_evil_twin_captured_data()
                elif choice == '0':
                    return  # Back to attacks menu
                else:
                    print(f"{Colors.RED}Invalid option{Colors.NC}")
                    time.sleep(1)
                    
            except KeyboardInterrupt:
                print(f"\n{Colors.YELLOW}[*] Returning to attacks menu{Colors.NC}")
                time.sleep(1)
                break
            except EOFError:
                print(f"\n{Colors.YELLOW}[*] Returning to attacks menu{Colors.NC}")
                time.sleep(1)
                break
    
    def scan_menu(self) -> None:
        """Scan submenu."""
        while True:
            try:
                clear_screen()
                UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                              self.sniffer_running, self.sae_overflow_running,
                              self.handshake_running, self.portal_running,
                              self.evil_twin_running)
                UI.print_scan_menu(self.network_mgr.network_count, 
                                 self.network_mgr.selected_networks)
                
                choice = input("Select option: ").strip()
                
                if choice == '1':
                    self.do_scan()
                elif choice == '2':
                    self.show_scan_results()
                elif choice == '3':
                    self.select_networks_menu()
                elif choice == '0':
                    return  # Back to main menu
                else:
                    print(f"{Colors.RED}Invalid option{Colors.NC}")
                    time.sleep(1)
                    
            except KeyboardInterrupt:
                print(f"\n{Colors.YELLOW}[*] Returning to main menu{Colors.NC}")
                time.sleep(1)
                break
            except EOFError:
                print(f"\n{Colors.YELLOW}[*] Returning to main menu{Colors.NC}")
                time.sleep(1)
                break
    
    def sniffer_menu(self) -> None:
        """Sniffer submenu."""
        while True:
            try:
                clear_screen()
                UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                              self.sniffer_running, self.sae_overflow_running,
                              self.handshake_running, self.portal_running,
                              self.evil_twin_running)
                UI.print_sniffer_menu(self.sniffer_running, self.sniffer_packets)
                
                choice = input("Select option: ").strip()
                
                if choice == '1':
                    self.start_sniffer()
                elif choice == '2':
                    self.show_sniffer_results()
                elif choice == '3':
                    self.show_sniffer_probes()
                elif choice == '0':
                    return  # Back to main menu
                else:
                    print(f"{Colors.RED}Invalid option{Colors.NC}")
                    time.sleep(1)
                    
            except KeyboardInterrupt:
                print(f"\n{Colors.YELLOW}[*] Returning to main menu{Colors.NC}")
                time.sleep(1)
                break
            except EOFError:
                print(f"\n{Colors.YELLOW}[*] Returning to main menu{Colors.NC}")
                time.sleep(1)
                break
    
    def attacks_menu(self) -> None:
        """Attacks submenu."""
        while True:
            try:
                clear_screen()
                UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                              self.sniffer_running, self.sae_overflow_running,
                              self.handshake_running, self.portal_running,
                              self.evil_twin_running)
                UI.print_attacks_menu(self.network_mgr.selected_networks, 
                                     self.attack_running, self.blackout_running, 
                                     self.sae_overflow_running, self.handshake_running,
                                     self.portal_running, self.evil_twin_running,
                                     self.beacon_spam_running, self.arp_running,
                                     self.mitm_running)
                
                choice = input("Select option: ").strip()
                
                if choice == '1':
                    self.start_deauth_attack()
                elif choice == '2':
                    self.start_blackout_attack()
                elif choice == '3':
                    self.setup_and_start_sae_overflow()
                elif choice == '4':
                    self.start_handshake_attack()
                elif choice == '5':
                    self.portal_menu()
                elif choice == '6':
                    self.evil_twin_menu()
                elif choice == '7':
                    self.beacon_spam_menu()
                elif choice == '8':
                    self.start_arp_attack()
                elif choice == '9':
                    self.start_mitm_attack()
                elif choice == '10':
                    self.stop_all_attacks()
                elif choice == '0':
                    return  # Back to main menu
                else:
                    print(f"{Colors.RED}Invalid option{Colors.NC}")
                    time.sleep(1)
                    
            except KeyboardInterrupt:
                print(f"\n{Colors.YELLOW}[*] Returning to main menu{Colors.NC}")
                time.sleep(1)
                break
            except EOFError:
                print(f"\n{Colors.YELLOW}[*] Returning to main menu{Colors.NC}")
                time.sleep(1)
                break

    def system_reboot(self) -> None:
        """Reboot the device."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        print()
        confirm = input("Reboot device now? [y/N]: ").strip().lower()
        if confirm not in ['y', 'yes']:
            print(f"{Colors.GRAY}[-] Reboot cancelled{Colors.NC}")
            time.sleep(1)
            return
        
        print(f"{Colors.YELLOW}[*] Rebooting device...{Colors.NC}")
        self.serial_mgr.send_command("reboot")
        time.sleep(1)
        print(f"{Colors.GREEN}[+] Reboot command sent{Colors.NC}")
        print()
        input("Press Enter to continue...")
    
    def system_ping(self) -> None:
        """Ping a host from the device."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        print()
        host = input("Host to ping (IP or domain): ").strip()
        if not host:
            print(f"{Colors.RED}[!] Host cannot be empty{Colors.NC}")
            time.sleep(1)
            return
        
        print(f"{Colors.YELLOW}[*] Sending ping to {host}...{Colors.NC}")
        self.serial_mgr.send_command(f"ping {host}")
        time.sleep(0.5)
        
        print(f"{Colors.CYAN}[*] Response:{Colors.NC}")
        lines = self.serial_mgr.read_response(timeout=5)
        if not lines:
            print(f"{Colors.GRAY}[-] No response received{Colors.NC}")
        else:
            for line in lines:
                print(line)
        print()
        input("Press Enter to continue...")
    
    def system_list_sd(self) -> None:
        """List SD card contents."""
        clear_screen()
        UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                       self.sniffer_running, self.sae_overflow_running,
                       self.handshake_running, self.portal_running,
                       self.evil_twin_running)
        print()
        print(f"{Colors.YELLOW}[*] Listing SD card contents...{Colors.NC}")
        self.serial_mgr.send_command("list_sd")
        time.sleep(0.5)
        
        lines = self.serial_mgr.read_response(timeout=5)
        if not lines:
            print(f"{Colors.GRAY}[-] No response received{Colors.NC}")
        else:
            for line in lines:
                print(line)
        print()
        input("Press Enter to continue...")
    
    def system_menu(self) -> None:
        """System submenu."""
        while True:
            try:
                clear_screen()
                UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                              self.sniffer_running, self.sae_overflow_running,
                              self.handshake_running, self.portal_running,
                              self.evil_twin_running)
                UI.print_system_menu()
                
                choice = input("Select option: ").strip()
                
                if choice == '1':
                    self.system_reboot()
                elif choice == '2':
                    self.system_ping()
                elif choice == '3':
                    self.system_list_sd()
                elif choice == '0':
                    return  # Back to main menu
                else:
                    print(f"{Colors.RED}Invalid option{Colors.NC}")
                    time.sleep(1)
                    
            except KeyboardInterrupt:
                print(f"\n{Colors.YELLOW}[*] Returning to main menu{Colors.NC}")
                time.sleep(1)
                break
            except EOFError:
                print(f"\n{Colors.YELLOW}[*] Returning to main menu{Colors.NC}")
                time.sleep(1)
                break
    
    def main_menu(self) -> None:
        """Main menu loop."""
        while True:
            try:
                clear_screen()
                UI.print_banner(self.device, self.attack_running, self.blackout_running, 
                              self.sniffer_running, self.sae_overflow_running,
                              self.handshake_running, self.portal_running,
                              self.evil_twin_running)
                UI.print_main_menu()
                
                # Status display
                if self.network_mgr.network_count > 0:
                    print(f"{Colors.GREEN}[+] Networks found: {self.network_mgr.network_count}{Colors.NC}")
                else:
                    print(f"{Colors.GRAY}[-] No networks scanned{Colors.NC}")
                
                if self.network_mgr.selected_networks:
                    print(f"{Colors.GREEN}[+] Selected: {self.network_mgr.selected_networks}{Colors.NC}")
                
                if self.attack_running:
                    print(f"{Colors.RED}[!] Deauth Attack is RUNNING{Colors.NC}")
                if self.blackout_running:
                    print(f"{Colors.RED}[!] Blackout Attack is RUNNING{Colors.NC}")
                if self.sniffer_running:
                    print(f"{Colors.CYAN}[📡] Sniffer is RUNNING{Colors.NC}")
                    print(f"{Colors.CYAN}[+] Packets captured: {self.sniffer_packets}{Colors.NC}")
                if self.sae_overflow_running:
                    print(f"{Colors.MAGENTA}[!] WPA3 SAE Overflow is RUNNING{Colors.NC}")
                if self.handshake_running:
                    print(f"{Colors.YELLOW}[!] Handshake Capture is RUNNING{Colors.NC}")
                if self.portal_running:
                    print(f"{Colors.BLUE}[!] Captive Portal is RUNNING{Colors.NC}")
                    print(f"{Colors.BLUE}[+] SSID: {self.portal_ssid}{Colors.NC}")
                    print(f"{Colors.BLUE}[+] Forms: {self.submitted_forms}{Colors.NC}")
                if self.evil_twin_running:
                    print(f"{Colors.MAGENTA}[!] Evil Twin Attack is RUNNING{Colors.NC}")
                    if self.evil_twin_ssid:
                        print(f"{Colors.MAGENTA}[+] Target: {self.evil_twin_ssid}{Colors.NC}")
                    print(f"{Colors.MAGENTA}[+] Captured: {len(self.evil_twin_captured_data)}{Colors.NC}")
                if self.wardrive_running:
                    print(f"{Colors.CYAN}[!] Wardrive is RUNNING{Colors.NC}")
                    if self.wardrive_last_file:
                        print(f"{Colors.CYAN}[+] Last log: {self.wardrive_last_file}{Colors.NC}")
                if self.beacon_spam_running:
                    print(f"{Colors.YELLOW}[!] Beacon spam is RUNNING{Colors.NC}")
                if self.arp_running:
                    print(f"{Colors.YELLOW}[!] ARP attack is RUNNING{Colors.NC}")
                if self.mitm_running:
                    print(f"{Colors.CYAN}[!] MITM attack is RUNNING{Colors.NC}")
                if not self.attack_running and not self.blackout_running and not self.sniffer_running and not self.sae_overflow_running and not self.handshake_running and not self.portal_running and not self.evil_twin_running and not self.wardrive_running and not self.beacon_spam_running and not self.arp_running and not self.mitm_running:
                    print(f"{Colors.GRAY}[-] No attacks running{Colors.NC}")
                
                print()
                
                choice = input("Select option: ").strip()
                
                if choice == '1':
                    self.scan_menu()
                elif choice == '2':
                    self.sniffer_menu()
                elif choice == '3':
                    self.attacks_menu()
                elif choice == '4':
                    self.wardrive_menu()
                elif choice == '5':
                    self.sd_data_menu()
                elif choice in ['0', 'q', 'Q']:
                    if self.attack_running or self.blackout_running or self.sniffer_running or self.sae_overflow_running or self.handshake_running or self.portal_running or self.evil_twin_running or self.wardrive_running or self.beacon_spam_running or self.arp_running or self.mitm_running:
                        print()
                        try:
                            stop_confirm = input("Actions are running. Stop before exit? [Y/n]: ").strip().lower()
                        except EOFError:
                            stop_confirm = 'y'
                        
                        if stop_confirm not in ['n', 'no']:
                            self.serial_mgr.send_command("stop")
                            if self.sniffer_running:
                                self.stop_sniffer_event.set()
                                if self.sniffer_thread:
                                    self.sniffer_thread.join(timeout=2)
                            if self.portal_running:
                                self.stop_portal_event.set()
                                if self.portal_thread:
                                    self.portal_thread.join(timeout=2)
                            if self.evil_twin_running:
                                self.stop_evil_twin_event.set()
                                if self.evil_twin_thread:
                                    self.evil_twin_thread.join(timeout=2)
                            if self.wardrive_running:
                                self.stop_wardrive_event.set()
                                if self.wardrive_thread:
                                    self.wardrive_thread.join(timeout=2)
                            print(f"{Colors.GREEN}[+] All activities stopped{Colors.NC}")
                            time.sleep(1)
                    return
                else:
                    print(f"{Colors.RED}Invalid option{Colors.NC}")
                    time.sleep(1)
                    
            except KeyboardInterrupt:
                print(f"\n{Colors.YELLOW}[*] Interrupted{Colors.NC}")
                if self.attack_running or self.blackout_running or self.sniffer_running or self.sae_overflow_running or self.handshake_running or self.portal_running or self.evil_twin_running or self.wardrive_running or self.beacon_spam_running or self.arp_running or self.mitm_running:
                    self.serial_mgr.send_command("stop")
                    if self.sniffer_running:
                        self.stop_sniffer_event.set()
                    if self.portal_running:
                        self.stop_portal_event.set()
                    if self.evil_twin_running:
                        self.stop_evil_twin_event.set()
                    if self.wardrive_running:
                        self.stop_wardrive_event.set()
                break
            except EOFError:
                print(f"\n{Colors.YELLOW}[*] Exiting{Colors.NC}")
                if self.attack_running or self.blackout_running or self.sniffer_running or self.sae_overflow_running or self.handshake_running or self.portal_running or self.evil_twin_running or self.wardrive_running or self.beacon_spam_running or self.arp_running or self.mitm_running:
                    self.serial_mgr.send_command("stop")
                    if self.sniffer_running:
                        self.stop_sniffer_event.set()
                    if self.portal_running:
                        self.stop_portal_event.set()
                    if self.evil_twin_running:
                        self.stop_evil_twin_event.set()
                    if self.wardrive_running:
                        self.stop_wardrive_event.set()
                break
    
    def run(self) -> None:
        """Run the application."""
        print(f"{Colors.YELLOW}[*] JanOS Controller starting...{Colors.NC}")
        print(f"{Colors.GREEN}[+] Connected to {self.device}{Colors.NC}")
        time.sleep(1)
        
        try:
            self.main_menu()
        finally:
            self.cleanup()
    
    def cleanup(self) -> None:
        """Cleanup resources."""
        print()
        print(f"{Colors.YELLOW}[*] Cleaning up...{Colors.NC}")
        if self.attack_running or self.blackout_running or self.sniffer_running or self.sae_overflow_running or self.handshake_running or self.portal_running or self.evil_twin_running or self.wardrive_running or self.beacon_spam_running or self.arp_running or self.mitm_running:
            self.serial_mgr.send_command("stop")
            if self.sniffer_running:
                self.stop_sniffer_event.set()
                if self.sniffer_thread:
                    self.sniffer_thread.join(timeout=2)
            if self.portal_running:
                self.stop_portal_event.set()
                if self.portal_thread:
                    self.portal_thread.join(timeout=2)
            if self.evil_twin_running:
                self.stop_evil_twin_event.set()
                if self.evil_twin_thread:
                    self.evil_twin_thread.join(timeout=2)
            if self.wardrive_running:
                self.stop_wardrive_event.set()
                if self.wardrive_thread:
                    self.wardrive_thread.join(timeout=2)
        self.serial_mgr.close()
        print(f"{Colors.GREEN}Goodbye!{Colors.NC}")

# ============================================================================
# Main Entry Point
# ============================================================================
def main():
    device = None
    if len(sys.argv) > 1:
        if sys.argv[1] in ['-h', '--help']:
            print_usage()
            sys.exit(0)
        device = sys.argv[1]
    
    if not device:
        device = select_device_interactive()
    
    # Create and run application
    app = JanOS(device)
    
    # Setup signal handlers
    import signal
    def signal_handler(sig, frame):
        print(f"\n{Colors.YELLOW}[*] Received interrupt signal{Colors.NC}")
        if app.attack_running or app.blackout_running or app.sniffer_running or app.sae_overflow_running or app.handshake_running or app.portal_running or app.evil_twin_running or app.wardrive_running or app.beacon_spam_running or app.arp_running or app.mitm_running:
            app.serial_mgr.send_command("stop")
            if app.sniffer_running:
                app.stop_sniffer_event.set()
            if app.portal_running:
                app.stop_portal_event.set()
            if app.evil_twin_running:
                app.stop_evil_twin_event.set()
            if app.wardrive_running:
                app.stop_wardrive_event.set()
        app.serial_mgr.close()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    app.run()

if __name__ == "__main__":
    main()
