"""تنظیمات MVP مستقل؛ فقط کتابخانه استاندارد پایتون."""
from dataclasses import dataclass
import os
from pathlib import Path


def load_env_file(path: str = ".env") -> None:
    """بارگذاری ساده .env بدون وابستگی؛ متغیرهای سیستم اولویت دارند."""
    file = Path(path)
    if not file.exists():
        return
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _float(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
        if value < 0 or value != value or value == float("inf"):
            raise ValueError
        return value
    except ValueError as exc:
        raise ValueError(f"مقدار {name} باید عدد نامنفی باشد.") from exc


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    wallex_fee_pct: float = 0.25
    nobitex_fee_pct: float = 0.25
    slippage_pct_per_side: float = 0.20
    transfer_cost_pct: float = 0.30
    transfer_cost_confirmed: bool = False
    fees_confirmed: bool = False
    capital_toman: float = 2_000_000
    min_net_profit_toman: float = 1_000
    max_book_age_seconds: float = 30
    request_timeout_seconds: float = 15
    db_path: str = "arbitrage_history.sqlite3"
    nobitex_irt_price_divisor: float = 10

    @classmethod
    def from_env(cls):
        load_env_file()
        return cls(
            wallex_fee_pct=_float("WALLEX_FEE_PCT", .25),
            nobitex_fee_pct=_float("NOBITEX_FEE_PCT", .25),
            slippage_pct_per_side=_float("SLIPPAGE_PCT_PER_SIDE", .20),
            transfer_cost_pct=_float("TRANSFER_COST_PCT", .30),
            transfer_cost_confirmed=_bool("TRANSFER_COST_CONFIRMED"),
            fees_confirmed=_bool("FEES_CONFIRMED"),
            capital_toman=_float("CAPITAL_TOMAN", 2_000_000),
            min_net_profit_toman=_float("MIN_NET_PROFIT_TOMAN", 1_000),
            max_book_age_seconds=_float("MAX_BOOK_AGE_SECONDS", 30),
            request_timeout_seconds=_float("REQUEST_TIMEOUT_SECONDS", 15),
            db_path=os.getenv("DB_PATH", "arbitrage_history.sqlite3"),
            nobitex_irt_price_divisor=_float("NOBITEX_IRT_PRICE_DIVISOR", 10),
        )
