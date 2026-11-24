# ⚡ CiviProject_Domotization · Home Energy & Smart Scheduling Engine

An end-to-end ELT data engineering project built on **Snowflake** and **dbt** to settle an age-old household debate with actual numbers: *when should we turn on the water heater, space heaters, and home appliances to stay comfortable while paying as little as possible on the Spanish electricity bill?*

Instead of over-engineering with heavy ML pipelines or paid SaaS orchestrators, this repo combines **daily batch ingestion**, a **3NF-normalized Silver layer**, a **Kimball star schema in Gold**, a **governed Snowflake Semantic View** (connected to a Gemini CLI assistant), and an interactive **Streamlit in Snowflake** 24-hour planner.

---

## 🎯 What Problem Does This Solve?

Under Spain's regulated electricity tariff (**PVPC 2.0TD**), hourly prices swing wildly across three periods (*Valle*, *Llano*, and *Punta*), and next-day hourly prices are published every evening around 20:15 CET. By crossing next-day electricity prices with hourly weather forecasts and indoor room sensor readings (Granada, Spain), this project answers four practical questions:

1. **Smart Electric Water Heater (*Termo Eléctrico*):** Keep hot water available 24/7 by spreading heating cycles across three daily blocks (*Madrugada*, *Mediodía*, *Tarde/Noche*) during the cheapest hours—automatically adding an extra heating hour on cold days (`< 10 °C` outdoor daily average).
2. **Room-by-Room Heating Optimization:** Cross indoor temperature sensors against room comfort thresholds (`dim_habitaciones`) to rank and schedule portable heaters only when a room actually drops below comfort—prioritizing the cheapest hours first.
3. **Flexible Appliance Scheduling:** Find the cheapest consecutive time window (down to exact hours and minutes) for appliances like washing machines, dishwashers, or ovens, comparing *"run it right now"* vs. *"delayed start"*.
4. **Monthly Bill Tracking (MTD):** Track accumulated kWh, ON hours, and projected month-end euro spend (`mart_resumen_mensual_termo`) to compare against the real utility bill.

---

## 🏗️ Architecture & Tech Stack

The project follows a lightweight **Medallion ELT pattern** across isolated `DEV` and `PRO` environments in Snowflake (`DOMO_*` prefix):

* **Data Warehouse & Compute:** Snowflake (`DOMO_WH_DEV`, `DOMO_WH_PRO` on `XSMALL` with 60s auto-suspend).
* **Transformation, Testing & Governance:** dbt (`domotizacion_energia` project) with `dbt_utils` and `Snowflake-Labs/dbt_semantic_view`.
* **Ingestion & CI/CD:** Python (`requests`, `snowflake-connector-python`), GitHub Actions (`daily_ingest_pro.yml` & `backfill_bronze.yml`), and native Snowflake Tasks (`TASK_REPLAY_SENSORES_DAILY`).
* **Consumption & AI Layer:** Streamlit in Snowflake (`app/streamlit_app.py`) + governed natural-language Q&A via Gemini (`app/chat_gemini_semantico.py` querying `SEMANTIC_VIEW(...)`).

### End-to-End Lineage

```mermaid
flowchart LR
    subgraph Sources["External & IoT Sources"]
        REE["REData API<br/>(PVPC Indicator 1001)"]
        OM["Open-Meteo API<br/>(Granada Hourly Forecast)"]
        IOT["Indoor Sensors<br/>(7 Rooms · Replay Pipeline)"]
        SEEDS["dbt Seeds<br/>(Rooms & Devices Catalog)"]
    end

    subgraph Bronze["BRONZE · DOMO_PRO_BRONZE_DB"]
        B1["RAW_APIS.REE_PVPC_RAW<br/>(VARIANT JSON)"]
        B2["RAW_APIS.OPENMETEO_FORECAST_RAW<br/>(VARIANT JSON)"]
        B3["RAW_DOMOTICA.SENSORES_INTERIORES_RAW"]
    end

    subgraph Silver["SILVER · DOMO_*_SILVER_DB (Staging Views + 3NF Tables)"]
        STG["stg_ree__pvpc<br/>stg_openmeteo__prediccion_horaria<br/>stg_domotica__sensores_interiores"]
        SLV["slv_energia__precios_pvpc<br/>slv_clima__prediccion_horaria<br/>slv_domotica__lecturas_sensores<br/>slv_domotica__habitaciones<br/>slv_domotica__dispositivos"]
    end

    subgraph Gold["GOLD · DOMO_*_GOLD_DB (Star Schema & Marts)"]
        CORE["Dimensions: dim_tiempo_horario, dim_habitaciones,<br/>dim_dispositivos, dim_termo<br/>Facts: fct_plan_termo_horario,<br/>fct_plan_dispositivos_horario"]
        MARTS["Marts & Semantic Layer:<br/>mart_panel_termo_24h<br/>mart_resumen_mensual_termo<br/>mart_planificador_dispositivos_24h<br/>sv_plan_termo (Semantic View)"]
    end

    subgraph Apps["Consumption Layer (DOMO_REPORTING_ROLE)"]
        APP["Streamlit 24h Dashboard"]
        AI["Gemini Semantic CLI"]
    end

    REE & OM -->|"GitHub Actions (20:43 CET)<br/>PUT + COPY INTO"| B1 & B2
    IOT -->|"Snowflake Task (20:45 CET)"| B3
    B1 & B2 & B3 --> STG --> SLV
    SEEDS --> SLV
    SLV --> CORE --> MARTS
    MARTS --> APP & AI
