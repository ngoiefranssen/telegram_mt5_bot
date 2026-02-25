"""
Bot Trading Telegram -> Deriv API
Capture les signaux du canal Hunto Trader et exécute via Deriv API
Lot fixe: 0.02
"""

# Deriv API imports
import websockets
import aiohttp
import json

from telethon import TelegramClient, events
from dotenv import load_dotenv
import re
import asyncio
import logging
import os
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional

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
    'magic_number': 234000,
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
        self.processed_messages = set()
        self.channel_entity = None
        
    async def initialize(self):
        """Initialisation du bot"""
        logger.info("=" * 60)
        logger.info("DÉMARRAGE DU BOT TRADING TELEGRAM -> DERIV API")
        logger.info("=" * 60)
        
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
            await self.deriv_ws.send(json.dumps(auth_request))
            auth_response = json.loads(await self.deriv_ws.recv())
            
            if 'error' in auth_response:
                error_code = auth_response['error'].get('code', 'unknown')
                error_msg = auth_response['error'].get('message', 'Unknown error')
                logger.error(f"[Deriv API] Authentication failure (code: {error_code}): {error_msg}")
                logger.error(f"[Deriv API] Please verify DERIV_API_TOKEN in .env file")
                logger.error(f"[Deriv API] Obtain token from: https://app.deriv.com/account/api-token")
                return False
            
            # Get account info
            balance_request = {"balance": 1, "subscribe": 1}
            await self.deriv_ws.send(json.dumps(balance_request))
            balance_response = json.loads(await self.deriv_ws.recv())
            
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
            logger.info(f"[Telegram] 📡 Canal cible: {self.channel_entity.title}")
            logger.info(f"[Telegram] 🆔 ID: {self.channel_entity.id}")
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
                await self.deriv_ws.send(json.dumps(active_symbols_request))
                response = json.loads(await self.deriv_ws.recv())

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
            Execute trade via Deriv API contract purchase
            Maps MT5 order types to Deriv contract types and handles TP/SL
            """
            try:
                if not self.deriv_ws or not self.deriv_connected:
                    logger.error("[TRADE] Deriv API not connected")
                    logger.info("[TRADE] Attempting to reconnect...")
                    if await self._connect_deriv():
                        logger.info("[TRADE] ✅ Reconnected successfully")
                    else:
                        logger.error("[TRADE] Reconnection failed - Trade skipped")
                        return False

                # Find correct Deriv symbol
                deriv_symbol = await self.find_correct_symbol(signal.symbol)
                if not deriv_symbol:
                    logger.error(f"[TRADE] Cannot map symbol {signal.symbol} - Trade skipped")
                    return False

                # Get current price for the symbol
                tick_request = {"ticks": deriv_symbol, "subscribe": 0}
                await self.deriv_ws.send(json.dumps(tick_request))
                tick_response = json.loads(await self.deriv_ws.recv())

                if 'error' in tick_response:
                    error_code = tick_response['error'].get('code', 'unknown')
                    error_msg = tick_response['error'].get('message', 'Unknown error')
                    
                    # Handle market closed error
                    if 'closed' in error_msg.lower() or error_code == 'MarketIsClosed':
                        logger.error(f"[TRADE] Market closed for {deriv_symbol}")
                        logger.info(f"[TRADE] Trade will be retried when market opens")
                        return False
                    
                    logger.error(f"[TRADE] Error getting price (code: {error_code}): {error_msg}")
                    logger.info(f"[TRADE] Trade skipped")
                    return False

                if 'tick' not in tick_response:
                    logger.error(f"[TRADE] No tick data received for {deriv_symbol}")
                    logger.info(f"[TRADE] Trade skipped")
                    return False

                current_price = float(tick_response['tick']['quote'])
                logger.info(f"[TRADE] Current price for {deriv_symbol}: {current_price}")

                # Determine order type using preserved logic
                point = 0.01  # Standard point size
                price_diff = abs(current_price - signal.entry_price)

                # Order type determination (preserved from original MT5 logic)
                if signal.direction == "BUY":
                    if price_diff <= 10 * point:
                        order_type = "MARKET_BUY"
                        contract_type = "CALL"
                    elif signal.entry_price < current_price:
                        order_type = "BUY_LIMIT"
                        contract_type = "CALL"
                    else:
                        order_type = "BUY_STOP"
                        contract_type = "CALL"
                else:  # SELL
                    if price_diff <= 10 * point:
                        order_type = "MARKET_SELL"
                        contract_type = "PUT"
                    elif signal.entry_price > current_price:
                        order_type = "SELL_LIMIT"
                        contract_type = "PUT"
                    else:
                        order_type = "SELL_STOP"
                        contract_type = "PUT"

                logger.info(f"[TRADE] Order type: {order_type} → Contract type: {contract_type}")

                # Calculate stake from lot size (0.02 lot = $2 stake for simplicity)
                # Note: Deriv uses stake amount, not lot size
                stake = CONFIG['fixed_lot'] * 100  # 0.02 * 100 = $2

                # Handle multiple TPs - use first TP, log others
                first_tp = signal.take_profits[0] if signal.take_profits else None
                if len(signal.take_profits) > 1:
                    logger.info(f"[TRADE] Multiple TPs detected: {signal.take_profits}")
                    logger.info(f"[TRADE] Using first TP: {first_tp}, others logged for manual management")

                # Create proposal request (equivalent to MT5's order_check)
                proposal_request = {
                    "proposal": 1,
                    "amount": stake,
                    "basis": "stake",
                    "contract_type": contract_type,
                    "currency": "USD",
                    "symbol": deriv_symbol,
                    "duration": 60,  # 60 minutes duration
                    "duration_unit": "m"
                }

                # Add limit price for LIMIT orders
                if "LIMIT" in order_type:
                    proposal_request["barrier"] = str(signal.entry_price)

                logger.info(f"[TRADE] Sending proposal request: {proposal_request}")
                await self.deriv_ws.send(json.dumps(proposal_request))
                proposal_response = json.loads(await self.deriv_ws.recv())

                if 'error' in proposal_response:
                    error_code = proposal_response['error'].get('code', 'unknown')
                    error_msg = proposal_response['error'].get('message', 'Unknown error')
                    
                    # Handle insufficient balance error
                    if 'balance' in error_msg.lower() or error_code == 'InsufficientBalance':
                        logger.error(f"[TRADE] Insufficient balance to execute trade")
                        logger.error(f"[TRADE] Required stake: ${stake}, check account balance")
                        logger.info(f"[TRADE] Trade skipped due to insufficient funds")
                        return False
                    
                    # Handle market closed error
                    if 'closed' in error_msg.lower() or error_code == 'MarketIsClosed':
                        logger.error(f"[TRADE] Market closed for {deriv_symbol}")
                        logger.info(f"[TRADE] Trade will be retried when market opens")
                        return False
                    
                    # Handle invalid symbol error
                    if 'symbol' in error_msg.lower() or error_code == 'InvalidSymbol':
                        logger.error(f"[TRADE] Invalid symbol: {deriv_symbol}")
                        logger.info(f"[TRADE] Trade skipped due to invalid symbol")
                        return False
                    
                    # Generic error handling
                    logger.error(f"[TRADE] Proposal error (code: {error_code}): {error_msg}")
                    logger.info(f"[TRADE] Trade skipped")
                    return False

                if 'proposal' not in proposal_response:
                    logger.error(f"[TRADE] Invalid proposal response")
                    logger.info(f"[TRADE] Trade skipped")
                    return False

                proposal_id = proposal_response['proposal']['id']
                logger.info(f"[TRADE]  Proposal validated: {proposal_id}")

                # Execute trade via buy API (equivalent to MT5's order_send)
                buy_request = {
                    "buy": proposal_id,
                    "price": stake
                }

                logger.info(f"[TRADE] Executing buy request: {buy_request}")
                await self.deriv_ws.send(json.dumps(buy_request))
                buy_response = json.loads(await self.deriv_ws.recv())

                if 'error' in buy_response:
                    error_code = buy_response['error'].get('code', 'unknown')
                    error_msg = buy_response['error'].get('message', 'Unknown error')
                    
                    # Handle insufficient balance error
                    if 'balance' in error_msg.lower() or error_code == 'InsufficientBalance':
                        logger.error(f"[TRADE] Insufficient balance to execute trade")
                        logger.error(f"[TRADE] Required stake: ${stake}, check account balance")
                        logger.info(f"[TRADE] Trade skipped due to insufficient funds")
                        return False
                    
                    # Handle authentication failure
                    if 'auth' in error_msg.lower() or error_code in ['AuthorizationRequired', 'InvalidToken']:
                        logger.error(f"[TRADE] Authentication failure: {error_msg}")
                        logger.info(f"[TRADE] Attempting to reconnect...")
                        if await self._connect_deriv():
                            logger.info(f"[TRADE]  Reconnected - Please retry trade manually")
                        else:
                            logger.error(f"[TRADE] Reconnection failed")
                        return False
                    
                    logger.error(f"[TRADE] Buy error (code: {error_code}): {error_msg}")
                    logger.info(f"[TRADE] Trade skipped")
                    return False

                if 'buy' not in buy_response:
                    logger.error(f"[TRADE] Invalid buy response")
                    logger.info(f"[TRADE] Trade skipped")
                    return False

                contract_id = buy_response['buy']['contract_id']
                buy_price = buy_response['buy']['buy_price']

                logger.info("=" * 60)
                logger.info(" TRADE EXECUTED SUCCESSFULLY")
                logger.info(f"Contract ID: {contract_id}")
                logger.info(f"Symbol: {deriv_symbol}")
                logger.info(f"Type: {contract_type}")
                logger.info(f"Entry: {signal.entry_price}")
                logger.info(f"Stake: ${stake}")
                logger.info(f"Buy Price: ${buy_price}")
                if first_tp:
                    logger.info(f"Take Profit: {first_tp}")
                logger.info(f"Stop Loss: {signal.stop_loss}")
                logger.info("=" * 60)

                if first_tp or signal.stop_loss:
                    logger.warning("[TRADE] TP/SL logged for manual management")
                    logger.warning(f"[TRADE] Monitor contract {contract_id} and close at TP: {first_tp} or SL: {signal.stop_loss}")

                return True

            except websockets.exceptions.WebSocketException as e:
                logger.error(f"[TRADE] WebSocket error executing trade: {e}")
                logger.info(f"[TRADE] Attempting to reconnect...")
                if await self._connect_deriv():
                    logger.info(f"[TRADE]  Reconnected - Please retry trade manually")
                else:
                    logger.error(f"[TRADE] Reconnection failed")
                return False
            except Exception as e:
                logger.error(f"[TRADE] Unexpected error executing trade: {e}")
                logger.exception(e)
                logger.info(f"[TRADE] Trade skipped due to error")
                return False
            
    async def handle_new_message(self, event):
        """Gestionnaire de nouveaux messages"""
        try:
            # Vérifier si c'est le bon canal
            if event.chat_id != self.channel_entity.id:
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
            logger.info(f"[Telegram] Nouveau message du canal")
            
            # Parsing et exécution
            signal = self.parse_signal(text)
            if signal is None:
                logger.info("[Telegram] Message ignoré (pas un signal)")
                return
                
            # Exécution immédiate
            success = self.execute_trade(signal)
            
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


async def main():
    if not validate_config():
        exit(1)
        
    bot = TelegramDerivBot()
    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\n\n Interruption par l'utilisateur")
    except Exception as e:
        logger.error(f" Erreur fatale: {e}", exc_info=True)
    finally:
        bot.shutdown()


if __name__ == "__main__":
    asyncio.run(main())