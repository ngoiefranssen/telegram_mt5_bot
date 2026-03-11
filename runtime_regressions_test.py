import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from bot_vps_gram_mt import TelegramDerivBot, TradingSignal


class TestTelegramChatIdHandling(unittest.IsolatedAsyncioTestCase):
    async def test_handle_new_message_accepts_marked_chat_id(self):
        bot = TelegramDerivBot()
        bot.channel_entity = SimpleNamespace(id=123456789)
        bot.parse_signal = MagicMock(return_value=object())
        bot.execute_trade = AsyncMock(return_value=True)

        event = SimpleNamespace(
            chat_id=-100123456789,
            message=SimpleNamespace(
                id=77,
                message="#XAUUSD BUY 5100\nTP1. @ 5103\nSL. @ 5095",
            ),
        )

        with patch("bot_vps_gram_mt.telethon_utils.get_peer_id", return_value=-100123456789):
            await bot.handle_new_message(event)

        bot.parse_signal.assert_called_once()
        bot.execute_trade.assert_awaited_once()


class TestDerivLimitOrderFallback(unittest.IsolatedAsyncioTestCase):
    async def test_execute_trade_retries_without_limit_order(self):
        bot = TelegramDerivBot()
        bot.deriv_connected = True
        bot.deriv_ws = object()
        bot.find_correct_symbol = AsyncMock(return_value="frxXAUUSD")
        bot.history.record_event = MagicMock()
        bot._log_history_summary = MagicMock()

        signal = TradingSignal(
            symbol="XAUUSD",
            direction="SELL",
            entry_price=5104.0,
            take_profits=[5101.0, 5098.0, 5095.0, 5092.0],
            stop_loss=5115.0,
            raw_text="#XAUUSD SELL 5104",
            received_at=datetime.now(timezone.utc),
        )

        async def ws_side_effect(payload):
            if payload.get("proposal") == 1 and "limit_order" in payload:
                return {
                    "error": {
                        "code": "InvalidRequest",
                        "message": "limit_order not allowed",
                    }
                }
            if payload.get("proposal") == 1:
                return {"proposal": {"id": "P1"}}
            if "buy" in payload:
                return {"buy": {"contract_id": 42, "buy_price": 2.0}}
            return {}

        bot._ws_request = AsyncMock(side_effect=ws_side_effect)
        bot._monitor_contract_result = AsyncMock(return_value=None)
        success = await bot.execute_trade(signal)

        self.assertTrue(success)
        self.assertGreaterEqual(bot._ws_request.await_count, 3)

        first_request = bot._ws_request.await_args_list[0].args[0]
        second_request = bot._ws_request.await_args_list[1].args[0]
        self.assertIn("limit_order", first_request)
        self.assertEqual(first_request["limit_order"]["take_profit"], 5092.0)
        self.assertNotIn("limit_order", second_request)


if __name__ == "__main__":
    unittest.main()
