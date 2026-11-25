"""
rt.core.lan
Accesso dalla stessa rete locale (Wi-Fi di casa o hotspot del telefono), senza Tailscale.
Di default RT ascolta solo su 127.0.0.1; con l'opzione accesa ascolta su tutte le interfacce
(0.0.0.0) e l'altro dispositivo lo apre con http://nome-mac.local:porta o con l'IP del Mac.
Il traffico non è cifrato: va bene in casa o sull'hotspot, non sulle reti pubbliche.
Per non lasciarlo aperto per dimenticanza vale solo finché RT resta acceso e sulla stessa rete:
un avvio da zero (dopo "Esci da RT" o un riavvio del computer) lo spegne, e lo spegne anche il
passaggio a un'altra rete (es. da casa all'università). L'opzione è un file nella cartella dati
con l'impronta della rete su cui è stata accesa, letto all'avvio del server.
"""
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from typing import Callable, List, Optional

from rt.core import paths

FLAG_FILE = "lan-access"
LOCAL_HOST = "127.0.0.1"
ALL_HOSTS = "0.0.0.0"
KEEP_ENV = "RT_LAN_KEEP"  # messo da restart_process: il riavvio per accendere l'opzione non la spegne
WATCH_SECONDS = 15


def _flag_path() -> str:
    return os.path.join(paths.default_data_dir(), FLAG_FILE)


def _read_flag() -> Optional[dict]:
    try:
        with open(_flag_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def lan_enabled() -> bool:
    return _read_flag() is not None


def enabled_network() -> Optional[str]:
    return (_read_flag() or {}).get("network")


def set_lan_enabled(enabled: bool) -> None:
    path = _flag_path()
    if enabled:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"network": network_id()}, f)
    else:
        try:
            os.remove(path)
        except FileNotFoundError:
            pass


def bind_host() -> str:
    """Indirizzo su cui ascoltare: tutte le interfacce con l'accesso in rete locale, se no solo questo
    computer. Un avvio da zero o una rete diversa da quella su cui è stata accesa spengono l'opzione."""
    keep = os.environ.pop(KEEP_ENV, None) == "1"
    if not lan_enabled():
        return LOCAL_HOST
    if not keep or not same_network(network_id(), enabled_network()):
        set_lan_enabled(False)
        return LOCAL_HOST
    return ALL_HOSTS


def _run(*args: str) -> str:
    try:
        return subprocess.run(list(args), capture_output=True, text=True, timeout=2, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _gateway() -> Optional[str]:
    if sys.platform == "darwin":
        found = re.search(r"gateway:\s*(\S+)", _run("route", "-n", "get", "default"))
    elif sys.platform.startswith("linux"):
        found = re.search(r"default via (\S+)", _run("ip", "route", "show", "default"))
    else:
        found = None
    return found.group(1) if found else None


def _mac_of(ip: str) -> Optional[str]:
    if sys.platform == "win32":
        return None
    found = re.search(r"(([0-9a-f]{1,2}[:-]){5}[0-9a-f]{1,2})", _run("arp", "-n", ip), re.I)
    return found.group(1).lower() if found else None


def network_id() -> Optional[str]:
    """Impronta della rete: sottorete del Mac più il router (MAC, se no IP). Molte reti usano
    192.168.1.x: il MAC del router distingue casa da università. None senza rete locale."""
    ips = _lan_ips()
    if not ips:
        return None
    subnet = str(ipaddress.ip_network(f"{ips[0]}/24", strict=False))
    gateway = _gateway() or ""
    return f"{subnet}|{gateway}|{(_mac_of(gateway) if gateway else None) or ''}"


def same_network(current: Optional[str], expected: Optional[str]) -> bool:
    """Stessa sottorete e stesso router; il MAC conta solo se noto in entrambe (arp a volte non lo ha)."""
    if not current or not expected:
        return False
    a, b = current.split("|"), expected.split("|")
    if len(a) != 3 or len(b) != 3 or a[:2] != b[:2]:
        return False
    return not (a[2] and b[2]) or a[2] == b[2]


def watch_network(on_change: Callable[[], None], stop: Optional[threading.Event] = None,
                  interval: float = WATCH_SECONDS) -> threading.Thread:
    """Con l'accesso acceso, se il computer cambia rete (due controlli di fila) spegne l'opzione e
    chiama on_change (il server si riavvia solo su 127.0.0.1)."""
    stop = stop or threading.Event()

    def loop() -> None:
        misses = 0
        while not stop.wait(interval):
            misses = 0 if same_network(network_id(), enabled_network()) else misses + 1
            if misses >= 2:
                set_lan_enabled(False)
                on_change()
                return
    thread = threading.Thread(target=loop, name="rt-lan-watch", daemon=True)
    thread.start()
    return thread


def _local_hostname() -> Optional[str]:
    """Nome Bonjour del Mac (Impostazioni > Generali > Condivisione), senza '.local'."""
    name = _run("scutil", "--get", "LocalHostName").strip() if sys.platform == "darwin" else ""
    if not name:
        name = socket.gethostname().split(".")[0]
    return name or None


def _is_lan_ip(value: str) -> bool:
    """IP privato raggiungibile in rete locale: niente loopback, link-local né 100.64/10 (Tailscale)."""
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if ip.version != 4 or ip.is_loopback or ip.is_link_local:
        return False
    return ip.is_private and ip not in ipaddress.ip_network("100.64.0.0/10")


def _lan_ips() -> List[str]:
    found: List[str] = []
    # l'interfaccia della rotta predefinita (nessun pacchetto parte: UDP senza invio)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            found.append(s.getsockname()[0])
    except OSError:
        pass
    # Solo senza rotta: su macOS getaddrinfo del nome host può aspettare mDNS per più di 10 s.
    if not found:
        try:
            found += [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
        except OSError:
            pass
    out: List[str] = []
    for ip in found:
        if _is_lan_ip(ip) and ip not in out:
            out.append(ip)
    return out


_ADDRESS_CACHE: dict = {}
_ADDRESS_TTL = 30.0


def lan_addresses(port: int) -> List[str]:
    """Indirizzi con cui un altro dispositivo della stessa rete apre RT: prima il nome .local, poi gli IP.
    Tenuti 30 s: su macOS getaddrinfo del nome host può impiegare secondi a ogni chiamata."""
    cached = _ADDRESS_CACHE.get(port)
    if cached and time.monotonic() - cached[0] < _ADDRESS_TTL:
        return list(cached[1])
    out = _lan_addresses(port)
    _ADDRESS_CACHE[port] = (time.monotonic(), out)
    return list(out)


def _lan_addresses(port: int) -> List[str]:
    out = []
    name = _local_hostname()
    if name and name.lower() != "localhost":
        out.append(f"http://{name}.local:{port}")
    out += [f"http://{ip}:{port}" for ip in _lan_ips()]
    return out
