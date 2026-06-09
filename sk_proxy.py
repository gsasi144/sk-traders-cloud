# ============================================================
#  SK TRADERS — Angel One Proxy Backend (CLOUD VERSION)
#  File: sk_proxy.py
#  Deploy: Railway.app
#  AUTO SESSION REFRESH — re-logins if token expired
# ============================================================

from flask import Flask, request, jsonify
from flask_cors import CORS
import pyotp
import os
import time
import datetime
import logging

try:
    from SmartApi import SmartConnect
    SMARTAPI_AVAILABLE = True
except ImportError:
    SMARTAPI_AVAILABLE = False
    print("SmartApi not installed. Running in DEMO mode.\n")

CONFIG = {
    "CLIENT_ID"  : os.environ.get("CLIENT_ID",   "G204035"),
    "PIN"        : os.environ.get("MPIN",         ""),
    "TOTP_SECRET": os.environ.get("TOTP_SECRET",  ""),
    "API_KEY"    : os.environ.get("API_KEY",       ""),
    "PORT"       : int(os.environ.get("PORT",      8080)),
    "DEBUG"      : os.environ.get("DEBUG",         "false").lower() == "true"
}

app = Flask(__name__)
CORS(app, origins=["*"])

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [SK-TRADERS] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

session = {
    "obj"       : None,
    "token"     : None,
    "feed_token": None,
    "logged_in" : False,
    "last_login": None
}

trade_log = []

# ──────────────────────────────────────────
# AUTO RE-LOGIN FUNCTION
# Called before every order to ensure session is fresh
# ──────────────────────────────────────────
def ensure_session():
    """Check if session is valid, re-login if expired (older than 55 mins)"""
    if not SMARTAPI_AVAILABLE:
        return True

    now = datetime.datetime.now()

    # Check if we need to re-login
    need_login = False
    if not session["logged_in"] or not session["obj"]:
        need_login = True
        log.info("Session not active — logging in...")
    elif session["last_login"]:
        last = datetime.datetime.fromisoformat(session["last_login"])
        age_mins = (now - last).total_seconds() / 60
        if age_mins > 55:  # Refresh every 55 minutes
            need_login = True
            log.info(f"Session age: {age_mins:.1f} mins — refreshing...")

    if not need_login:
        return True

    # Re-login
    try:
        if not CONFIG["TOTP_SECRET"] or not CONFIG["API_KEY"]:
            log.error("Missing API credentials!")
            return False

        totp = pyotp.TOTP(CONFIG["TOTP_SECRET"]).now()
        obj  = SmartConnect(api_key=CONFIG["API_KEY"])
        data = obj.generateSession(CONFIG["CLIENT_ID"], CONFIG["PIN"], totp)

        if data["status"]:
            session["obj"]        = obj
            session["token"]      = data["data"]["jwtToken"]
            session["feed_token"] = obj.getfeedToken()
            session["logged_in"]  = True
            session["last_login"] = now.isoformat()
            log.info(f"AUTO RE-LOGIN OK — Client: {CONFIG['CLIENT_ID']}")
            return True
        else:
            log.error(f"AUTO RE-LOGIN FAILED — {data}")
            return False
    except Exception as e:
        log.error(f"AUTO RE-LOGIN ERROR — {e}")
        return False

# ──────────────────────────────────────────
# ROOT
# ──────────────────────────────────────────
@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "status"  : "running",
        "platform": "SK Traders Cloud v2.0",
        "client"  : CONFIG["CLIENT_ID"],
        "time"    : datetime.datetime.now().isoformat()
    })

