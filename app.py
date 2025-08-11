from flask import Flask, request, jsonify
from flask_cors import CORS
import requests, time, json
from datetime import datetime, time as dtime, timedelta
from functools import wraps

app = Flask(__name__)
CORS(app)

NSE_BASE = "https://www.nseindia.com"
NSE_API_INDICES = "https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept-Language": "en-US,en;q=0.9"
}

CACHE = {}
CACHE_TTL = 12  # seconds
LAST_FETCH = 0.0
MIN_FETCH_INTERVAL = 1.0  # seconds

def cached(ttl=CACHE_TTL):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            key = f.__name__ + json.dumps(request.args, sort_keys=True)
            now = time.time()
            if key in CACHE:
                ts, val = CACHE[key]
                if now - ts < ttl:
                    return val
            val = f(*args, **kwargs)
            CACHE[key] = (now, val)
            return val
        return wrapper
    return decorator

def is_market_time():
    tz = None
    try:
        import pytz
        tz = pytz.timezone("Asia/Kolkata")
    except:
        pass
    now = datetime.now(tz) if tz else datetime.utcnow() + timedelta(hours=5, minutes=30)
    start = dtime(hour=9, minute=15)
    end = dtime(hour=15, minute=30)
    return start <= now.time() <= end

def fetch_nse(symbol):
    global LAST_FETCH
    if time.time() - LAST_FETCH < MIN_FETCH_INTERVAL:
        time.sleep(MIN_FETCH_INTERVAL - (time.time() - LAST_FETCH))
    s = requests.Session()
    s.get(NSE_BASE, headers=HEADERS, timeout=8)
    url = NSE_API_INDICES.format(symbol=symbol)
    resp = s.get(url, headers=HEADERS, timeout=10)
    resp.raise_for_status()
    LAST_FETCH = time.time()
    return resp.json()

def transform(rjson, expiry_filter=None):
    records = rjson.get("records", {})
    data = records.get("data", [])
    expiryDates = records.get("expiryDates", [])
    underlying = records.get("underlyingValue", None)
    rows = []
    for item in data:
        strike = item.get("strikePrice")
        e = item.get("expiryDate")
        if expiry_filter and str(e).strip() != str(expiry_filter).strip():
            continue
        ce = item.get("CE")
        pe = item.get("PE")
        ce_min = pe_min = None
        if ce:
            ce_min = {
                "oi": int(ce.get("openInterest") or 0),
                "changeOi": int(ce.get("changeinOpenInterest") or 0),
                "iv": float(ce.get("impliedVolatility") or 0.0),
                "ltp": float(ce.get("lastPrice") or 0.0),
                "volume": int(ce.get("totalTradedVolume") or 0)
            }
        if pe:
            pe_min = {
                "oi": int(pe.get("openInterest") or 0),
                "changeOi": int(pe.get("changeinOpenInterest") or 0),
                "iv": float(pe.get("impliedVolatility") or 0.0),
                "ltp": float(pe.get("lastPrice") or 0.0),
                "volume": int(pe.get("totalTradedVolume") or 0)
            }
        rows.append({"strike": strike, "expiry": e, "ce": ce_min, "pe": pe_min})
    rows = sorted(rows, key=lambda x: x["strike"] or 0)
    payload = {
        "instrument": request.args.get("symbol", "NIFTY"),
        "expiryDates": expiryDates,
        "expiry": expiry_filter or (expiryDates[0] if expiryDates else None),
        "underlying": underlying,
        "data": rows,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    return payload

@app.route("/api/option-chain")
@cached()
def api_option_chain():
    symbol = request.args.get("symbol", "NIFTY").upper()
    expiry = request.args.get("expiry", None)
    try:
        if not is_market_time():
            return jsonify({"ok": False, "market_status": "closed", "next_open": "09:15 IST"})
        raw = fetch_nse(symbol)
        payload = transform(raw, expiry_filter=expiry)
        return jsonify({"ok": True, "payload": payload})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat() + "Z"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

