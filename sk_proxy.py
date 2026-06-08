# ============================================================
#  SK TRADERS — Angel One Proxy Backend (CLOUD VERSION)
#  File: sk_proxy.py
#  Deploy: Railway.app
#  URL: https://your-app.railway.app
# ============================================================

from flask import Flask, request, jsonify
from flask_cors import CORS
import pyotp
import json
import os
import time
import datetime
import logging

# ──────────────────────────────────────────
# Try importing SmartAPI (Angel One SDK)
# ──────────────────────────────────────────
try:
    from SmartApi import SmartConnect
    SMARTAPI_AVAILABLE = True
except ImportError:
    SMARTAPI_AVAILABLE = False
    print("⚠  SmartApi not installed. Running in DEMO mode.\n")

# ──────────────────────────────────────────
# CONFIGURATION — Read from Environment Variables (Cloud Safe)
# ──────────────────────────────────────────
CONFIG = {
    "CLIENT_ID"  : os.environ.get("CLIENT_ID",   "G204035"),
    "PIN"        : os.environ.get("MPIN",         ""),
    "TOTP_SECRET": os.environ.get("TOTP_SECRET",  ""),
    "API_KEY"    : os.environ.get("API_KEY",       ""),
    "PORT"       : int(os.environ.get("PORT",      8080)),
    "DEBUG"      : os.environ.get("DEBUG",         "false").lower() == "true"
}

# ──────────────────────────────────────────
# FLASK APP
# ──────────────────────────────────────────
app = Flask(__name__)
CORS(app, origins=["*"])

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [SK-TRADERS] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

# Session state
session = {
    "obj"       : None,
    "token"     : None,
    "feed_token": None,
    "logged_in" : False,
    "last_login": None
}

# Trade log (in-memory)
trade_log = []

