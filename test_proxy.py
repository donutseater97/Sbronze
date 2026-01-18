import yfinance as yf
import sys

# Free proxy list (these change frequently, may or may not work)
proxies_to_try = [
    {'http': 'http://proxy.server.com:3128', 'https': 'http://proxy.server.com:3128'},
]

# Try without proxy first
print("[TEST] Attempting without proxy...", file=sys.stderr)
try:
    ticker = yf.Ticker("0P0001CRXW.F")
    df = ticker.history(period="5d")
    if not df.empty:
        print(f"✓ SUCCESS without proxy: {len(df)} rows", file=sys.stderr)
        print(df.head())
        sys.exit(0)
    else:
        print("✗ No data without proxy", file=sys.stderr)
except Exception as e:
    print(f"✗ Error without proxy: {str(e)[:100]}", file=sys.stderr)

# Try with yfinance's built-in proxy parameter
print("\n[TEST] Trying with random user agent...", file=sys.stderr)
try:
    # Use custom session with headers
    import requests
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
    })
    
    ticker = yf.Ticker("0P0001CRXW.F", session=session)
    df = ticker.history(period="5d")
    if not df.empty:
        print(f"✓ SUCCESS with custom user agent: {len(df)} rows", file=sys.stderr)
        print(df.head())
        sys.exit(0)
    else:
        print("✗ No data with custom user agent", file=sys.stderr)
except Exception as e:
    print(f"✗ Error with custom user agent: {str(e)[:100]}", file=sys.stderr)

print("\n[RESULT] All proxy attempts failed. Yahoo Finance is blocking this environment.", file=sys.stderr)
