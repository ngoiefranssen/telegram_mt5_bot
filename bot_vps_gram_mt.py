"""
Bot Trading Telegram -> Deriv API
Capture les signaux du canal Hunto Trader et exécute via Deriv API
Lot fixe: 0.02
"""

# Deriv API imports
import websockets
import aiohttp
import json

from telethon import TelegramClient, events, utils as telethon_utils
from dotenv import load_dotenv
import re
import asyncio
import logging
import os
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from aiohttp import web

# Charger les variables d'environnement
load_dotenv()

# Configuration Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('trading_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
CONFIG = {
    'telegram_api_id': int(os.getenv('TELEGRAM_API_ID', '0')),
    'telegram_api_hash': os.getenv('TELEGRAM_API_HASH', ''),
    'channel_username': os.getenv('CHANNEL_USERNAME', 'hunto4x_fullaccourcy92'),
    
    # Deriv API configuration
    'deriv_api_token': os.getenv('DERIV_API_TOKEN', ''),
    'deriv_app_id': os.getenv('DERIV_APP_ID', '1089'),  # Default for binary.com
    
    # Deprecated MT5 configuration (no longer used)
    # 'mt5_account': int(os.getenv('MT5_ACCOUNT', '0')),
    # 'mt5_password': os.getenv('MT5_PASSWORD', ''),
    # 'mt5_server': os.getenv('MT5_SERVER', ''),
    
    'fixed_lot': float(os.getenv('FIXED_LOT', '0.02')),
    'target_tp_number': int(os.getenv('TARGET_TP_NUMBER', '4')),
    'trades_per_signal': int(os.getenv('TRADES_PER_SIGNAL', '2')),
    'magic_number': 234000,
    'history_file': os.getenv('TRADE_HISTORY_FILE', 'trade_history.jsonl'),
    'monitor_poll_seconds': int(os.getenv('MONITOR_POLL_SECONDS', '30')),
}


class TradeHistoryStore:
    """Persist trade events and compute rolling summaries."""

    def __init__(self, path: str):
        self.path = path

    def record_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        event = {
            "ts": datetime.utcnow().isoformat(),
            "event_type": event_type,
            **payload,
        }
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=True) + "\n")

    def _load_events(self) -> List[Dict[str, Any]]:
        if not os.path.exists(self.path):
            return []
        events: List[Dict[str, Any]] = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    logger.warning("[History] Invalid JSON line skipped")
        return events

    def summarize(self, days: int) -> Dict[str, int]:
        cutoff = datetime.utcnow() - timedelta(days=days)
        events = self._load_events()
        filtered: List[Dict[str, Any]] = []
        for event in events:
            ts_raw = event.get("ts")
            if not ts_raw:
                continue
            try:
                ts = datetime.fromisoformat(ts_raw)
            except ValueError:
                continue
            if ts >= cutoff:
                filtered.append(event)

        trades_taken = sum(1 for e in filtered if e.get("event_type") == "trade_opened")
        execution_failures = sum(1 for e in filtered if e.get("event_type") == "trade_execution_failed")
        gains = sum(
            1
            for e in filtered
            if e.get("event_type") == "trade_closed" and e.get("outcome") == "gain"
        )
        echec = sum(
            1
            for e in filtered
            if e.get("event_type") == "trade_closed" and e.get("outcome") == "echec"
        )
        flat = sum(
            1
            for e in filtered
            if e.get("event_type") == "trade_closed" and e.get("outcome") == "flat"
        )
        total_closed = gains + echec + flat
        pending = max(trades_taken - total_closed, 0)
        total_all = trades_taken + execution_failures
        return {
            "trades_taken": trades_taken,
            "gains": gains,
            "echec": echec,
            "flat": flat,
            "total_closed": total_closed,
            "pending": pending,
            "execution_failures": execution_failures,
            "total_all": total_all,
        }

@dataclass
class TradingSignal:
    """Structure d'un signal de trading"""
    symbol: str
    direction: str
    entry_price: float
    take_profits: List[float]
    stop_loss: float
    raw_text: str
    received_at: datetime
    
    def display(self):
        """Affichage formaté du signal"""
        return f"""

    SIGNAL DÉTECTÉ

    Symbole:     {self.symbol:<36}
    Direction:   {self.direction:<36}
    Entrée:      {self.entry_price:<36}
    SL:          {self.stop_loss:<36}
    TPs:         {str(self.take_profits):<36}
    Heure:       {self.received_at.strftime('%H:%M:%S'):<36}

"""


