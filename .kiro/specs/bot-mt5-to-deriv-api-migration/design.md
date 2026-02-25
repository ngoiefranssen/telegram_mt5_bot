# Bot MT5 to Deriv API Migration - Bugfix Design

## Overview

This bugfix migrates the trading bot from MetaTrader5 (MT5) bridge architecture to direct Deriv API integration. The current implementation fails on Linux servers because it requires MT5 installed locally or accessible via Wine+RPyC bridge, which is not viable for remote deployment. The fix replaces the MT5 connection layer with Deriv's WebSocket/REST API, enabling the bot to execute trades directly with the Deriv broker without any MT5 dependency.

The migration maintains all existing functionality (signal parsing, trade execution, logging) while replacing only the broker connection and order execution layer. The user's Deriv account (currently accessed via MT5 mobile app) will be accessed directly through Deriv API tokens.

## Glossary

- **Bug_Condition (C)**: The condition that triggers the bug - when the bot starts on a Linux server without MT5 installed or accessible via RPyC bridge
- **Property (P)**: The desired behavior - bot connects directly to Deriv API and executes trades without requiring MT5
- **Preservation**: Existing signal parsing, order type logic, logging, and Telegram integration that must remain unchanged
- **MT5 Bridge**: The current RPyC-based connection to MetaTrader5 running under Wine (file: `mt5_bridge.py`)
- **Deriv API**: WebSocket and REST API provided by Deriv broker for direct trading access
- **API Token**: Authentication credential for Deriv API (replaces MT5_ACCOUNT/MT5_PASSWORD)
- **Contract**: Deriv's term for a trade position (equivalent to MT5 order)
- **Proposal**: Deriv's pre-trade validation mechanism (equivalent to MT5's order_check)

## Bug Details

### Fault Condition

The bug manifests when the bot attempts to start on a Linux server without MetaTrader5 installed or accessible. The `_connect_mt5()` function tries to initialize MT5 via `mt5linux.MetaTrader5()` which requires an RPyC bridge server running on port 18812. When this bridge is unavailable, the connection fails with `[Errno 111] Connection refused`, preventing the bot from initializing and executing any trades.

**Formal Specification:**
```
FUNCTION isBugCondition(environment)
  INPUT: environment of type SystemEnvironment
  OUTPUT: boolean
  
  RETURN environment.os == 'Linux'
         AND (NOT mt5_installed_locally OR NOT rpyc_bridge_running)
         AND bot_initialization_attempted
         AND connection_to_mt5_fails_with_errno_111
END FUNCTION
```

### Examples

- **Example 1**: User deploys bot to Ubuntu VPS → MT5 not installed → `mt5.initialize()` fails → Bot crashes during startup
- **Example 2**: User runs bot on Linux with Wine+MT5 → RPyC bridge not started → Connection refused on port 18812 → Bot cannot authenticate
- **Example 3**: User receives valid trading signal from Telegram → MT5 connection unavailable → `execute_trade()` cannot send order → Trade not executed
- **Edge Case**: Bot running on Windows with MT5 installed locally → Works correctly (not affected by bug)

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- Telegram signal parsing using regex patterns for symbol, direction, entry price, TPs, and SL
- Order type determination logic (MARKET vs LIMIT vs STOP based on current price vs entry price)
- Logging format and output to `trading_bot.log`
- Duplicate message filtering using `processed_messages` set
- Graceful shutdown on Ctrl+C
- Configuration validation for required environment variables
- Multiple TP handling (first TP placed, others logged for manual management)

**Scope:**
All inputs and behaviors that do NOT involve MT5 connection or order execution should be completely unaffected by this fix. This includes:
- Telegram client initialization and message handling
- Signal parsing from text messages
- Configuration loading from `.env` file
- Logging infrastructure
- Error handling for non-MT5 errors

## Hypothesized Root Cause

Based on the bug description and code analysis, the root causes are:

1. **Architecture Dependency**: The bot uses `MetaTrader5` library which requires either:
   - Native Windows MT5 installation (not available on Linux)
   - Wine + MT5 + RPyC bridge (complex, fragile, requires local MT5 instance)

2. **Bridge Connection Failure**: The `mt5linux.MetaTrader5()` initialization attempts to connect to RPyC server on port 18812, which fails when:
   - Bridge server (`mt5_bridge.py`) is not running
   - MT5 is not running under Wine
   - Network/firewall blocks port 18812

