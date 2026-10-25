# Part 1 – Customer pitch (≤5 min)
1. Problem (30s): you buy day-ahead by ~09:00 D-1; wind is weather-driven; residual demand = demand − wind.
2. Demo (2.5m): pick a day → see the *exact* latest forecast you'd have had at cutoff (publish time shown) vs actual.
3. Trust the number (1.5m): Jan MAE/RMSE/bias, worst days, horizon chart; "hedge buffer" = 90th pct over-forecast → how much thermal to add.
4. Next steps (30s): add demand, solar, price data; alerts when forecast revisions are large.
# Part 2 – Tech review (≤5 min)
1. Architecture: React → FastAPI → Elexon stream APIs; single Docker image; in-memory cache.
2. Key logic (`load()`): chunked WINDFOR fetch, drop forecasts published after cutoff, take latest per target, join actuals, error = forecast − actual.
3. Metrics & endpoints; assumptions (09:00 UTC cutoff, UTC==London in Jan).
4. Practices/gaps: AI-assisted, add tests, persistent cache, CI; configurable cutoff.