class TelegramDerivBot:
    def __init__(self):
        self.client: Optional[TelegramClient] = None
        self.deriv_connected = False
        self.deriv_ws = None
        self.ws_lock = asyncio.Lock()
        self.processed_messages = set()
        self.channel_entity = None
        self.history = TradeHistoryStore(CONFIG['history_file'])
        self.monitor_tasks = set()

    async def _ws_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.deriv_ws:
            raise RuntimeError("Deriv WebSocket is not connected")
        async with self.ws_lock:
            await self.deriv_ws.send(json.dumps(payload))
            return json.loads(await self.deriv_ws.recv())

    def _track_task(self, task: asyncio.Task) -> None:
        self.monitor_tasks.add(task)
        task.add_done_callback(self.monitor_tasks.discard)

    def _log_history_summary(self) -> None:
        week = self.history.summarize(7)
        month = self.history.summarize(30)
        logger.info(
            "[History] 7j trades=%s gain=%s echec=%s total=%s",
            week["trades_taken"],
            week["gains"],
            week["echec"],
            week["total_all"],
        )
        logger.info(
            "[History] 30j trades=%s gain=%s echec=%s total=%s",
            month["trades_taken"],
            month["gains"],
            month["echec"],
            month["total_all"],
        )

    async def _monitor_contract_result(
        self,
        contract_id: int,
        signal: TradingSignal,
        deriv_symbol: str,
        contract_type: str,
        take_profit_level: Optional[float] = None,
    ) -> None:
        """Poll Deriv until contract closes, then record gain/echec."""
        try:
            max_checks = max(int((8 * 60 * 60) / max(CONFIG['monitor_poll_seconds'], 5)), 1)
            for _ in range(max_checks):
                response = await self._ws_request({
                    "proposal_open_contract": 1,
                    "contract_id": contract_id,
                })
                if 'error' in response:
                    await asyncio.sleep(CONFIG['monitor_poll_seconds'])
                    continue

                poc = response.get("proposal_open_contract", {})
                if not poc.get("is_sold"):
                    await asyncio.sleep(CONFIG['monitor_poll_seconds'])
                    continue

                profit = float(poc.get("profit", 0.0))
                if profit > 0:
                    outcome = "gain"
                elif profit < 0:
                    outcome = "echec"
                else:
                    outcome = "flat"

                self.history.record_event(
                    "trade_closed",
                    {
                        "contract_id": contract_id,
                        "symbol": signal.symbol,
                        "deriv_symbol": deriv_symbol,
                        "direction": signal.direction,
                        "contract_type": contract_type,
                        "entry_price": signal.entry_price,
                        "tp": take_profit_level,
                        "sl": signal.stop_loss,
                        "profit": profit,
                        "outcome": outcome,
                    },
                )
                logger.info(
                    "[TRADE] Contract %s closed outcome=%s profit=%s",
                    contract_id,
                    outcome,
                    profit,
                )
                self._log_history_summary()
                return
        except asyncio.CancelledError:
            logger.info("[TRADE] Monitor task cancelled for contract %s", contract_id)
            raise
        except Exception as e:
            logger.error("[TRADE] Monitor error for contract %s: %s", contract_id, e)
        
    async def initialize(self):
        """Initialisation du bot"""
        logger.info("=" * 60)
        logger.info("DÉMARRAGE DU BOT TRADING TELEGRAM -> DERIV API")
        logger.info("=" * 60)
        self._log_history_summary()
        
        # Connexion Deriv API
        if not await self._connect_deriv():
            raise Exception("Impossible de connecter Deriv API")
            
        # Connexion Telegram
        await self._connect_telegram()
        
    async def _connect_deriv(self) -> bool:
        """Connexion à Deriv API via WebSocket"""
        logger.info("[Deriv API] Initialisation...")
        
        try:
            # WebSocket connection to Deriv API
            ws_url = f"wss://ws.binaryws.com/websockets/v3?app_id={CONFIG['deriv_app_id']}"
            logger.info(f"[Deriv API] Connexion à {ws_url}...")
            
            self.deriv_ws = await websockets.connect(ws_url)
            logger.info("[Deriv API] WebSocket connecté")
            
            # Authenticate with API token
            auth_request = {
                "authorize": CONFIG['deriv_api_token']
            }
            auth_response = await self._ws_request(auth_request)
            
            if 'error' in auth_response:
                error_code = auth_response['error'].get('code', 'unknown')
                error_msg = auth_response['error'].get('message', 'Unknown error')
                logger.error(f"[Deriv API] Authentication failure (code: {error_code}): {error_msg}")
                logger.error(f"[Deriv API] Please verify DERIV_API_TOKEN in .env file")
                logger.error(f"[Deriv API] Obtain token from: https://app.deriv.com/account/api-token")
                return False
            
            # Get account info
            balance_request = {"balance": 1, "subscribe": 0}
            balance_response = await self._ws_request(balance_request)
            
            if 'error' in balance_response:
                error_msg = balance_response['error'].get('message', 'Unknown error')
                logger.error(f"[Deriv API] Error fetching balance: {error_msg}")
                return False
            
            if 'balance' in balance_response:
                balance = balance_response['balance']['balance']
                currency = balance_response['balance']['currency']
                logger.info(f"[Deriv API] Connecté")
                logger.info(f"[Deriv API] Balance: {balance} {currency}")
            
            self.deriv_connected = True
            return True
            
        except websockets.exceptions.WebSocketException as e:
            logger.error(f"[Deriv API] WebSocket connection error: {e}")
            logger.error(f"[Deriv API] Check network connectivity and firewall settings")
            return False
        except Exception as e:
            logger.error(f"[Deriv API] Unexpected connection error: {e}")
            logger.exception(e)
            return False
        
    async def _connect_telegram(self):
        """Connexion à Telegram"""
        logger.info("[Telegram] Connexion...")
        
        # Check if we have a session string from environment (for Render deployment)
        session_string = os.getenv('TELEGRAM_SESSION')
        
        if session_string:
            # Use StringSession for deployment
            from telethon.sessions import StringSession
            logger.info("[Telegram] Utilisation de la session depuis variable d'environnement")
            self.client = TelegramClient(
                StringSession(session_string),
                CONFIG['telegram_api_id'],
                CONFIG['telegram_api_hash']
            )
        else:
            # Use file-based session for local development
            logger.info("[Telegram] Utilisation de la session fichier (développement local)")
            self.client = TelegramClient(
                'trading_session',
                CONFIG['telegram_api_id'],
                CONFIG['telegram_api_hash']
            )
        
        await self.client.start()
        me = await self.client.get_me()
        logger.info(f"[Telegram]  Connecté en tant que {me.first_name}")
        
        # Résolution du canal
        try:
            self.channel_entity = await self.client.get_entity(CONFIG['channel_username'])
            marked_chat_id = telethon_utils.get_peer_id(self.channel_entity)
            logger.info(f"[Telegram] Canal cible: {self.channel_entity.title}")
            logger.info(f"[Telegram] ID: {self.channel_entity.id}")
            logger.info(f"[Telegram] Marked chat_id: {marked_chat_id}")
        except Exception as e:
            logger.error(f"[Telegram] Erreur canal: {e}")
            raise
            
    def parse_signal(self, text: str) -> Optional[TradingSignal]:
        """
        Parser le signal avec format flexible
        """
        try:
            lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
            
            if len(lines) < 3:
                return None
                
            # Ligne 1: #XAUUSD BUY 5130 ou XAUUSD BUY 5130
            header_line = lines[0]
            
            # Pattern flexible pour le header
            header_pattern = r'#?\s*(\w+)\s+(BUY|SELL)\s+(\d+\.?\d*)'
            header_match = re.search(header_pattern, header_line, re.IGNORECASE)
            
            if not header_match:
                return None
                
            symbol = header_match.group(1).upper()
            direction = header_match.group(2).upper()
            entry_price = float(header_match.group(3))
            
            # Extraction des TPs et SL
            take_profits = []
            sl_price = None
            
            for line in lines[1:]:
                # TP: TP1.@ 5133, TP1. @ 5133, TP1 @ 5133, TP1: 5133
                tp_match = re.search(r'TP\d+[\.:]?\s*[@©]?\s*(\d+\.?\d*)', line, re.IGNORECASE)
                if tp_match:
                    take_profits.append(float(tp_match.group(1)))
                    continue
                
                # SL: SL.@ 5118, SL. @ 5118, SL @ 5118, SL: 5118
                sl_match = re.search(r'SL[\.:]?\s*[@©]?\s*(\d+\.?\d*)', line, re.IGNORECASE)
                if sl_match:
                    sl_price = float(sl_match.group(1))
                    continue
            
            if not take_profits or sl_price is None:
                return None
            #
            signal = TradingSignal(
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                take_profits=take_profits,
                stop_loss=sl_price,
                raw_text=text,
                received_at=datetime.now()
            )
            
            # Affichage immédiat du signal détecté
            print(signal.display())
            logger.info(f"[Parser]  Signal valide: {direction} {symbol} @ {entry_price}")
            
            return signal
            
        except Exception as e:
            logger.error(f"[Parser] Erreur: {e}")
            return None
            
    async def find_correct_symbol(self, symbol: str) -> Optional[str]:
            """
            Map Telegram signal symbols to Deriv trading symbols
            Uses Deriv active_symbols API to validate symbols
            """
            # Symbol mapping: Telegram signal format → Deriv API format
            symbol_map = {
                'XAUUSD': 'frxXAUUSD',  # Gold
                'XAGUSD': 'frxXAGUSD',  # argent
                'EURUSD': 'frxEURUSD',  # Euro/US Dollar
                'GBPUSD': 'frxGBPUSD',  # British Pound/US Dollar
                'USDJPY': 'frxUSDJPY',  # US Dollar/Japanese Yen
                'AUDUSD': 'frxAUDUSD',  # Australian Dollar/US Dollar
                'USDCAD': 'frxUSDCAD',  # US Dollar/Canadian Dollar
                'USDCHF': 'frxUSDCHF',  # US Dollar/Swiss Franc
                'NZDUSD': 'frxNZDUSD',  # New Zealand Dollar/US Dollar
                'EURGBP': 'frxEURGBP',  # Euro/British Pound
                'EURJPY': 'frxEURJPY',  # Euro/Japanese Yen
                'GBPJPY': 'frxGBPJPY',  # British Pound/Japanese Yen
                'BTCUSD': 'cryBTCUSD',  # Bitcoin
                'ETHUSD': 'cryETHUSD',  # Ethereum
            }

            # Try direct mapping first
            deriv_symbol = symbol_map.get(symbol.upper())

            if not deriv_symbol:
                logger.error(f"[Symbol] Invalid symbol: {symbol} - No mapping found")
                logger.info(f"[Symbol] Available symbols: {', '.join(symbol_map.keys())}")
                logger.info(f"[Symbol] Trade skipped for invalid symbol")
                return None

            logger.info(f"[Symbol] Mapped {symbol} → {deriv_symbol}")

            # Validate symbol with Deriv API
            try:
                if not self.deriv_ws:
                    logger.error("[Symbol] Deriv WebSocket not connected")
                    return None

                # Request active symbols from Deriv API
                active_symbols_request = {
                    "active_symbols": "brief",
                    "product_type": "basic"
                }
                response = await self._ws_request(active_symbols_request)

                if 'error' in response:
                    error_code = response['error'].get('code', 'unknown')
                    error_msg = response['error'].get('message', 'Unknown error')
                    logger.error(f"[Symbol] Deriv API error (code: {error_code}): {error_msg}")
                    logger.info(f"[Symbol] Trade skipped due to API error")
                    return None

                # Check if our mapped symbol exists in active symbols
                if 'active_symbols' in response:
                    active_symbols = response['active_symbols']
                    symbol_exists = any(s['symbol'] == deriv_symbol for s in active_symbols)

                    if symbol_exists:
                        logger.info(f"[Symbol]  Validated: {deriv_symbol}")
                        return deriv_symbol
                    else:
                        logger.error(f"[Symbol] Invalid symbol: {deriv_symbol} not found in active symbols")
                        logger.info(f"[Symbol] Trade skipped for invalid symbol")
                        return None

            except websockets.exceptions.WebSocketException as e:
                logger.error(f"[Symbol] WebSocket error validating symbol: {e}")
                logger.info(f"[Symbol] Trade skipped due to connection error")
                return None
            except Exception as e:
                logger.error(f"[Symbol] Unexpected error validating symbol: {e}")
                logger.exception(e)
                logger.info(f"[Symbol] Trade skipped due to error")
                return None
        
    async def execute_trade(self, signal: TradingSignal) -> bool:
            """
            Execute trade immediately from Telegram signal.
            BUY -> CALL, SELL -> PUT (no LIMIT/STOP logic).
            """
            try:
                def _record_trade_failure(reason: str, trade_index: Optional[int] = None) -> None:
                    payload: Dict[str, Any] = {
                        "symbol": signal.symbol,
                        "direction": signal.direction,
                        "entry_price": signal.entry_price,
                        "reason": reason,
                    }
                    if trade_index is not None:
                        payload["trade_index"] = trade_index
                    self.history.record_event("trade_execution_failed", payload)
                    self._log_history_summary()

                if not self.deriv_ws or not self.deriv_connected:
                    logger.error("[TRADE] Deriv API not connected")
                    logger.info("[TRADE] Attempting to reconnect...")
                    if await self._connect_deriv():
                        logger.info("[TRADE] Reconnected successfully")
                    else:
                        logger.error("[TRADE] Reconnection failed - Trade skipped")
                        return False

                # Find correct Deriv symbol
                deriv_symbol = await self.find_correct_symbol(signal.symbol)
                if not deriv_symbol:
                    logger.error(f"[TRADE] Cannot map symbol {signal.symbol} - Trade skipped")
                    return False

                if signal.direction == "BUY":
                    contract_type = "CALL"
                elif signal.direction == "SELL":
                    contract_type = "PUT"
                else:
                    logger.error(f"[TRADE] Invalid direction: {signal.direction}")
                    return False

                logger.info(f"[TRADE] Immediate market execution: {signal.direction} -> {contract_type}")

                # Calculate stake from lot size (0.02 lot = $2 stake for simplicity)
                # Note: Deriv uses stake amount, not lot size
                stake = CONFIG['fixed_lot'] * 100  # 0.02 * 100 = $2

                target_tp_number = max(int(CONFIG.get('target_tp_number', 4)), 1)
                trades_per_signal = max(int(CONFIG.get('trades_per_signal', 2)), 1)
                target_tp_index = target_tp_number - 1

                if len(signal.take_profits) <= target_tp_index:
                    logger.error(
                        "[TRADE] Signal missing TP%s. Available TPs=%s -> trade skipped",
                        target_tp_number,
                        signal.take_profits,
                    )
                    _record_trade_failure(f"missing_tp{target_tp_number}")
                    return False

                selected_tp = signal.take_profits[target_tp_index]
                logger.info(f"[TRADE] Multiple TPs detected: {signal.take_profits}")
                logger.info(
                    "[TRADE] Enforcing TP%s only for all trades: %s",
                    target_tp_number,
                    selected_tp,
                )
                logger.info(
                    "[TRADE] Opening %s trades with identical TP/SL (entry price ignored)",
                    trades_per_signal,
                )

                opened_count = 0
                for trade_index in range(1, trades_per_signal + 1):
                    # Create proposal request for immediate execution
                    proposal_request = {
                        "proposal": 1,
                        "amount": stake,
                        "basis": "stake",
                        "contract_type": contract_type,
                        "currency": "USD",
                        "symbol": deriv_symbol,
                        "duration": 60,  # 60 minutes duration
                        "duration_unit": "m",
                    }

                    # Attempt to attach TP/SL directly to the order when supported by Deriv.
                    limit_order = {}
                    if selected_tp is not None:
                        limit_order["take_profit"] = float(selected_tp)
                    if signal.stop_loss is not None:
                        limit_order["stop_loss"] = float(signal.stop_loss)
                    if limit_order:
                        proposal_request["limit_order"] = limit_order

                    logger.info(
                        "[TRADE] [%s/%s] Sending proposal request: %s",
                        trade_index,
                        trades_per_signal,
                        proposal_request,
                    )
                    proposal_response = await self._ws_request(proposal_request)

                    if 'error' in proposal_response and "limit_order" in proposal_request:
                        error_msg = proposal_response['error'].get('message', 'Unknown error')
                        logger.warning(
                            "[TRADE] [%s/%s] TP/SL not accepted on this contract type by Deriv API: %s",
                            trade_index,
                            trades_per_signal,
                            error_msg,
                        )
                        logger.warning(
                            "[TRADE] [%s/%s] Retrying immediate market order without TP/SL attachment",
                            trade_index,
                            trades_per_signal,
                        )
                        proposal_request = {k: v for k, v in proposal_request.items() if k != "limit_order"}
                        logger.info(
                            "[TRADE] [%s/%s] Sending fallback proposal request: %s",
                            trade_index,
                            trades_per_signal,
                            proposal_request,
                        )
                        proposal_response = await self._ws_request(proposal_request)

                    if 'error' in proposal_response:
                        error_code = proposal_response['error'].get('code', 'unknown')
                        error_msg = proposal_response['error'].get('message', 'Unknown error')

                        # Handle insufficient balance error
                        if 'balance' in error_msg.lower() or error_code == 'InsufficientBalance':
                            logger.error(f"[TRADE] Insufficient balance to execute trade")
                            logger.error(f"[TRADE] Required stake: ${stake}, check account balance")
                            logger.info(f"[TRADE] Trade skipped due to insufficient funds")
                            _record_trade_failure("insufficient_balance", trade_index)
                            return False

                        # Handle market closed error
                        if 'closed' in error_msg.lower() or error_code == 'MarketIsClosed':
                            logger.error(f"[TRADE] Market closed for {deriv_symbol}")
                            logger.info(f"[TRADE] Trade will be retried when market opens")
                            _record_trade_failure("market_closed", trade_index)
                            return False

                        # Handle invalid symbol error
                        if 'symbol' in error_msg.lower() or error_code == 'InvalidSymbol':
                            logger.error(f"[TRADE] Invalid symbol: {deriv_symbol}")
                            logger.info(f"[TRADE] Trade skipped due to invalid symbol")
                            _record_trade_failure("invalid_symbol", trade_index)
                            return False

                        # Generic error handling
                        logger.error(f"[TRADE] Proposal error (code: {error_code}): {error_msg}")
                        logger.info(f"[TRADE] Trade skipped")
                        _record_trade_failure(f"proposal_error:{error_code}", trade_index)
                        return False

                    if 'proposal' not in proposal_response:
                        logger.error(f"[TRADE] Invalid proposal response")
                        logger.info(f"[TRADE] Trade skipped")
                        _record_trade_failure("invalid_proposal_response", trade_index)
                        return False

                    proposal_id = proposal_response['proposal']['id']
                    logger.info(
                        "[TRADE] [%s/%s] Proposal validated: %s",
                        trade_index,
                        trades_per_signal,
                        proposal_id,
                    )

                    # Execute trade via buy API (equivalent to MT5's order_send)
                    buy_request = {
                        "buy": proposal_id,
                        "price": stake,
                    }

                    logger.info(
                        "[TRADE] [%s/%s] Executing buy request: %s",
                        trade_index,
                        trades_per_signal,
                        buy_request,
                    )
                    buy_response = await self._ws_request(buy_request)

                    if 'error' in buy_response:
                        error_code = buy_response['error'].get('code', 'unknown')
                        error_msg = buy_response['error'].get('message', 'Unknown error')

                        # Handle insufficient balance error
                        if 'balance' in error_msg.lower() or error_code == 'InsufficientBalance':
                            logger.error(f"[TRADE] Insufficient balance to execute trade")
                            logger.error(f"[TRADE] Required stake: ${stake}, check account balance")
                            logger.info(f"[TRADE] Trade skipped due to insufficient funds")
                            _record_trade_failure("insufficient_balance", trade_index)
                            return False

                        # Handle authentication failure
                        if 'auth' in error_msg.lower() or error_code in ['AuthorizationRequired', 'InvalidToken']:
                            logger.error(f"[TRADE] Authentication failure: {error_msg}")
                            logger.info(f"[TRADE] Attempting to reconnect...")
                            if await self._connect_deriv():
                                logger.info(f"[TRADE]  Reconnected - Please retry trade manually")
                            else:
                                logger.error(f"[TRADE] Reconnection failed")
                            _record_trade_failure("auth_failure", trade_index)
                            return False

                        logger.error(f"[TRADE] Buy error (code: {error_code}): {error_msg}")
                        logger.info(f"[TRADE] Trade skipped")
                        _record_trade_failure(f"buy_error:{error_code}", trade_index)
                        return False

                    if 'buy' not in buy_response:
                        logger.error(f"[TRADE] Invalid buy response")
                        logger.info(f"[TRADE] Trade skipped")
                        _record_trade_failure("invalid_buy_response", trade_index)
                        return False

                    contract_id = buy_response['buy']['contract_id']
                    buy_price = buy_response['buy']['buy_price']

                    logger.info("=" * 60)
                    logger.info(" TRADE EXECUTED SUCCESSFULLY")
                    logger.info(f"Trade: {trade_index}/{trades_per_signal}")
                    logger.info(f"Contract ID: {contract_id}")
                    logger.info(f"Symbol: {deriv_symbol}")
                    logger.info(f"Type: {contract_type}")
                    logger.info(f"Entry: {signal.entry_price}")
                    logger.info(f"Stake: ${stake}")
                    logger.info(f"Buy Price: ${buy_price}")
                    logger.info(
                        "Take Profit (TP%s): %s",
                        target_tp_number,
                        selected_tp,
                    )
                    logger.info(f"Stop Loss: {signal.stop_loss}")
                    logger.info("=" * 60)

                    if selected_tp or signal.stop_loss:
                        logger.info("[TRADE] TP/SL requested on order")

                    self.history.record_event(
                        "trade_opened",
                        {
                            "contract_id": contract_id,
                            "symbol": signal.symbol,
                            "deriv_symbol": deriv_symbol,
                            "direction": signal.direction,
                            "contract_type": contract_type,
                            "entry_price": signal.entry_price,
                            "buy_price": buy_price,
                            "stake": stake,
                            "tp": selected_tp,
                            "sl": signal.stop_loss,
                            "trade_index": trade_index,
                            "trades_per_signal": trades_per_signal,
                        },
                    )
                    self._log_history_summary()
                    monitor_task = asyncio.create_task(
                        self._monitor_contract_result(
                            contract_id,
                            signal,
                            deriv_symbol,
                            contract_type,
                            selected_tp,
                        )
                    )
                    self._track_task(monitor_task)
                    opened_count += 1

                logger.info(
                    "[TRADE] Opened %s/%s trades with identical TP/SL",
                    opened_count,
                    trades_per_signal,
                )
                return opened_count == trades_per_signal

            except websockets.exceptions.WebSocketException as e:
                logger.error(f"[TRADE] WebSocket error executing trade: {e}")
                logger.info(f"[TRADE] Attempting to reconnect...")
                if await self._connect_deriv():
                    logger.info(f"[TRADE]  Reconnected - Please retry trade manually")
                else:
                    logger.error(f"[TRADE] Reconnection failed")
                _record_trade_failure("websocket_error")
                return False
            except Exception as e:
                logger.error(f"[TRADE] Unexpected error executing trade: {e}")
                logger.exception(e)
                logger.info(f"[TRADE] Trade skipped due to error")
                _record_trade_failure("unexpected_error")
                return False
            
    async def handle_new_message(self, event):
        """Gestionnaire de nouveaux messages"""
        try:
            # Safety check when called directly (handler already filters by channel).
            expected_chat_id = telethon_utils.get_peer_id(self.channel_entity) if self.channel_entity else None
            if expected_chat_id is not None and event.chat_id != expected_chat_id:
                logger.info(
                    "[Telegram] Message ignoré (chat différent): event.chat_id=%s expected=%s",
                    event.chat_id,
                    expected_chat_id,
                )
                return

            # Éviter les doublons
            msg_id = event.message.id
            if msg_id in self.processed_messages:
                return
            self.processed_messages.add(msg_id)
            
            # Nettoyage périodique
            if len(self.processed_messages) > 10000:
                self.processed_messages.clear()
                
            text = event.message.message
            if not text:
                return
                
            logger.info("-" * 60)
            logger.info(f"[Telegram] Nouveau message du canal (chat_id={event.chat_id}, msg_id={msg_id})")
            
            # Parsing et exécution
            signal = self.parse_signal(text)
            if signal is None:
                logger.info("[Telegram] Message ignoré (pas un signal)")
                return
                
            # Exécution immédiate
            success = await self.execute_trade(signal)
            
            if success:
                print(f"\n{'='*60}")
                print(" SIGNAL TRAITÉ AVEC SUCCÈS")
                print(f"{'='*60}\n")
            else:
                print(f"\n{'='*60}")
                print("ÉCHEC DU TRAITEMENT")
                print(f"{'='*60}\n")
                
        except Exception as e:
            logger.error(f"[Handler] Erreur: {e}", exc_info=True)
            
    async def run(self):
        """Boucle principale"""
        await self.initialize()

        # Enregistrement du handler pour le canal spécifique
        @self.client.on(events.NewMessage(chats=self.channel_entity))
        async def handler(event):
            await self.handle_new_message(event)
            
        print(f"\n{'='*60}")
        print("BOT EN ÉCOUTE...")
        print(f"Canal: {self.channel_entity.title}")
        print("Appuyez sur Ctrl+C pour arrêter")
        print(f"{'='*60}\n")
        
        await self.client.run_until_disconnected()
        
    def shutdown(self):
        """Arrêt propre"""
        logger.info("[System] Arrêt du bot...")
        for task in list(self.monitor_tasks):
            task.cancel()
        if self.deriv_connected and self.deriv_ws:
            asyncio.create_task(self.deriv_ws.close())
            logger.info("[Deriv API] Déconnecté")
        print("Bot arrêté")