3. **Deployment Incompatibility**: The current architecture cannot run on typical VPS/cloud servers because:
   - MT5 requires Windows or Wine (adds complexity)
   - RPyC bridge adds another failure point
   - Cannot scale horizontally (each instance needs MT5)

4. **Authentication Model Mismatch**: The bot uses MT5 credentials (account number, password, server) which are tied to MT5 platform, not directly to Deriv API

## Correctness Properties

Property 1: Fault Condition - Direct Deriv API Connection

_For any_ environment where the bot is deployed on a Linux server without MT5 installed, the fixed bot SHALL successfully initialize by connecting directly to Deriv API using WebSocket/REST, authenticate using DERIV_API_TOKEN from environment variables, and be ready to execute trades without requiring any MT5 installation or RPyC bridge.

**Validates: Requirements 2.1, 2.2, 2.3**

Property 2: Preservation - Signal Processing and Logging

_For any_ trading signal received from Telegram that does NOT involve MT5-specific connection or order execution, the fixed bot SHALL produce exactly the same behavior as the original bot, preserving signal parsing logic, order type determination, logging format, duplicate filtering, and graceful shutdown handling.

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `bot_vps_gram_mt.py`

**Function**: `_connect_mt5()` → Rename to `_connect_deriv()`

**Specific Changes**:

1. **Remove MT5 Dependencies**: 
   - Remove `import MetaTrader5 as mt5` and `from mt5linux import MetaTrader5`
   - Remove global `mt5` variable and `is_linux_mt5` flag
   - Add `import deriv_api` (or use `websockets` + `aiohttp` for direct API calls)

2. **Replace Connection Logic**:
   - Replace `mt5.initialize()` with Deriv WebSocket connection
   - Replace `mt5.login()` with Deriv API token authentication
   - Replace `mt5.account_info()` with Deriv `balance` API call
   - Store Deriv API connection object in `self.deriv_api`

