import os
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("CURRENCY_API_KEY")


def _get_base_params() -> dict:
    """
    Базовые параметры запроса к api.exchangerate.host.
    Все запросы идут только на endpoint /convert.
    """
    if not API_KEY:
        raise RuntimeError("CURRENCY_API_KEY не найден в .env")
    return {"access_key": API_KEY}


def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict:
    """
    Базовый вызов /convert.
    Возвращает полный JSON-ответ API.
    """
    url = "http://api.exchangerate.host/convert"
    params = {
        **_get_base_params(),
        "from": from_currency,
        "to": to_currency,
        "amount": amount,
    }

    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    return data


def get_rate(from_currency: str, to_currency: str) -> Optional[float]:
    """
    Получить курс (rate) через /convert для amount=1.
    Возвращает None, если запрос неуспешен.
    """
    try:
        data = convert_currency(1, from_currency, to_currency)
    except Exception:
        return None

    if not data.get("success"):
        return None

    info = data.get("info") or {}
    # В разных тарифах APILayer поле может называться по‑разному.
    rate = info.get("rate")
    if rate is None:
        rate = info.get("quote")
    if rate is None and "result" in data:
        # При amount=1 result фактически равен курсу.
        rate = data.get("result")

    return float(rate) if rate is not None else None


if __name__ == "__main__":
    example_rate = get_rate("USD", "EUR")
    print("1 USD -> EUR =", example_rate)