# ──────────────────────────────────────────
# ROOT — Health Check
# ──────────────────────────────────────────
@app.route("/", methods=["GET"])
def root():
    return jsonify({
        "status"  : "running",
        "platform": "SK Traders Cloud v1.0",
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
            log.info(f"DEMO LOGIN — Client: {CONFIG['CLIENT_ID']}")
            return jsonify({"status": "success", "message": "Demo login OK", "client": CONFIG["CLIENT_ID"]})

        if not CONFIG["TOTP_SECRET"] or not CONFIG["API_KEY"]:
            return jsonify({"status": "error", "message": "API credentials not configured in environment variables"}), 500

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
            log.error(f"LOGIN FAILED — {data}")
            return jsonify({"status": "error", "message": "Login failed", "detail": data}), 401

    except Exception as e:
        log.error(f"LOGIN ERROR — {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ──────────────────────────────────────────
# STATUS
# ──────────────────────────────────────────
@app.route("/status", methods=["GET"])
def status():
    return jsonify({
        "status"      : "running",
        "platform"    : "SK Traders Cloud v1.0",
        "client_id"   : CONFIG["CLIENT_ID"],
        "logged_in"   : session["logged_in"],
        "last_login"  : session["last_login"],
        "smartapi"    : SMARTAPI_AVAILABLE,
        "timestamp"   : datetime.datetime.now().isoformat()
    })

# ──────────────────────────────────────────
# PLACE ORDER
# ──────────────────────────────────────────
@app.route("/order", methods=["POST"])
def place_order():
    try:
        body = request.get_json()
        required = ["symbol", "token", "exchange", "action", "qty", "order_type", "product"]
        for field in required:
            if field not in body:
                return jsonify({"status": "error", "message": f"Missing field: {field}"}), 400

        log.info(f"ORDER REQUEST — {body['action']} {body['symbol']} x{body['qty']} @ {body.get('price','MARKET')}")

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

        if not SMARTAPI_AVAILABLE or not session["logged_in"]:
            order_id = f"DEMO{int(time.time())}"
            log.info(f"DEMO ORDER — ID: {order_id}")
            _save_trade(body, order_id, "PAPER")
            return jsonify({"status": "success", "message": "Demo order placed",
                            "order_id": order_id, "mode": "PAPER"})

        if not session["obj"]:
            return jsonify({"status": "error", "message": "Not logged in"}), 401

        resp = session["obj"].placeOrder(order_params)
        log.info(f"ORDER PLACED — ID: {resp}")
        _save_trade(body, resp, "LIVE")
        return jsonify({"status": "success", "message": "Order placed", "order_id": resp})

    except Exception as e:
        log.error(f"ORDER ERROR — {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ──────────────────────────────────────────
# ORDER BOOK
# ──────────────────────────────────────────
@app.route("/orders", methods=["GET"])
def get_orders():
    try:
        if not SMARTAPI_AVAILABLE or not session["logged_in"] or not session["obj"]:
            return jsonify({"status": "success", "data": trade_log, "source": "local_log"})

        data = session["obj"].orderBook()
        return jsonify({"status": "success", "data": data.get("data", []), "source": "angel_one"})
    except Exception as e:
        log.error(f"ORDER BOOK ERROR — {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ──────────────────────────────────────────
# POSITIONS
# ──────────────────────────────────────────
@app.route("/positions", methods=["GET"])
def get_positions():
    try:
        if not SMARTAPI_AVAILABLE or not session["obj"]:
            return jsonify({"status": "success", "data": [], "source": "demo"})

        data = session["obj"].position()
        return jsonify({"status": "success", "data": data.get("data", [])})
    except Exception as e:
        log.error(f"POSITIONS ERROR — {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ──────────────────────────────────────────
# PROFILE / BALANCE
# ──────────────────────────────────────────
@app.route("/profile", methods=["GET"])
def get_profile():
    try:
        if not SMARTAPI_AVAILABLE or not session["obj"]:
            return jsonify({"status": "success", "data": {
                "clientcode": CONFIG["CLIENT_ID"], "name": "SK Traders",
                "balance": "20000.00", "mode": "DEMO"
            }})

        profile = session["obj"].getProfile(session["token"])
        rms     = session["obj"].rmsLimit()
        return jsonify({"status": "success",
                        "profile": profile.get("data", {}),
                        "balance": rms.get("data", {})})
    except Exception as e:
        log.error(f"PROFILE ERROR — {e}")
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
            log.info(f"DEMO CANCEL — {order_id}")
            return jsonify({"status": "success", "message": f"Demo cancel: {order_id}"})

        resp = session["obj"].cancelOrder(order_id, variety)
        log.info(f"ORDER CANCELLED — {order_id}")
        return jsonify({"status": "success", "data": resp})
    except Exception as e:
        log.error(f"CANCEL ERROR — {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ──────────────────────────────────────────
# TRADE LOG
# ──────────────────────────────────────────
@app.route("/tradelog", methods=["GET"])
def get_tradelog():
    return jsonify({"status": "success", "data": trade_log, "count": len(trade_log)})

def _save_trade(body, order_id, mode):
    entry = {
        "order_id"  : order_id,
        "time"      : datetime.datetime.now().isoformat(),
        "symbol"    : body.get("symbol"),
        "exchange"  : body.get("exchange"),
        "action"    : body.get("action"),
        "qty"       : body.get("qty"),
        "price"     : body.get("price", "MARKET"),
        "product"   : body.get("product"),
        "order_type": body.get("order_type"),
        "stoploss"  : body.get("stoploss", 0),
        "target"    : body.get("target", 0),
        "mode"      : mode
    }
    trade_log.append(entry)

# ──────────────────────────────────────────
# SIGNAL ENDPOINT
# ──────────────────────────────────────────
@app.route("/signal", methods=["POST"])
def receive_signal():
    try:
        sig = request.get_json()
        log.info(f"SIGNAL — {sig['action']} {sig['symbol']} entry:{sig.get('entry')} sl:{sig.get('sl')} tgt:{sig.get('target')}")
        return jsonify({"status": "success", "message": "Signal received", "signal": sig})
    except Exception as e:
        log.error(f"SIGNAL ERROR — {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ──────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "═"*55)
    print("  SK TRADERS — Cloud Proxy Backend")
    print("  Platform : SK Traders Cloud v1.0")
    print(f"  Client   : {CONFIG['CLIENT_ID']}")
    print(f"  Port     : {CONFIG['PORT']}")
    print(f"  SmartAPI : {'✓ Available' if SMARTAPI_AVAILABLE else '⚠ Demo Mode'}")
    print("═"*55 + "\n")

    app.run(host="0.0.0.0", port=CONFIG["PORT"], debug=CONFIG["DEBUG"])