3. **Update Configuration**:
   - Add `DERIV_API_TOKEN` to `.env` file (obtain from https://app.deriv.com/account/api-token)
   - Add `DERIV_APP_ID` to `.env` (default: 1089 for binary.com)
   - Keep existing Telegram and trading settings
   - Mark `MT5_ACCOUNT`, `MT5_PASSWORD`, `MT5_SERVER` as deprecated

4. **Replace Symbol Resolution**:
   - Replace `find_correct_symbol()` with Deriv symbol mapping
   - Map `XAUUSD` → `frxAUUSD` (Deriv forex symbol)
   - Use Deriv `active_symbols` API call to validate symbols

5. **Replace Trade Execution**:
   - Replace `execute_trade()` MT5 order logic with Deriv contract purchase
   - Map MT5 order types to Deriv contract types:
     - `ORDER_TYPE_BUY` → `CALL` contract (for BUY signals)
     - `ORDER_TYPE_SELL` → `PUT` contract (for SELL signals)
     - `ORDER_TYPE_BUY_LIMIT` → `CALL` with `proposal` for specific entry price
     - `ORDER_TYPE_SELL_LIMIT` → `PUT` with `proposal` for specific entry price
   - Replace `mt5.order_check()` with Deriv `proposal` API call
   - Replace `mt5.order_send()` with Deriv `buy` API call
   - Map TP/SL to Deriv `take_profit` and `stop_loss` parameters

6. **Update Error Handling**:
   - Replace MT5 error codes with Deriv API error responses
   - Map `TRADE_RETCODE_DONE` → Deriv `buy` success response
   - Handle Deriv-specific errors (insufficient balance, invalid symbol, market closed)

7. **Preserve Existing Logic**:
   - Keep `parse_signal()` unchanged
   - Keep order type determination logic (MARKET vs LIMIT vs STOP)
   - Keep logging format and handlers
   - Keep Telegram client initialization
   - Keep `processed_messages` duplicate filtering

**File**: `mt5_bridge.py`

**Action**: Delete this file (no longer needed)

**File**: `.env`

**Changes**: Add new variables, deprecate old ones
```
# Deriv API (obtain from https://app.deriv.com/account/api-token)
DERIV_API_TOKEN=your_api_token_here
DERIV_APP_ID=1089  # Default for binary.com

# Deprecated (no longer used)
# MT5_ACCOUNT=32121223
# MT5_PASSWORD="Do!02@_07#.~"
# MT5_SERVER=Deriv-Demo
```

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code (MT5 connection failure on Linux), then verify the fix works correctly (Deriv API connection succeeds) and preserves existing behavior (signal parsing, logging unchanged).

### Exploratory Fault Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm that MT5 connection fails on Linux without Wine+RPyC bridge.

**Test Plan**: Attempt to run the unfixed bot on a Linux server without MT5 installed. Observe the connection failure and error messages. Document the exact failure point and error codes.

**Test Cases**:
1. **Linux Without MT5**: Run bot on Ubuntu VPS → Observe `[Errno 111] Connection refused` during `mt5.initialize()` (will fail on unfixed code)
2. **Linux With Wine But No Bridge**: Run bot with Wine+MT5 but without `mt5_bridge.py` running → Observe RPyC connection timeout (will fail on unfixed code)
3. **Windows With MT5**: Run bot on Windows with MT5 installed → Observe successful connection (will succeed on unfixed code, proving bug is Linux-specific)
4. **Network Port Check**: Check if port 18812 is listening → Observe no listener when bridge not running (will fail on unfixed code)

**Expected Counterexamples**:
- Bot crashes during initialization with connection refused error
- Possible causes: MT5 not installed, RPyC bridge not running, Wine not configured, port 18812 blocked

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds (Linux deployment without MT5), the fixed function produces the expected behavior (successful Deriv API connection).

**Pseudocode:**
```
FOR ALL environment WHERE isBugCondition(environment) DO
  result := bot_initialize_fixed(environment)
  ASSERT result.connected == True
  ASSERT result.api_type == "Deriv"
  ASSERT result.balance > 0
  ASSERT result.can_execute_trades == True
END FOR
```

**Test Cases**:
1. **Linux VPS Deployment**: Deploy fixed bot to Ubuntu VPS → Verify Deriv API connection succeeds
2. **Docker Container**: Run fixed bot in Docker container → Verify no MT5 dependency required
3. **Multiple Instances**: Run multiple bot instances on same server → Verify each connects independently to Deriv API
4. **API Token Authentication**: Test with valid/invalid tokens → Verify proper authentication handling

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold (signal parsing, logging, Telegram integration), the fixed function produces the same result as the original function.

**Pseudocode:**
```
FOR ALL signal_text WHERE is_valid_telegram_message(signal_text) DO
  parsed_original := parse_signal_original(signal_text)
  parsed_fixed := parse_signal_fixed(signal_text)
  ASSERT parsed_original == parsed_fixed
END FOR

FOR ALL log_event WHERE is_loggable_event(log_event) DO
  log_original := format_log_original(log_event)
  log_fixed := format_log_fixed(log_event)
  ASSERT log_original == log_fixed
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many test cases automatically across the input domain
- It catches edge cases that manual unit tests might miss
- It provides strong guarantees that behavior is unchanged for all non-buggy inputs

**Test Plan**: Observe behavior on UNFIXED code first for signal parsing and logging, then write property-based tests capturing that behavior.

**Test Cases**:
1. **Signal Parsing Preservation**: Generate 100 random valid signals → Verify parsing produces identical results
2. **Order Type Logic Preservation**: Test MARKET/LIMIT/STOP determination with various price differences → Verify same logic applied
3. **Logging Format Preservation**: Capture log output for same events → Verify format unchanged
4. **Duplicate Filtering Preservation**: Send duplicate messages → Verify same filtering behavior
5. **Configuration Validation Preservation**: Test with missing env vars → Verify same validation errors

### Unit Tests

- Test Deriv API connection with valid/invalid tokens
- Test symbol mapping (XAUUSD → frxAUUSD)
- Test contract type mapping (BUY → CALL, SELL → PUT)
- Test proposal creation for different order types
- Test error handling for Deriv API errors
- Test signal parsing with various formats (unchanged from original)
- Test order type determination logic (unchanged from original)

### Property-Based Tests

- Generate random trading signals → Verify parsing produces valid TradingSignal objects
- Generate random price differences → Verify order type determination follows same rules
- Generate random Deriv API responses → Verify error handling is robust
- Generate random account balances → Verify trade execution respects balance limits

### Integration Tests

- Test full flow: Telegram signal → Parse → Deriv API execution → Success logging
- Test error flow: Invalid signal → Parse failure → Error logging
- Test network failure: Deriv API timeout → Retry logic → Error handling
- Test multiple TPs: Signal with 3 TPs → First TP placed → Others logged
- Test graceful shutdown: Ctrl+C → Deriv API disconnect → Clean exit
