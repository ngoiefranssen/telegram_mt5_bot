"""
MT5 relay server (Option 2)
---------------------------
Receives trade instructions from the Render bot and executes orders on MT5.
Run this on a VPS where MetaTrader 5 terminal is installed and logged in.
"""

import logging
import os
from typing import Any, Dict, List, Tuple

from aiohttp import web
from dotenv import load_dotenv

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - runtime dependency on VPS
    mt5 = None


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("mt5_relay")


CONFIG = {
    "relay_host": os.getenv("RELAY_HOST", "0.0.0.0"),
    "relay_port": int(os.getenv("RELAY_PORT", "9000")),
    "relay_api_key": os.getenv("MT5_RELAY_API_KEY", "").strip(),
    "mt5_login": int(os.getenv("MT5_LOGIN", "0")),
    "mt5_password": os.getenv("MT5_PASSWORD", "").strip(),
    "mt5_server": os.getenv("MT5_SERVER", "").strip(),
    "mt5_deviation": int(os.getenv("MT5_DEVIATION", "20")),
    "magic_number": int(os.getenv("MT5_MAGIC_NUMBER", "234000")),
}


def validate_config() -> bool:
    if mt5 is None:
        logger.error("MetaTrader5 package is not installed")
        return False

    required = {
        "MT5_RELAY_API_KEY": CONFIG["relay_api_key"],
        "MT5_LOGIN": CONFIG["mt5_login"],
        "MT5_PASSWORD": CONFIG["mt5_password"],
        "MT5_SERVER": CONFIG["mt5_server"],
    }
    missing = [key for key, value in required.items() if not value or value == 0]
    if missing:
        logger.error("Missing relay configuration: %s", ", ".join(missing))
        return False
    return True


def ensure_mt5_connection() -> bool:
    if mt5 is None:
        return False

    account_info = mt5.account_info()
    if account_info is not None:
        return True

    if not mt5.initialize():
        logger.error("MT5 initialize failed: %s", mt5.last_error())
        return False

    if not mt5.login(
        CONFIG["mt5_login"],
        password=CONFIG["mt5_password"],
        server=CONFIG["mt5_server"],
    ):
        logger.error("MT5 login failed: %s", mt5.last_error())
        return False

    logger.info("MT5 connected: login=%s server=%s", CONFIG["mt5_login"], CONFIG["mt5_server"])
    return True


def symbol_ready(symbol: str) -> bool:
    info = mt5.symbol_info(symbol)
    if info is None:
        logger.error("Unknown MT5 symbol: %s", symbol)
        return False
    if info.visible:
        return True
    return bool(mt5.symbol_select(symbol, True))


def build_order_request(
    symbol: str,
    direction: str,
    volume: float,
    tp: float,
    sl: float,
    trade_index: int,
    source: str,
) -> Tuple[Dict[str, Any], str]:
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(f"No tick for symbol {symbol}")

    side = direction.upper()
    if side == "BUY":
        order_type = mt5.ORDER_TYPE_BUY
        price = float(tick.ask)
    elif side == "SELL":
        order_type = mt5.ORDER_TYPE_SELL
        price = float(tick.bid)
    else:
        raise ValueError(f"Invalid direction: {direction}")

    symbol_info = mt5.symbol_info(symbol)
    filling_mode = symbol_info.filling_mode if symbol_info else mt5.ORDER_FILLING_IOC
    comment = f"{source}-#{trade_index}"
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(volume),
        "type": order_type,
        "price": price,
        "sl": float(sl),
        "tp": float(tp),
        "deviation": CONFIG["mt5_deviation"],
        "magic": CONFIG["magic_number"],
        "comment": comment,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_mode,
    }
    return request, comment


def _authorized(request: web.Request) -> bool:
    expected = CONFIG["relay_api_key"]
    if not expected:
        return False
    auth_header = request.headers.get("Authorization", "").strip()
    x_key = request.headers.get("X-Relay-Key", "").strip()
    return auth_header == f"Bearer {expected}" or x_key == expected


