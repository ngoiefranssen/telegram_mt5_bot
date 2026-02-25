# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Fault Condition** - MT5 Connection Failure on Linux Without Bridge
  - **CRITICAL**: This test MUST FAIL on unfixed code - failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior - it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists
  - **Scoped PBT Approach**: For deterministic bugs, scope the property to the concrete failing case(s) to ensure reproducibility
  - Test that bot initialization fails on Linux without MT5/RPyC bridge (from Fault Condition in design)
  - The test assertions should match the Expected Behavior Properties from design:
    - Bot should connect directly to Deriv API using WebSocket/REST
    - Bot should authenticate using DERIV_API_TOKEN from environment
    - Bot should be ready to execute trades without MT5 dependency
  - Run test on UNFIXED code (current MT5-based implementation)
  - **EXPECTED OUTCOME**: Test FAILS with connection refused error (this is correct - it proves the bug exists)
  - Document counterexamples found:
    - `[Errno 111] Connection refused` when attempting `mt5.initialize()`
    - RPyC bridge connection timeout on port 18812
    - Bot crashes during startup on Linux VPS
  - Mark task complete when test is written, run, and failure is documented
  - _Requirements: 2.1, 2.2, 2.3_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** - Signal Processing and Logging Unchanged
  - **IMPORTANT**: Follow observation-first methodology
  - Observe behavior on UNFIXED code for non-buggy inputs:
    - Signal parsing with regex patterns for symbol, direction, entry, TPs, SL
    - Order type determination (MARKET vs LIMIT vs STOP based on price difference)
    - Logging format to `trading_bot.log`
    - Duplicate message filtering using `processed_messages` set
    - Configuration validation for required environment variables
  - Write property-based tests capturing observed behavior patterns from Preservation Requirements:
    - Generate random valid signals → Verify parsing produces identical TradingSignal objects
    - Generate random price differences → Verify order type determination follows same rules
    - Capture log output for same events → Verify format unchanged
    - Send duplicate messages → Verify same filtering behavior
    - Test with missing env vars → Verify same validation errors
  - Property-based testing generates many test cases for stronger guarantees
  - Run tests on UNFIXED code
  - **EXPECTED OUTCOME**: Tests PASS (this confirms baseline behavior to preserve)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

- [ ] 3. Migrate from MT5 to Deriv API

  - [x] 3.1 Remove MT5 dependencies and add Deriv API client
    - Remove `import MetaTrader5 as mt5` and `from mt5linux import MetaTrader5`
    - Remove global `mt5` variable and `is_linux_mt5` flag
    - Add Deriv API client library (use `websockets` + `aiohttp` or `deriv-api` package)
    - Install required packages: `pip install websockets aiohttp`
    - _Bug_Condition: isBugCondition(environment) where environment.os == 'Linux' AND NOT mt5_installed_locally AND bot_initialization_attempted_
    - _Expected_Behavior: Bot connects directly to Deriv API using WebSocket/REST, authenticates using DERIV_API_TOKEN, ready to execute trades without MT5_
    - _Preservation: Signal parsing, order type logic, logging format, duplicate filtering, graceful shutdown, configuration validation remain unchanged_
    - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_

  - [x] 3.2 Replace connection logic (_connect_mt5 → _connect_deriv)
    - Rename `_connect_mt5()` to `_connect_deriv()`
    - Replace `mt5.initialize()` with Deriv WebSocket connection to `wss://ws.binaryws.com/websockets/v3?app_id={DERIV_APP_ID}`
    - Replace `mt5.login()` with Deriv API token authentication using `authorize` call
    - Replace `mt5.account_info()` with Deriv `balance` API call
    - Store Deriv API connection object in `self.deriv_api`
    - Handle connection errors with proper logging
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.3 Update configuration and environment variables
    - Add `DERIV_API_TOKEN` to `.env` file (obtain from https://app.deriv.com/account/api-token)
    - Add `DERIV_APP_ID` to `.env` (default: 1089 for binary.com)
    - Update config validation to require `DERIV_API_TOKEN` and `DERIV_APP_ID`
    - Mark `MT5_ACCOUNT`, `MT5_PASSWORD`, `MT5_SERVER` as deprecated (add comments)
    - Keep existing Telegram and trading settings unchanged
    - _Requirements: 2.2, 3.6_

  - [x] 3.4 Replace symbol resolution logic
    - Replace `find_correct_symbol()` with Deriv symbol mapping
    - Map common symbols: `XAUUSD` → `frxAUUSD`, `EURUSD` → `frxEURUSD`, etc.
    - Use Deriv `active_symbols` API call to validate symbols
    - Handle symbol not found errors with proper logging
    - _Requirements: 2.3_

  - [x] 3.5 Replace trade execution logic
    - Replace `execute_trade()` MT5 order logic with Deriv contract purchase
    - Map MT5 order types to Deriv contract types:
      - `ORDER_TYPE_BUY` → `CALL` contract
      - `ORDER_TYPE_SELL` → `PUT` contract
      - `ORDER_TYPE_BUY_LIMIT` → `CALL` with `proposal` for specific entry price
      - `ORDER_TYPE_SELL_LIMIT` → `PUT` with `proposal` for specific entry price
    - Replace `mt5.order_check()` with Deriv `proposal` API call
    - Replace `mt5.order_send()` with Deriv `buy` API call
    - Map TP/SL to Deriv `take_profit` and `stop_loss` parameters
    - Handle multiple TPs (place first TP, log others for manual management)
    - _Requirements: 2.3, 3.3_

  - [x] 3.6 Update error handling for Deriv API
    - Replace MT5 error codes with Deriv API error responses
    - Map `TRADE_RETCODE_DONE` → Deriv `buy` success response
    - Handle Deriv-specific errors:
      - Insufficient balance → Log error and skip trade
      - Invalid symbol → Log error and skip trade
      - Market closed → Log error and retry later
      - Authentication failure → Log error and reconnect
    - Preserve existing error logging format
    - _Requirements: 2.3, 3.4_

  - [x] 3.7 Delete mt5_bridge.py file
    - Remove `mt5_bridge.py` file (no longer needed)
    - Remove any imports or references to `mt5_bridge` in other files
    - _Requirements: 2.1_

  - [x] 3.8 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** - Direct Deriv API Connection
    - **IMPORTANT**: Re-run the SAME test from task 1 - do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - Verify bot successfully initializes on Linux without MT5
    - Verify bot connects to Deriv API using WebSocket
    - Verify bot authenticates using DERIV_API_TOKEN
    - Verify bot is ready to execute trades
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 3.9 Verify preservation tests still pass
    - **Property 2: Preservation** - Signal Processing and Logging Unchanged
    - **IMPORTANT**: Re-run the SAME tests from task 2 - do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Verify signal parsing produces identical results
    - Verify order type determination follows same rules
    - Verify logging format unchanged
    - Verify duplicate filtering behavior unchanged
    - Verify configuration validation unchanged
    - Confirm all tests still pass after fix (no regressions)

- [x] 4. Checkpoint - Ensure all tests pass
  - Run all tests (exploration + preservation)
  - Verify bot can connect to Deriv API on Linux
  - Verify bot can parse signals and execute trades
  - Verify all logging and error handling works correctly
  - Ask the user if questions arise
