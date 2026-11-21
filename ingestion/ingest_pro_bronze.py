import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import snowflake.connector

# Configuración desde variables de entorno (GitHub Secrets / Workflow)
SF_ACCOUNT = os.environ["SNOWFLAKE_ACCOUNT"]
SF_USER = os.environ["SNOWFLAKE_USER"]
SF_PASSWORD = os.environ["SNOWFLAKE_PASSWORD"]

HOME_CITY = os.getenv("HOME_CITY", "Granada")
HOME_LAT = float(os.getenv("HOME_LAT", "37.1773"))
HOME_LON = float(os.getenv("HOME_LON", "-3.5986"))
DAYS_OFFSET = int(os.getenv("DAYS_OFFSET", "0"))  # 0 = hoy, 1 = mañana (tras las 20:30)

DATABASE = "DOMO_PRO_BRONZE_DB"
SCHEMA = "RAW_APIS"
STAGE = f"@{DATABASE}.{SCHEMA}.STG_RAW_APIS"
FILE_FORMAT = f"{DATABASE}.{SCHEMA}.FF_JSON_RAW"


def get_target_date() -> str:
    tz_madrid = ZoneInfo("Europe/Madrid")
    target = datetime.now(tz_madrid) + timedelta(days=DAYS_OFFSET)
    return target.strftime("%Y-%m-%d")


def get_with_retries(url: str, params: dict, headers: dict | None = None, attempts: int = 4) -> dict:
    last_exc = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            if resp.status_code in (500, 502, 503, 504):
                wait = attempt * 15
                print(f"Error HTTP {resp.status_code} en {url} (intento {attempt}/{attempts}). Reintentando en {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_exc = exc
            if attempt == attempts:
                raise
            wait = attempt * 15
            print(f"Timeout/conexión en {url} (intento {attempt}/{attempts}): {exc}. Reintentando en {wait}s...")
            time.sleep(wait)

    if last_exc:
        raise last_exc
    resp.raise_for_status()


def fetch_ree_pvpc(target_date: str) -> dict:
    url = "https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real"
    params = {
        "start_date": f"{target_date}T00:00",
        "end_date": f"{target_date}T23:59",
        "time_trunc": "hour",
    }
    return get_with_retries(url, params=params, headers={"Accept": "application/json"})


def fetch_openmeteo_forecast(lat: float, lon: float, target_date: str) -> dict:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,relative_humidity_2m,precipitation_probability",
        "timezone": "Europe/Madrid",
        "start_date": target_date,
        "end_date": target_date,  # Exactamente las mismas 24h que PVPC
    }
    data = get_with_retries(url, params=params)
    if data.get("error"):
        raise RuntimeError(f"Error en Open-Meteo: {data.get('reason')}")
    return data


def upload_and_copy(cur, payload, filename: str, copy_sql: str):
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

        cur.execute(
            f"PUT 'file://{filepath}' {STAGE} AUTO_COMPRESS=TRUE OVERWRITE=TRUE"
        )
        cur.execute(copy_sql)


def main():
    target_date = get_target_date()
    run_ts = datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y%m%d_%H%M%S")

    print(f"Descargando REData PVPC (24h) para {target_date}...")
    ree_data = fetch_ree_pvpc(target_date)

    print(f"Descargando Open-Meteo (24h) para {HOME_CITY} en {target_date}...")
    meteo_data = fetch_openmeteo_forecast(HOME_LAT, HOME_LON, target_date)

    conn = snowflake.connector.connect(
        account=SF_ACCOUNT,
        user=SF_USER,
        password=SF_PASSWORD,
        role="DOMO_INGEST_ROLE",
        warehouse="DOMO_WH_PRO",
        database=DATABASE,
        schema=SCHEMA,
    )

    try:
        cur = conn.cursor()

        # 1. Cargar REData PVPC
        ree_file = f"ree_pvpc_{target_date}_{run_ts}.json"
        ree_copy_sql = f"""
            COPY INTO {DATABASE}.{SCHEMA}.REE_PVPC_RAW (TARGET_DATE, FILE_NAME, RAW_JSON)
            FROM (
                SELECT
                    TO_DATE('{target_date}'),
                    METADATA$FILENAME,
                    $1
                FROM {STAGE}/{ree_file}.gz
            )
            FILE_FORMAT = (FORMAT_NAME = '{FILE_FORMAT}')
            ON_ERROR = 'ABORT_STATEMENT'
        """
        upload_and_copy(cur, ree_data, ree_file, ree_copy_sql)
        print(f"OK -> Cargado {ree_file} en REE_PVPC_RAW")

        # 2. Cargar Open-Meteo
        meteo_file = f"openmeteo_{HOME_CITY.lower()}_{target_date}_{run_ts}.json"
        meteo_copy_sql = f"""
            COPY INTO {DATABASE}.{SCHEMA}.OPENMETEO_FORECAST_RAW (UBICACION, FILE_NAME, RAW_JSON)
            FROM (
                SELECT
                    '{HOME_CITY}',
                    METADATA$FILENAME,
                    $1
                FROM {STAGE}/{meteo_file}.gz
            )
            FILE_FORMAT = (FORMAT_NAME = '{FILE_FORMAT}')
            ON_ERROR = 'ABORT_STATEMENT'
        """
        upload_and_copy(cur, meteo_data, meteo_file, meteo_copy_sql)
        print(f"OK -> Cargado {meteo_file} en OPENMETEO_FORECAST_RAW")

    finally:
        conn.close()


if __name__ == "__main__":
    main()