async def health(request: web.Request) -> web.Response:
    connected = ensure_mt5_connection()
    account = mt5.account_info() if connected else None
    return web.json_response(
        {
            "ok": True,
            "mt5_connected": connected,
            "login": account.login if account else None,
            "server": account.server if account else None,
        }
    )


async def trade(request: web.Request) -> web.Response:
    if not _authorized(request):
        return web.json_response({"success": False, "reason": "unauthorized"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"success": False, "reason": "invalid_json"}, status=400)

    symbol = str(body.get("symbol", "")).strip()
    direction = str(body.get("direction", "")).strip().upper()
    source = str(body.get("source", "telegram")).strip() or "telegram"
    try:
        volume = float(body.get("volume", 0.0))
        tp = float(body.get("tp"))
        sl = float(body.get("sl"))
        trades_count = int(body.get("trades_count", 1))
    except (TypeError, ValueError):
        return web.json_response({"success": False, "reason": "invalid_payload"}, status=400)

    if not symbol or direction not in {"BUY", "SELL"}:
        return web.json_response({"success": False, "reason": "invalid_symbol_or_direction"}, status=400)
    if trades_count < 1:
        return web.json_response({"success": False, "reason": "invalid_trades_count"}, status=400)
    if volume <= 0:
        return web.json_response({"success": False, "reason": "invalid_volume"}, status=400)

    if not ensure_mt5_connection():
        return web.json_response({"success": False, "reason": "mt5_not_connected"}, status=503)
    if not symbol_ready(symbol):
        return web.json_response({"success": False, "reason": "symbol_unavailable"}, status=400)

    orders: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []

    for trade_index in range(1, trades_count + 1):
        try:
            order_request, comment = build_order_request(
                symbol=symbol,
                direction=direction,
                volume=volume,
                tp=tp,
                sl=sl,
                trade_index=trade_index,
                source=source,
            )
            result = mt5.order_send(order_request)
            if result is None:
                failures.append(
                    {
                        "trade_index": trade_index,
                        "reason": "order_send_none",
                        "last_error": mt5.last_error(),
                    }
                )
                continue

            if result.retcode != mt5.TRADE_RETCODE_DONE:
                failures.append(
                    {
                        "trade_index": trade_index,
                        "retcode": result.retcode,
                        "comment": result.comment,
                    }
                )
                continue

            orders.append(
                {
                    "trade_index": trade_index,
                    "ticket": int(result.order),
                    "deal": int(result.deal),
                    "price": float(result.price),
                    "volume": volume,
                    "tp": tp,
                    "sl": sl,
                    "comment": comment,
                }
            )
        except Exception as e:
            failures.append({"trade_index": trade_index, "reason": f"exception:{e}"})

    success = len(failures) == 0 and len(orders) == trades_count
    status = 200 if success else 502
    payload = {
        "success": success,
        "symbol": symbol,
        "direction": direction,
        "requested_trades": trades_count,
        "opened_trades": len(orders),
        "orders": orders,
        "failures": failures,
    }
    if not success:
        payload["reason"] = "partial_or_failed_execution"
        logger.error("Relay execution failure: %s", payload)
    else:
        logger.info("Relay execution success: %s", payload)

    return web.json_response(payload, status=status)


async def on_cleanup(app: web.Application) -> None:
    if mt5 is not None:
        mt5.shutdown()
        logger.info("MT5 shutdown complete")


def main() -> None:
    if not validate_config():
        raise SystemExit(1)
    if not ensure_mt5_connection():
        raise SystemExit(1)

    app = web.Application()
    app.router.add_get("/health", health)
    app.router.add_post("/trade", trade)
    app.on_cleanup.append(on_cleanup)
    web.run_app(app, host=CONFIG["relay_host"], port=CONFIG["relay_port"])


if __name__ == "__main__":
    main()