# ──────────────────────────────────────────
# LOGIN
# ──────────────────────────────────────────
@app.route("/login", methods=["POST"])
def login():
    try:
        if not SMARTAPI_AVAILABLE:
            session["logged_in"] = True
            session["last_login"] = datetime.datetime.now().isoformat()
            return jsonify({"status": "success", "message": "Demo login OK", "client": CONFIG["CLIENT_ID"]})

        if not CONFIG["TOTP_SECRET"] or not CONFIG["API_KEY"]:
            return jsonify({"status": "error", "message": "API credentials not configured"}), 500

        totp = pyotp.TOTP(CONFIG["TOTP_SECRET"]).now()
        obj  = SmartConnect(api_key=CONFIG["API_KEY"])
        data = obj.generateSession(CONFIG["CLIENT_ID"], CONFIG["PIN"], totp)

        if data["status"]:
            session["obj"]        = obj
            session["token"]      = data["data"]["jwtToken"]
            session["feed_token"] = obj.getfeedToken()
            session["logged_in"]  = True
            session["last_login"] = datetime.datetime.now().isoformat()
            log.info(f"LOGIN OK — Client: {CONFIG['CLIENT_ID']}")
            return jsonify({"status": "success", "message": "Login successful",
                            "client": CONFIG["CLIENT_ID"], "token": session["token"]})
        else:
            return jsonify({"status": "error", "message": "Login failed", "detail": str(data)}), 401

    except Exception as e:
        log.error(f"LOGIN ERROR — {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ──────────────────────────────────────────
# STATUS
# ──────────────────────────────────────────
@app.route("/status", methods=["GET"])
def status():
    # Calculate session age
    age_mins = 0
    if session["last_login"]:
        last = datetime.datetime.fromisoformat(session["last_login"])
        age_mins = (datetime.datetime.now() - last).total_seconds() / 60

    return jsonify({
        "status"      : "running",
        "platform"    : "SK Traders Cloud v2.0",
        "client_id"   : CONFIG["CLIENT_ID"],
        "logged_in"   : session["logged_in"],
        "last_login"  : session["last_login"],
        "session_age_mins": round(age_mins, 1),
        "smartapi"    : SMARTAPI_AVAILABLE,
        "timestamp"   : datetime.datetime.now().isoformat()
    })

# ──────────────────────────────────────────
# PLACE ORDER — with AUTO SESSION REFRESH
# ──────────────────────────────────────────
@app.route("/order", methods=["POST"])
def place_order():
    try:
        body = request.get_json()
        required = ["symbol", "token", "exchange", "action", "qty", "order_type", "product"]
        for field in required:
            if field not in body:
                return jsonify({"status": "error", "message": f"Missing field: {field}"}), 400

        log.info(f"ORDER — {body['action']} {body['symbol']} x{body['qty']} @ {body.get('price','MARKET')}")

        # DEMO mode
        if not SMARTAPI_AVAILABLE:
            order_id = f"DEMO{int(time.time())}"
            _save_trade(body, order_id, "PAPER")
            return jsonify({"status": "success", "message": "Demo order placed",
                            "order_id": order_id, "mode": "PAPER"})

        # AUTO REFRESH SESSION before placing order
        if not ensure_session():
            return jsonify({"status": "error", "message": "Session refresh failed. Try logging in again."}), 401

        order_params = {
            "variety"         : body.get("variety", "NORMAL"),
            "tradingsymbol"   : body["symbol"],
            "symboltoken"     : str(body["token"]),
            "transactiontype" : body["action"].upper(),
            "exchange"        : body["exchange"].upper(),
            "ordertype"       : body["order_type"].upper(),
            "producttype"     : body["product"].upper(),
            "duration"        : body.get("duration", "DAY"),
            "price"           : str(body.get("price", "0")),
            "squareoff"       : str(body.get("target", "0")),
            "stoploss"        : str(body.get("stoploss", "0")),
            "quantity"        : str(body["qty"])
        }

        log.info(f"ORDER PARAMS — {order_params}")
        resp = session["obj"].placeOrder(order_params)
        log.info(f"ORDER RESPONSE — {resp}")
        log.info(f"FULL RESP TYPE — {type(resp)} — {repr(resp)}")

        if resp and str(resp) != 'None':
            _save_trade(body, resp, "LIVE")
            return jsonify({"status": "success", "message": "Order placed",
                            "order_id": resp, "mode": "LIVE"})
        else:
            # Session may have expired mid-request — force re-login and retry once
            log.warning("Order returned None — forcing re-login and retrying...")
            session["last_login"] = None  # Force re-login
            if ensure_session():
                resp2 = session["obj"].placeOrder(order_params)
                log.info(f"RETRY RESPONSE — {resp2}")
                if resp2 and str(resp2) != 'None':
                    _save_trade(body, resp2, "LIVE")
                    return jsonify({"status": "success", "message": "Order placed (retry)",
                                    "order_id": resp2, "mode": "LIVE"})
            return jsonify({"status": "error", "message": "Order returned null ID. Session may be invalid."}), 500

    except Exception as e:
        log.error(f"ORDER ERROR — {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ──────────────────────────────────────────
# ORDER BOOK
# ──────────────────────────────────────────
@app.route("/orders", methods=["GET"])
def get_orders():
    try:
        if not SMARTAPI_AVAILABLE or not session["obj"]:
            return jsonify({"status": "success", "data": trade_log, "source": "local_log"})
        ensure_session()
        data = session["obj"].orderBook()
        return jsonify({"status": "success", "data": data.get("data", []) or [], "source": "angel_one"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ──────────────────────────────────────────
# POSITIONS
# ──────────────────────────────────────────
@app.route("/positions", methods=["GET"])
def get_positions():
    try:
        if not SMARTAPI_AVAILABLE or not session["obj"]:
            return jsonify({"status": "success", "data": [], "source": "demo"})
        ensure_session()
        data = session["obj"].position()
        return jsonify({"status": "success", "data": data.get("data", []) or []})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ──────────────────────────────────────────
# PROFILE / BALANCE
# ──────────────────────────────────────────
@app.route("/profile", methods=["GET"])
def get_profile():
    try:
        if not SMARTAPI_AVAILABLE or not session["obj"]:
            return jsonify({"status": "success", "data": {
                "clientcode": CONFIG["CLIENT_ID"], "balance": "0", "mode": "DEMO"
            }})
        ensure_session()
        rms = session["obj"].rmsLimit()
        return jsonify({"status": "success", "balance": rms.get("data", {})})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ──────────────────────────────────────────
# CANCEL ORDER
# ──────────────────────────────────────────
@app.route("/cancel", methods=["POST"])
def cancel_order():
    try:
        body     = request.get_json()
        order_id = body.get("order_id")
        variety  = body.get("variety", "NORMAL")
        if not SMARTAPI_AVAILABLE or not session["obj"]:
            return jsonify({"status": "success", "message": f"Demo cancel: {order_id}"})
        ensure_session()
        resp = session["obj"].cancelOrder(order_id, variety)
        return jsonify({"status": "success", "data": resp})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ──────────────────────────────────────────
# TRADE LOG
# ──────────────────────────────────────────
@app.route("/tradelog", methods=["GET"])
def get_tradelog():
    return jsonify({"status": "success", "data": trade_log, "count": len(trade_log)})

def _save_trade(body, order_id, mode):
    trade_log.append({
        "order_id"  : order_id,
        "time"      : datetime.datetime.now().isoformat(),
        "symbol"    : body.get("symbol"),
        "exchange"  : body.get("exchange"),
        "action"    : body.get("action"),
        "qty"       : body.get("qty"),
        "price"     : body.get("price", "MARKET"),
        "product"   : body.get("product"),
        "order_type": body.get("order_type"),
        "mode"      : mode
    })

# ──────────────────────────────────────────
# SIGNAL ENDPOINT
# ──────────────────────────────────────────
@app.route("/signal", methods=["POST"])
def receive_signal():
    try:
        sig = request.get_json()
        log.info(f"SIGNAL — {sig.get('action')} {sig.get('symbol')}")
        return jsonify({"status": "success", "message": "Signal received", "signal": sig})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ──────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("  SK TRADERS — Cloud Proxy v2.0")
    print(f"  Client   : {CONFIG['CLIENT_ID']}")
    print(f"  Port     : {CONFIG['PORT']}")
    print(f"  SmartAPI : {'Available' if SMARTAPI_AVAILABLE else 'Demo Mode'}")
    print(f"  Auto Refresh: Every 55 minutes")
    print("=" * 55)
    app.run(host="0.0.0.0", port=CONFIG["PORT"], debug=CONFIG["DEBUG"])
