import json
import os
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import snowflake.connector

TZ_MADRID = ZoneInfo("Europe/Madrid")

HOME_CITY = os.environ.get("HOME_CITY", "Granada")
HOME_LAT = float(os.environ.get("HOME_LAT", "37.1773"))
HOME_LON = float(os.environ.get("HOME_LON", "-3.5986"))

TARGET_ENV = os.environ.get("TARGET_ENV", "PRO").upper()
SNOWFLAKE_DB = f"DOMO_{TARGET_ENV}_BRONZE_DB"
SNOWFLAKE_WH = f"DOMO_WH_{TARGET_ENV}"
SNOWFLAKE_SCHEMA = "RAW_APIS"
STAGE_NAME = f"@{SNOWFLAKE_DB}.{SNOWFLAKE_SCHEMA}.STG_RAW_APIS"
FILE_FORMAT = f"{SNOWFLAKE_DB}.{SNOWFLAKE_SCHEMA}.FF_JSON_RAW"


def parse_date_range() -> tuple[date, date]:
    today_madrid = datetime.now(TZ_MADRID).date()
    start_str = os.environ.get("START_DATE", f"{today_madrid.year}-{today_madrid.month:02d}-01").strip()
    end_str = os.environ.get("END_DATE", "").strip()

    start_dt = date.fromisoformat(start_str)
    end_dt = date.fromisoformat(end_str) if end_str else today_madrid

    if start_dt > end_dt:
        raise ValueError(f"START_DATE ({start_dt}) no puede ser posterior a END_DATE ({end_dt}).")
    return start_dt, end_dt


def get_with_retries(url: str, params: dict, headers: dict | None = None, max_attempts: int = 4) -> dict:
    for attempt in range(1, max_attempts + 1):
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts:
            wait_s = 15 * attempt
            print(f"[WARN] HTTP {resp.status_code} en {url}. Reintentando en {wait_s}s ({attempt}/{max_attempts})...")
            time.sleep(wait_s)
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"Error persistente consultando {url}")


def fetch_ree_pvpc(target_date: str) -> dict:
    url = "https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real"
    params = {
        "start_date": f"{target_date}T00:00",
        "end_date": f"{target_date}T23:59",
        "time_trunc": "hour",
    }
    return get_with_retries(url, params=params, headers={"Accept": "application/json"})


def fetch_openmeteo_range(lat: float, lon: float, start_date: str, end_date: str) -> dict:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,relative_humidity_2m,precipitation_probability",
        "timezone": "Europe/Madrid",
        "start_date": start_date,
        "end_date": end_date,
    }
    data = get_with_retries(url, params=params)
    if data.get("error"):
        raise RuntimeError(f"Open-Meteo devolvió error: {data.get('reason')}")
    return data


def put_file_to_stage(cur, payload: dict, tmpdir: str, filename: str, subdir: str) -> str:
    local_file = Path(tmpdir) / filename
    local_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    cur.execute(
        f"PUT file://{local_file.as_posix()} {STAGE_NAME}/{subdir}/ "
        "AUTO_COMPRESS=TRUE OVERWRITE=TRUE"
    )
    return f"{STAGE_NAME}/{subdir}/{filename}.gz"


def run_backfill() -> None:
    start_dt, end_dt = parse_date_range()
    print(f"Iniciando backfill en {SNOWFLAKE_DB} ({SNOWFLAKE_WH}) desde {start_dt} hasta {end_dt}...")

    # Descargamos Open-Meteo primero para fallar rápido sin encender el warehouse si hubiera problema de red
    meteo_data = fetch_openmeteo_range(HOME_LAT, HOME_LON, start_dt.isoformat(), end_dt.isoformat())

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role="DOMO_INGEST_ROLE",
        warehouse=SNOWFLAKE_WH,
        database=SNOWFLAKE_DB,
        schema=SNOWFLAKE_SCHEMA,
    )

    try:
        cur = conn.cursor()
        with tempfile.TemporaryDirectory() as tmpdir:
            # 1. Backfill REData día a día (1 fila por TARGET_DATE)
            current = start_dt
            while current <= end_dt:
                d_str = current.isoformat()
                ree_data = fetch_ree_pvpc(d_str)
                staged_path = put_file_to_stage(
                    cur, ree_data, tmpdir, f"ree_pvpc_{d_str}.json", subdir="ree"
                )
                cur.execute(
                    f"""
                    COPY INTO {SNOWFLAKE_DB}.{SNOWFLAKE_SCHEMA}.REE_PVPC_RAW
                        (INGESTED_AT, TARGET_DATE, FILE_NAME, RAW_JSON)
                    FROM (
                        SELECT CURRENT_TIMESTAMP(), TO_DATE('{d_str}'), METADATA$FILENAME, $1
                        FROM {staged_path}
                    )
                    FILE_FORMAT = (FORMAT_NAME = {FILE_FORMAT})
                    ON_ERROR = 'ABORT_STATEMENT'
                    """
                )
                print(f"[OK] REData cargado: {d_str}")
                current += timedelta(days=1)
                time.sleep(0.5)

            # 2. Backfill Open-Meteo completo en 1 JSON (misma estructura hourly que la ingesta diaria)
            meteo_filename = f"openmeteo_{HOME_CITY.lower()}_backfill_{start_dt}_{end_dt}.json"
            staged_meteo = put_file_to_stage(
                cur, meteo_data, tmpdir, meteo_filename, subdir="openmeteo"
            )
            cur.execute(
                f"""
                COPY INTO {SNOWFLAKE_DB}.{SNOWFLAKE_SCHEMA}.OPENMETEO_FORECAST_RAW
                    (INGESTED_AT, UBICACION, FILE_NAME, RAW_JSON)
                FROM (
                    SELECT CURRENT_TIMESTAMP(), '{HOME_CITY}', METADATA$FILENAME, $1
                    FROM {staged_meteo}
                )
                FILE_FORMAT = (FORMAT_NAME = {FILE_FORMAT})
                ON_ERROR = 'ABORT_STATEMENT'
                """
            )
            print(f"[OK] Open-Meteo cargado: {start_dt} -> {end_dt}")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run_backfill()