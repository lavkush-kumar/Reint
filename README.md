# Wind forecast portal (UK day-ahead buying support)

**Live app:** <ADD HEROKU/RENDER URL>  
**AI disclosure:** this project was built with assistance from Claude (Anthropic).

## What it does
1. Shows, for any January 2026 delivery day, the latest WINDFOR wind forecast available at decision time
   (assumption: last forecast published before **09:00 UTC on D-1**, near day-ahead gate closure), against FUELHH actuals.
2. Quantifies accuracy for January: MAE, RMSE, MAPE, bias, 90th-percentile over-forecast (suggested hedge buffer),
   by day and by forecast horizon.

## Files
- `backend/main.py` – FastAPI app: fetches Elexon data (cached in memory), applies the decision-time rule, computes metrics, serves `/api/day?date=` and `/api/accuracy`, and the built React app.
- `backend/requirements.txt` – Python deps.
- `frontend/` – Vite + React + Recharts UI (`src/App.jsx`).
- `Dockerfile` – multi-stage: builds frontend, serves everything via uvicorn. `heroku.yml` – Heroku container deploy.
- `VIDEO_SCRIPT.md` – talking points for the demo video.

## Run
```
docker build -t wind . && docker run -p 8000:8000 wind     # http://localhost:8000
```
Dev: `cd backend && pip install -r requirements.txt && uvicorn main:app --reload` and `cd frontend && npm i && npm run dev`.

## Deploy (Heroku)
`heroku create && heroku stack:set container && git push heroku main`

## Notes / limitations
Wind only, national level, Elexon only. First request takes ~10-30s while data loads. Forecast error is evaluated for the decision-time forecast only; the horizon chart shows how error changes with forecast age.
