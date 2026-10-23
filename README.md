# Real Exchange Rate (RER) Explorer

This Streamlit app builds a bilateral real exchange rate between any two IMF economies, including the Euro area. It uses monthly IMF CPI and exchange-rate data starting in January 1976 where the IMF has it.

## Definitions

| Symbol | Meaning |
|---|---|
| E1(t), E2(t) | IMF exchange rates: local currency units per 1 USD (period average) |
| **S(t)** | Units of Country 2 currency per 1 unit of Country 1 currency = **E2(t) / E1(t)** |
| P1(t), P2(t) | Monthly CPI (all items, index) of Country 1 and Country 2 |
| **RER(t)** | S(t) × P1(t) / P2(t) |
| **RER\*** | Average of RER(t) over *valid* months in the selected sample |
| **Real Index(t)** | 100 × RER(t) / RER\* |

A valid month is one where E1, E2, P1 and P2 are all available and positive. RER\* is recalculated every time the start or end month changes. Nominal S(t) is plotted in actual currency units and is never normalized.

A rising Real Index means Country 1's currency is appreciating in real terms against Country 2's, so Country 1 goods are getting more expensive relative to Country 2 goods.

## Data source

The data comes from the IMF SDMX 3.0 API at `https://api.imf.org/external/sdmx/3.0`.

| Series | Dataflow | Key |
|---|---|---|
| Monthly CPI | `IMF.STA/CPI` | `{ISO3}.CPI._T.IX.M` |
| Exchange rate | `IMF.STA/ER` | `{ISO3}.XDC_USD.PA_RT.M` |

Requests look like this:
`GET https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.STA/CPI/+/KOR.CPI._T.IX.M`

- **Euro area:** the code is `G163`.
- **United States:** USD per USD is 1 by definition, so no exchange-rate request is sent for `USA`.
- **Response formats:** the app requests SDMX-JSON first and falls back to SDMX-CSV. It accepts period formats such as `2024-M01`, `2024M01` and `2024-01`.
- **Caching:** responses are cached for 6 hours. Failed requests are retried on HTTP 429 and 5xx errors.
- **API key:** the public API needs none. If your network requires a subscription key, set the `IMF_API_KEY` environment variable.

## Features

- **Country selection:** Country 1 and Country 2 can be any IMF member, the Euro area, or a few other IMF-reported economies such as Hong Kong SAR and Macao SAR. Use **"Other IMF code…"** to type any other code.
- **Sample period:** a start/end month slider bounded by the months where RER(t) can be computed. It resets when the country pair changes.
- **Charts:** interactive Plotly charts with three views: **Real**, **Nominal**, or **Both**. *Both* puts the Real Index on the left axis and nominal S(t) on the right. There is an optional log scale for nominal S, which helps with high-inflation currencies.
- **Headline metrics:** RER\*, the latest Real Index, the latest S(t), and the count of valid months versus total months.
- **CSV download:** includes every month in the selected sample, including months with missing inputs, which are flagged `valid_month = False`. Columns:
  `month, country1, country2, E1_<C1>_per_USD, E2_<C2>_per_USD, P1_CPI_<C1>, P2_CPI_<C2>, S_<C2>_per_<C1>, RER, valid_month, RER_star, Real_Index, sample_start, sample_end`
- **Data notes and coverage table:** for each of the four series, shows the first and last month, the number of observations, and the fetch status.

## Installation and running (Python 3.12)

```bash
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

The app opens at `http://localhost:8501`.

## Data caveats

- **Gaps and limited coverage:** many economies don't have monthly data back to 1976. The Euro area aggregate starts in the late 1990s, and some countries publish only quarterly CPI. Months with any missing input appear as gaps in the chart and are excluded from RER\*. If no month has all four inputs, the app says so and shows the coverage table.
- **Redenominations and currency changeovers:** examples include Türkiye in 2005, Venezuela, Zimbabwe, and Euro-area members switching to the euro. These can cause large level jumps in E(t). The app flags any month where a per-USD rate moves more than 5× in one month. For an individual euro member, the euro-area aggregate `G163` is usually the cleaner choice after 1999.
- **CPI base years** differ across countries. This doesn't affect the Real Index, because it is normalized by RER\*. RER(t) itself is only meaningful in relative terms.
- **Network:** the app needs internet access to `api.imf.org`. If the IMF API is down or slow, the coverage table shows the error for each series.

## Files

- `app.py`: the Streamlit application (data fetch, SDMX parsing, calculations, charts, CSV export)
- `requirements.txt`: Python dependencies
- `README.md`: this file
