OptionMaster Backend (Flask) - Railway deploy ready

This backend includes analytics: PCR (volume & OI), Max Pain, Elastic-of-Ends.

Files:
- app.py : Flask API - /api/option-chain?symbol=NIFTY&expiry=...
- requirements.txt
- Procfile
- README.md

Deploy instructions (mobile-friendly):
1. Create new GitHub repo and upload these files.
2. Sign up / login to Railway.app and choose 'Deploy from GitHub' -> select this repo.
3. Railway will build and provide a public URL.
4. Test /health and /api/option-chain endpoints.

Notes:
- Cache TTL is set to 12 seconds. Increase to 30/60 for safer usage.
- This backend scrapes NSE public API; avoid excessive requests to prevent temporary blocks.
