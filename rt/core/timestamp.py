"""
rt.core.timestamp
Modulo per la gestione puramente deterministica dei timestamp e degli intervalli audio.
Normalizza internamente tutti i riferimenti temporali in secondi (float).
"""

from typing import Tuple
import re

INTERVAL_PATTERN = re.compile(r"^((?:\d{1,2}:)?\d{1,2}:\d{2})\s*[-–—]\s*((?:\d{1,2}:)?\d{1,2}:\d{2})$")


def parse_timestamp(ts_str: str) -> float:
    """
    Parsa una stringa timestamp (es. '00:14', '14', '01:14:59', '1:02:10.5')
    e restituisce il tempo equivalente in secondi come float.
    
    Lancia ValueError se il formato è non valido.
    """
    if not ts_str or not isinstance(ts_str, str):
        raise ValueError(f"Timestamp non valido (vuoto o non stringa): {ts_str!r}")
    
    clean_ts = ts_str.strip()
    # Supporta anche formato da segmenti raw tipo '*00:14*'
    clean_ts = clean_ts.strip("*").strip()
    
    parts = clean_ts.split(":")
    if len(parts) == 1:
        # Solo secondi (es. '45' o '45.2')
        try:
            sec = float(parts[0])
            if sec < 0:
                raise ValueError
            return sec
        except ValueError:
            raise ValueError(f"Formato timestamp non valido: '{ts_str}'")
    elif len(parts) == 2:
        # MM:SS
        try:
            m = int(parts[0])
            s = float(parts[1])
            if m < 0 or s < 0 or s >= 60:
                raise ValueError
            return float(m * 60 + s)
        except ValueError:
            raise ValueError(f"Formato timestamp MM:SS non valido: '{ts_str}'")
    elif len(parts) == 3:
        # H:MM:SS o HH:MM:SS
        try:
            h = int(parts[0])
            m = int(parts[1])
            s = float(parts[2])
            if h < 0 or m < 0 or m >= 60 or s < 0 or s >= 60:
                raise ValueError
            return float(h * 3600 + m * 60 + s)
        except ValueError:
            raise ValueError(f"Formato timestamp H:MM:SS non valido: '{ts_str}'")
    else:
        raise ValueError(f"Formato timestamp con troppi segmenti: '{ts_str}'")


def format_timestamp(seconds: float, include_hours_always: bool = False) -> str:
    """
    Formatta un valore in secondi in formato leggibile:
    - MM:SS se seconds < 3600 e include_hours_always è False
    - H:MM:SS o HH:MM:SS se seconds >= 3600
    Utilizza troncamento all'intero (int) per allineamento fedele ai player audio/ASR.
    """
    if seconds < 0:
        raise ValueError(f"I secondi non possono essere negativi: {seconds}")
    
    total_seconds = int(seconds)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    
    if hours > 0 or include_hours_always:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}" if include_hours_always else f"{hours}:{minutes:02d}:{secs:02d}"
    else:
        return f"{minutes:02d}:{secs:02d}"


def parse_interval(interval_str: str) -> Tuple[float, float]:
    """
    Parsa un intervallo come '00:02-00:12' o '01:14:00 - 01:15:30'.
    Restituisce (start_seconds, end_seconds).
    Lancia ValueError se il formato non è valido o se start >= end.
    """
    if not interval_str or not isinstance(interval_str, str):
        raise ValueError(f"Intervallo non valido: {interval_str!r}")
    
    clean_str = interval_str.strip().strip("*").strip()
    match = INTERVAL_PATTERN.match(clean_str)
    if not match:
        raise ValueError(f"Formato intervallo non riconosciuto: '{interval_str}'")
    
    start_sec = parse_timestamp(match.group(1))
    end_sec = parse_timestamp(match.group(2))
    
    validate_interval(start_sec, end_sec)
    return start_sec, end_sec


def validate_interval(start_seconds: float, end_seconds: float) -> None:
    """
    Valida un intervallo temporale:
    - start >= 0
    - end > start
    """
    if start_seconds < 0:
        raise ValueError(f"start_seconds deve essere >= 0, ricevuto: {start_seconds}")
    if end_seconds <= start_seconds:
        raise ValueError(f"end_seconds ({end_seconds}) deve essere strettamente maggiore di start_seconds ({start_seconds})")
