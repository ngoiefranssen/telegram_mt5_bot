# Bugfix Requirements Document

## Introduction

Le bot de trading Telegram ne peut pas démarrer sur un serveur Linux hébergé car il tente de se connecter à MetaTrader5 via un bridge RPyC qui n'est pas disponible. L'erreur `[Errno 111] Connection refused` se produit lors de l'initialisation MT5, empêchant le bot de fonctionner. Cette architecture nécessite MT5 installé localement ou accessible via Wine+RPyC, ce qui n'est pas viable sur un serveur Linux distant.

La solution consiste à migrer vers l'API Deriv (WebSocket/REST) qui permet une connexion directe au broker sans dépendance MT5, tout en utilisant le même compte de trading Deriv que l'application MT5 mobile de l'utilisateur.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN the bot starts on a Linux server without MT5 installed THEN the system crashes with "[Errno 111] Connection refused" during MT5 bridge connection

1.2 WHEN the bot attempts to initialize MT5 via `mt5linux.MetaTrader5()` THEN the system fails because the RPyC bridge server is not running

1.3 WHEN the bot tries to execute `mt5.login()` after failed initialization THEN the system cannot authenticate with the broker

1.4 WHEN the bot receives a valid trading signal from Telegram THEN the system cannot execute the trade because MT5 connection is unavailable

### Expected Behavior (Correct)

2.1 WHEN the bot starts on a Linux server without MT5 installed THEN the system SHALL connect directly to Deriv API using WebSocket/REST without requiring MT5

2.2 WHEN the bot initializes the trading connection THEN the system SHALL authenticate with Deriv using API token from environment variables

2.3 WHEN the bot receives account credentials (MT5_ACCOUNT, MT5_PASSWORD) THEN the system SHALL use them to derive the Deriv API token or use a separate DERIV_API_TOKEN variable

2.4 WHEN the bot receives a valid trading signal from Telegram THEN the system SHALL execute the trade via Deriv API with the same parameters (symbol, direction, lot size, TP, SL)

2.5 WHEN the bot executes a trade via Deriv API THEN the system SHALL return success/failure status equivalent to MT5's order_send result

2.6 WHEN the bot queries account information THEN the system SHALL retrieve balance, equity, and positions from Deriv API

### Unchanged Behavior (Regression Prevention)

3.1 WHEN the bot receives a message from the Telegram channel THEN the system SHALL CONTINUE TO parse trading signals using the same regex patterns

3.2 WHEN a trading signal is parsed successfully THEN the system SHALL CONTINUE TO extract symbol, direction, entry price, take profits, and stop loss

3.3 WHEN the bot determines order type (MARKET, LIMIT, STOP) THEN the system SHALL CONTINUE TO use the same logic based on current price vs entry price

3.4 WHEN the bot logs events THEN the system SHALL CONTINUE TO write to trading_bot.log with the same format

3.5 WHEN the bot handles multiple TPs THEN the system SHALL CONTINUE TO place the first TP and log additional TPs for manual management

3.6 WHEN the bot receives duplicate messages THEN the system SHALL CONTINUE TO filter them using the processed_messages set

3.7 WHEN the user presses Ctrl+C THEN the system SHALL CONTINUE TO shutdown gracefully and disconnect from services

3.8 WHEN the bot validates configuration THEN the system SHALL CONTINUE TO check for required environment variables before starting