def validate_config():
    """Validation de la configuration"""
    required = {
        'TELEGRAM_API_ID': CONFIG['telegram_api_id'],
        'TELEGRAM_API_HASH': CONFIG['telegram_api_hash'],
        'DERIV_API_TOKEN': CONFIG['deriv_api_token'],
        'DERIV_APP_ID': CONFIG['deriv_app_id'],
    }
    
    missing = [k for k, v in required.items() if not v or v == 0]
    
    if missing:
        print("\n" + "*30")
        print("ERREUR: Configuration incomplète!")
        print("*30")
        print(f"\nVariables manquantes: {', '.join(missing)}")
        print("\nCréez un fichier .env avec:")
        print("-" * 40)
        print('DERIV_API_TOKEN="your_api_token_here"  # Obtain from https://app.deriv.com/account/api-token')
        print('DERIV_APP_ID="1089"  # Default for binary.com')
        print("FIXED_LOT=0.02")
        print("-" * 40)
        print("\n  Deprecated (no longer used):")
        print('# MT5_SERVER="Deriv-Demo"')
        print("-" * 40)
        return False
    return True


async def health_check(request):
    """Health check endpoint for Render"""
    return web.Response(text="Bot is running", status=200)


async def stats_handler(request):
    """Expose week/month trade statistics."""
    bot: TelegramDerivBot = request.app["bot"]
    return web.json_response({
        "week_7d": bot.history.summarize(7),
        "month_30d": bot.history.summarize(30),
    })


async def start_http_server(bot: TelegramDerivBot):
    """Start HTTP server for Render port binding"""
    app = web.Application()
    app["bot"] = bot
    app.router.add_get('/health', health_check)
    app.router.add_get('/', health_check)
    app.router.add_get('/stats', stats_handler)
    
    port = int(os.getenv('PORT', 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"[HTTP] Server started on port {port}")
    return runner


async def main():
    if not validate_config():
        exit(1)

    bot = TelegramDerivBot()
    # Start HTTP server for Render
    http_runner = await start_http_server(bot)
    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\n\n Interruption par l'utilisateur")
    except Exception as e:
        logger.error(f" Erreur fatale: {e}", exc_info=True)
    finally:
        bot.shutdown()
        await http_runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
