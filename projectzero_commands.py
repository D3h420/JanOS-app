"""Declarative command catalog for current projectZero/JanOS firmware.

The main application has tailored workflows for the common commands.  This
catalog exposes the remaining firmware surface without duplicating dozens of
near-identical menu handlers.  ``arguments`` is shown to the operator and the
entered suffix is passed to JanOS verbatim.
"""

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class CommandSpec:
    command: str
    label: str
    arguments: str = ""
    stream: bool = False
    confirm: bool = False


COMMAND_GROUPS: Dict[str, Tuple[CommandSpec, ...]] = {
    "Wi-Fi tools": (
        CommandSpec("wifi_analyzer", "WFA/1 Wi-Fi analyzer", "capabilities|scan|status|list|inspect ..."),
        CommandSpec("wifi_country", "Wi-Fi country/regulatory domain", "[show|set <CC>]"),
        CommandSpec("sta_mac", "Persistent STA MAC policy", "status|random|set <MAC>|factory"),
        CommandSpec("radio_protect", "Shared-radio protection", "status|on|off"),
        CommandSpec("show_sniffer_clients", "Structured AP/client snapshot"),
        CommandSpec("start_deauth_station", "Deauth one station", "<BSSID> <station-MAC>", stream=True),
        CommandSpec("select_stations", "Select station indices", "<index> [index ...]"),
        CommandSpec("unselect_stations", "Clear station selection"),
        CommandSpec("sniffer_debug", "Sniffer debug logging", "<0|1>"),
        CommandSpec("start_nmap", "Network host/port scan", "[target/options]", stream=True),
        CommandSpec("list_hosts_vendor", "Connected hosts with vendor"),
        CommandSpec("wifi_disconnect", "Disconnect Wi-Fi STA"),
        CommandSpec("wifi_connect", "Advanced Wi-Fi STA connection", "<SSID> <password> [ota] [IP netmask gateway [DNS1] [DNS2]]"),
    ),
    "WPS and Bluetooth": (
        CommandSpec("wps", "WPS scanner/workflow", "capabilities|scan|list|select|start|status|stop ...", stream=True),
        CommandSpec("jwps", "Machine-readable WPS workflow", "capabilities|scan|list|select|start|status|stop ...", stream=True),
        CommandSpec("start_blespam", "Apple/Samsung BLE spam", "[20|50|100|200|500]", stream=True),
    ),
    "Portals and gateways": (
        CommandSpec("capture_gateway", "Capture Gateway", "start|status|clients|stats|stop [options]", stream=True),
        CommandSpec("start_pcap", "PCAP capture", "radio|net|gateway", stream=True),
        CommandSpec("start_rogue_gitm", "Rogue GITM", "[options]", stream=True),
        CommandSpec("start_rogueap", "WPA2 Rogue AP", '"SSID" "password"', stream=True),
        CommandSpec("start_karma", "Karma attack from probe", "<probe-index>", stream=True),
        CommandSpec("start_admin_portal", "SD administration portal", "[SSID] [password]", stream=True),
        CommandSpec("start_darksword", "Darksword portal", "[arguments]", stream=True),
        CommandSpec("start_beacon_spam", "Beacon spam from arguments", '"SSID1" ["SSID2" ...]', stream=True),
        CommandSpec("set_html", "Upload/select portal HTML", "[arguments]"),
    ),
    "Zigbee / 802.15.4": (
        CommandSpec("start_zig_recon", "Start Zigbee/Thread/Matter recon", "[channel/options]", stream=True),
        CommandSpec("zig_recon_status", "Recon status"),
        CommandSpec("zig_recon_list", "Discovered PAN list"),
        CommandSpec("zig_recon_nodes", "Discovered node list", "[PAN/index]"),
        CommandSpec("zig_recon_clear", "Clear recon results", confirm=True),
    ),
    "Wardrive services": (
        CommandSpec("wigle_key", "WiGLE API key", "status|set <name> <token>|clear"),
        CommandSpec("wigle_upload", "Upload Wardrive to WiGLE", "[all|file]", stream=True),
        CommandSpec("wdgwars_key", "WDGWars API key", "status|set <key>|clear"),
        CommandSpec("wdgwars_upload", "Upload Wardrive to WDGWars", "[all|file]", stream=True),
        CommandSpec("upload_state", "Wardrive upload state", "[arguments]"),
        CommandSpec("wardrive_files", "Wardrive file statistics", "[arguments]"),
        CommandSpec("wardrive_cleanup", "Wardrive cleanup", "[dry-run/options]", confirm=True),
        CommandSpec("wardrive_fix", "Repair Wardrive log", "<file> [options]"),
        CommandSpec("wardrive_fix_kml", "Repair Wardrive KML", "<file> [options]"),
        CommandSpec("home_list", "List protected home networks"),
        CommandSpec("home_add", "Add protected home network", "<BSSID> [label]"),
        CommandSpec("home_remove", "Remove protected home network", "<index|BSSID>"),
    ),
    "Handshake and cracking": (
        CommandSpec("save_handshake", "Save current handshake"),
        CommandSpec("wpasec_key", "WPA-SEC API key", "status|set <key>|clear"),
        CommandSpec("wpasec_upload", "Upload handshake to WPA-SEC", "[file|all]", stream=True),
        CommandSpec("artifact_inventory", "Capture artifact inventory", "capabilities|list|inspect|cancel ..."),
        CommandSpec("crack_worker", "Distributed crack worker", "capabilities|probe|receive|reset|diag|start|status|cancel ...", stream=True),
    ),
    "OTA and firmware": (
        CommandSpec("ota_check", "Check/apply OTA update", "[latest|tag]", stream=True, confirm=True),
        CommandSpec("ota_list", "List available releases"),
        CommandSpec("ota_channel", "OTA channel", "[main|dev]"),
        CommandSpec("ota_info", "OTA partition information"),
        CommandSpec("ota_boot", "Boot selected OTA partition", "<ota_0|ota_1>", confirm=True),
        CommandSpec("download", "Enter ROM download mode", confirm=True),
    ),
    "Hardware and diagnostics": (
        CommandSpec("boot_button", "Boot-button action", "[read|set ...]"),
        CommandSpec("init_nrf24", "Initialize nRF24L01+"),
        CommandSpec("start_jammer24", "nRF24 2.4 GHz jammer", "[ble|bt|wifi|drone|all]", stream=True),
        CommandSpec("sd_benchmark", "SD performance benchmark", "[arguments]", stream=True),
        CommandSpec("selftest", "Board self-test", "[arguments]", stream=True),
        CommandSpec("test_radio_channel", "Radio channel diagnostic", "[arguments]"),
        CommandSpec("test_radio_channels", "Radio channel suite", "[arguments]"),
        CommandSpec("secret", "Firmware secret/diagnostic", "[arguments]"),
        CommandSpec("save_pass", "Persist captured credentials", "[arguments]"),
    ),
}


# Commands handled by the binary-aware file manager in JanOS_app.py.
FILE_COMMANDS = ("fs", "send_file", "uart_baud", "uart_baud_confirm", "uart_baud_status")

