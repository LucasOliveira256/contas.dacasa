"""Data e saudação usando o fuso horário local da família (Cuiabá)."""
from datetime import datetime
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Cuiaba")


def local_now() -> datetime:
    return datetime.now(LOCAL_TZ)


def local_today():
    return local_now().date()


def greeting_for_hour(hour: int) -> str:
    """Faixas convencionais: manhã 05–11h, tarde 12–17h, noite no restante."""
    if 5 <= hour < 12:
        return "Bom dia"
    if 12 <= hour < 18:
        return "Boa tarde"
    return "Boa noite"
