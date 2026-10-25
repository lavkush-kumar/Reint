
import React, { useEffect, useMemo, useState } from "react";
import {
  LineChart,
  Line,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
  ResponsiveContainer,
} from "recharts";

const API = "";

const number = (value, digits = 1) => {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) {
    return "—";
  }

  return Number(value).toLocaleString("en-GB", {
    maximumFractionDigits: digits,
  });
};

const Card = ({ title, value, subtitle }) => (
  <div className="metric-card">
    <div className="metric-title">{title}</div>
    <div className="metric-value">{value}</div>
    <div className="metric-subtitle">{subtitle || "\u00a0"}</div>
  </div>
);

const ChartBox = ({ title, children }) => (
  <section className="chart-card">
    <h3>{title}</h3>
    <div className="chart-area">
      <ResponsiveContainer width="100%" height="100%">
        {children}
      </ResponsiveContainer>
    </div>
  </section>
);

async function getJson(url) {
  const response = await fetch(url);

  if (!response.ok) {
    let message = `Request failed (${response.status})`;

    try {
      const body = await response.json();
      if (body?.detail) message = body.detail;
    } catch {
      // Keep the default error message if the response is not JSON.
    }

    throw new Error(message);
  }

  return response.json();
}

export default function App() {
  const [date, setDate] = useState("2026-01-15");
  const [dayData, setDayData] = useState(null);
  const [accuracy, setAccuracy] = useState(null);
  const [dayLoading, setDayLoading] = useState(false);
  const [accuracyLoading, setAccuracyLoading] = useState(true);
  const [dayError, setDayError] = useState("");
  const [accuracyError, setAccuracyError] = useState("");

  useEffect(() => {
    let cancelled = false;

    getJson(`${API}/api/accuracy`)
      .then((data) => {
        if (!cancelled) setAccuracy(data);
      })
      .catch((error) => {
        if (!cancelled) setAccuracyError(error.message);
      })
      .finally(() => {
        if (!cancelled) setAccuracyLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    setDayLoading(true);
    setDayError("");
    setDayData(null);

    getJson(`${API}/api/day?date=${encodeURIComponent(date)}`)
      .then((data) => {
        if (!cancelled) setDayData(data);
      })
      .catch((error) => {
        if (!cancelled) setDayError(error.message);
      })
      .finally(() => {
        if (!cancelled) setDayLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [date]);

  const rows = useMemo(() => {
    if (!dayData?.rows) return [];

    return dayData.rows.map((row) => ({
      ...row,
      time: row.t.slice(11, 16),
    }));
  }, [dayData]);

  const averageForecast = useMemo(() => {
    const values = rows
      .map((row) => Number(row.forecast))
      .filter(Number.isFinite);

    if (values.length === 0) return null;

    return values.reduce((sum, value) => sum + value, 0) / values.length;
  }, [rows]);

  const dailyChart = useMemo(
    () =>
      (accuracy?.daily || []).map((item) => ({
        ...item,
        dayLabel: item.day.slice(8, 10),
      })),
    [accuracy]
  );

  return (
    <main className="page">
      <header className="page-header">
        <div>
          <p className="eyebrow">UK ELECTRICITY · WIND ANALYTICS</p>
          <h1>Day-Ahead Wind Forecast Portal</h1>
          <p className="intro">
            Historical forecast selection and accuracy analysis for January 2026.
          </p>
        </div>
        <div className="period-badge">DELIVERY: JAN 2026</div>
      </header>

      <section className="notice">
        <strong>Data and decision rule</strong>
        <p>
          Source: Elexon BMRS FUELHH actual wind generation and WINDFOR
          forecasts. The assumed decision cutoff is 09:00 UK time on the
          day before delivery (D-1). The cutoff is configurable in the
          backend and must be confirmed against the assignment brief.
        </p>
        <p>
          Metrics are calculated only where a matching actual value is
          available. All chart times are shown in UK local time.
        </p>
      </section>

      <section className="selector-row">
        <label htmlFor="delivery-date">Delivery day</label>
        <input
          id="delivery-date"
          type="date"
          min="2026-01-01"
          max="2026-01-31"
          value={date}
          onChange={(event) => setDate(event.target.value)}
        />
        {dayLoading && <span className="muted">Loading day data…</span>}
      </section>

      {dayError && (
        <div className="error-box" role="alert">
          <strong>Could not load daily data.</strong>
          <p>{dayError}</p>
          <p>
            Check that the backend is running and can reach the Elexon API.
          </p>
        </div>
      )}

      {dayData && (
        <>
          <section className="section-heading">
            <div>
              <h2>Daily decision view</h2>
              <p>
                Forecasts selected for {date}, using the D-1 cutoff.
              </p>
            </div>
          </section>

          <section className="metric-grid">
            <Card
              title="Average forecast"
              value={`${number(averageForecast)} MW`}
              subtitle="Mean of selected delivery intervals"
            />
            <Card
              title="Suggested buffer"
              value={`${number(dayData.suggested_buffer_mw)} MW`}
              subtitle="Maximum of zero and January's 90th percentile over-forecast error"
            />
            <Card
              title="Daily MAE"
              value={`${number(dayData.day_metrics?.mae)} MW`}
              subtitle={`${number(dayData.day_metrics?.n, 0)} matched intervals`}
            />
            <Card
              title="Daily bias"
              value={`${number(dayData.day_metrics?.bias)} MW`}
              subtitle="Positive means forecast exceeded actual"
            />
          </section>

          <section className="notice">
            <strong>Selected forecast publication</strong>
            <p>
              Decision cutoff:{" "}
              <strong>{dayData.decision_cutoff || "Unavailable"}</strong>
            </p>
            <p>
              Latest selected publication:{" "}
              <strong>
                {dayData.latest_publish
                  ? new Date(dayData.latest_publish).toLocaleString("en-GB", {
                      dateStyle: "medium",
                      timeStyle: "short",
                      timeZone: "Europe/London",
                    }) + " UK time"
                  : "Unavailable"}
              </strong>
            </p>
          </section>

          <ChartBox title="Selected forecast vs actual generation (MW)">
            <LineChart data={rows}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="time" interval="preserveStartEnd" minTickGap={24} />
              <YAxis />
              <Tooltip />
              <Legend />
              <Line
                type="monotone"
                dataKey="forecast"
                name="Forecast"
                stroke="#0969da"
                dot={false}
                connectNulls={false}
              />
              <Line
                type="monotone"
                dataKey="actual"
                name="Actual"
                stroke="#cf222e"
                dot={false}
                connectNulls={false}
              />
            </LineChart>
          </ChartBox>

          <p className="footnote">
            Error is defined as forecast minus actual. Positive errors indicate
            over-forecasting; negative errors indicate under-forecasting.
            The suggested buffer is an indicative historical error statistic,
            not an automatically validated procurement instruction.
          </p>
        </>
      )}

      <section className="section-heading">
        <div>
          <h2>January accuracy overview</h2>
          <p>Historical evaluation across the selected January delivery intervals.</p>
        </div>
      </section>

      {accuracyLoading && <p className="muted">Loading accuracy metrics…</p>}

      {accuracyError && (
        <div className="error-box" role="alert">
          <strong>Could not load accuracy metrics.</strong>
          <p>{accuracyError}</p>
        </div>
      )}

      {accuracy && (
        <>
          <section className="metric-grid">
            <Card
              title="Mean absolute error"
              value={`${number(accuracy.overall?.mae)} MW`}
              subtitle={`${number(accuracy.overall?.n, 0)} matched intervals`}
            />
            <Card
              title="Root mean squared error"
              value={`${number(accuracy.overall?.rmse)} MW`}
              subtitle="Penalises larger errors more heavily"
            />
            <Card
              title="MAPE"
              value={
                accuracy.overall?.mape_pct == null
                  ? "—"
                  : `${number(accuracy.overall.mape_pct)}%`
              }
              subtitle="Zero actual values excluded"
            />
            <Card
              title="Overall bias"
              value={`${number(accuracy.overall?.bias)} MW`}
              subtitle="Positive means over-forecasting"
            />
          </section>

          <ChartBox title="Daily MAE and bias (MW)">
            <BarChart data={dailyChart}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="dayLabel" />
              <YAxis />
              <Tooltip />
              <Legend />
              <Bar dataKey="mae" name="MAE" fill="#0969da" />
              <Bar dataKey="bias" name="Bias" fill="#bf8700" />
            </BarChart>
          </ChartBox>

          <ChartBox title="MAE by forecast horizon">
            <BarChart data={accuracy.by_horizon || []}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="horizon" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="mae" name="MAE (MW)" fill="#1a7f37" />
            </BarChart>
          </ChartBox>

          <ChartBox title="Bias by delivery hour (UK local time)">
            <BarChart data={accuracy.hourly || []}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="hour" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="bias" name="Bias (MW)" fill="#8250df" />
            </BarChart>
          </ChartBox>
        </>
      )}

      <footer className="footer">
        <p>
          Internal analytical prototype · Historical data only · January 2026
        </p>
      </footer>
    </main>
  );
}
