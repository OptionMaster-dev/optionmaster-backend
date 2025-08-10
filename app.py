# app.py - OptionMaster backend with analytics (PCR, MaxPain, Elastic of Ends)
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests, time, json
from datetime import datetime
from functools import wraps

app = Flask(__name__)
CORS(app)

NSE_BASE = "https://www.nseindia.com"
NSE_API_INDICES = "https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
HEADERS = {
    "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Accept-Language":"en-US,en;q=0.9"
}

CACHE = {}
CACHE_TTL = 12  # seconds
LAST_FETCH = 0.0
MIN_FETCH_INTERVAL = 1.5  # seconds between actual NSE hits

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

def fetch_nse(symbol):
    global LAST_FETCH
    if time.time() - LAST_FETCH < MIN_FETCH_INTERVAL:
        time.sleep(max(0, MIN_FETCH_INTERVAL - (time.time() - LAST_FETCH)))
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
        ce_min = None
        pe_min = None
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
    rows = sorted(rows, key=lambda x: (x["strike"] if x["strike"] is not None else 0))
    payload = {
        "instrument": request.args.get("symbol","NIFTY"),
        "expiryDates": expiryDates,
        "expiry": expiry_filter or (expiryDates[0] if expiryDates else None),
        "underlying": underlying,
        "data": rows,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }
    return payload

def compute_pcr(rows):
    # PCR by volume and by OI
    total_put_vol = sum((r["pe"]["volume"] or 0) for r in rows if r.get("pe"))
    total_call_vol = sum((r["ce"]["volume"] or 0) for r in rows if r.get("ce"))
    vol_pcr = None
    if total_call_vol > 0:
        vol_pcr = round(total_put_vol / total_call_vol, 4)
    total_put_oi = sum((r["pe"]["oi"] or 0) for r in rows if r.get("pe"))
    total_call_oi = sum((r["ce"]["oi"] or 0) for r in rows if r.get("ce"))
    oi_pcr = None
    if total_call_oi > 0:
        oi_pcr = round(total_put_oi / total_call_oi, 4)
    return {"vol_pcr": vol_pcr, "oi_pcr": oi_pcr, "total_put_vol": total_put_vol, "total_call_vol": total_call_vol, "total_put_oi": total_put_oi, "total_call_oi": total_call_oi}

def compute_max_pain(rows):
    # approximate max pain: consider settlement at each strike and compute total intrinsic * OI cost
    strikes = [r["strike"] for r in rows if r["strike"] is not None]
    ce_map = {r["strike"]: (r["ce"]["oi"] if r.get("ce") else 0) for r in rows}
    pe_map = {r["strike"]: (r["pe"]["oi"] if r.get("pe") else 0) for r in rows}
    min_pain = None
    best_strike = None
    for s in strikes:
        pain = 0
        for k in strikes:
            # call intrinsic if settlement > strike k: max(0, S - K) * CE_OI(K)
            call_intrinsic = max(0, s - k)
            put_intrinsic = max(0, k - s)
            pain += call_intrinsic * (ce_map.get(k,0))
            pain += put_intrinsic * (pe_map.get(k,0))
        if min_pain is None or pain < min_pain:
            min_pain = pain
            best_strike = s
    return {"max_pain_strike": best_strike, "max_pain_value": int(min_pain) if min_pain is not None else None}

def compute_elastic(rows):
    # Elastic of ends: strike where abs(ce.changeOi)+abs(pe.changeOi) is max
    max_score = -1
    best_strike = None
    details = []
    for r in rows:
        ce_change = abs(r.get("ce",{}).get("changeOi") or 0)
        pe_change = abs(r.get("pe",{}).get("changeOi") or 0)
        score = ce_change + pe_change
        details.append({"strike": r["strike"], "ce_change": ce_change, "pe_change": pe_change, "score": score})
        if score > max_score:
            max_score = score
            best_strike = r["strike"]
    return {"elastic_strike": best_strike, "elastic_score": int(max_score), "details": details}

@app.route("/api/option-chain")
@cached()
def api_option_chain():
    symbol = request.args.get("symbol", "NIFTY").upper()
    expiry = request.args.get("expiry", None)
    try:
        raw = fetch_nse(symbol)
        payload = transform(raw, expiry_filter=expiry)
        rows = payload["data"]
        analytics = {}
        analytics.update(compute_pcr(rows))
        analytics.update(compute_max_pain(rows))
        analytics.update(compute_elastic(rows))
        return jsonify({"ok": True, "payload": payload, "analytics": analytics})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat() + "Z"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
