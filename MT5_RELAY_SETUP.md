# Setup Option 2: Render Bot + MT5 Relay VPS

## 1) Deploy MT5 relay on VPS (Windows + MT5 terminal)

Install relay dependencies on VPS:

```bash
pip install -r requirements_mt5_relay.txt
```

Create `.env` on VPS for relay:

```env
MT5_RELAY_API_KEY=replace_with_long_random_secret
MT5_LOGIN=12345678
MT5_PASSWORD=your_mt5_password
MT5_SERVER=YourBroker-Server
RELAY_HOST=0.0.0.0
RELAY_PORT=9000
MT5_DEVIATION=20
MT5_MAGIC_NUMBER=234000
```

Run relay on VPS:

```bash
python mt5_relay_server.py
```

Test health endpoint from VPS:

```bash
curl http://127.0.0.1:9000/health
```

## 2) Configure Render bot

Set these env vars in Render:

```env
EXECUTION_BACKEND=mt5_relay
MT5_RELAY_URL=https://your-vps-domain-or-ip:9000
MT5_RELAY_API_KEY=replace_with_long_random_secret
MT5_RELAY_TIMEOUT_SECONDS=20
```

Optional symbol mapping if broker symbols have suffixes:

```env
MT5_SYMBOL_MAP=XAUUSD:XAUUSDm,EURUSD:EURUSDm,GBPUSD:GBPUSDm
```

The bot keeps your current signal logic:
- ignores entry for trigger logic
- opens 2 trades
- uses TP4 only
- applies the same SL to both trades

## 3) Security recommendations

- Use HTTPS between Render and VPS (reverse proxy recommended).
- Restrict VPS firewall to Render egress IPs or trusted IPs.
- Keep `MT5_RELAY_API_KEY` private and rotate if exposed.
- Do not expose relay publicly without auth.
