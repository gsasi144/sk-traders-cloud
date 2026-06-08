# SK Traders — Cloud Deployment Guide

## Files in this folder:
- `sk_proxy.py` — Main Flask backend (cloud-ready)
- `requirements.txt` — Python packages
- `Procfile` — Railway start command
- `railway.json` — Railway config

## Deploy Steps:

### Step 1: GitHub
1. Go to github.com → Sign up (free)
2. Create new repository → Name: `sk-traders-cloud`
3. Upload all 4 files from this folder

### Step 2: Railway
1. Go to railway.app → Sign up with GitHub
2. Click "New Project" → "Deploy from GitHub repo"
3. Select `sk-traders-cloud`
4. Railway auto-detects Python ✅

### Step 3: Environment Variables (IMPORTANT!)
In Railway dashboard → Variables → Add these:
```
CLIENT_ID   = G204035
MPIN        = your_4digit_mpin
TOTP_SECRET = your_totp_secret_key
API_KEY     = your_angel_one_api_key
```

### Step 4: Get Your Cloud URL
Railway gives you URL like:
`https://sk-traders-cloud.up.railway.app`

### Step 5: Whitelist IP in Angel One
1. Go to smartapi.angelone.in
2. Login → API → Whitelist IP
3. Add Railway's fixed IP (found in Railway dashboard)

## API Endpoints:
- GET  /status    → Check if running
- POST /login     → Login to Angel One
- POST /order     → Place order
- GET  /orders    → Order book
- GET  /positions → Open positions
- GET  /profile   → Account balance
- POST /cancel    → Cancel order
- POST /signal    → Receive trade signal
