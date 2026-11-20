import json
import os
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import snowflake.connector

# Configuración desde variables de entorno (GitHub Secrets / Workflow)
SF_ACCOUNT = os.environ["SNOWFLAKE_ACCOUNT"]
SF_USER = os.environ["SNOWFLAKE_USER"]
SF_PASSWORD = os.environ["SNOWFLAKE_PASSWORD"]
AEMET_API_KEY = os.environ["AEMET_API_KEY"]

MUNICIPIO_INE = os.getenv("AEMET_MUNICIPIO_INE", "18087")  # 18087 = Granada
DAYS_OFFSET = int(os.getenv("DAYS_OFFSET", "0"))  # 0 = hoy, 1 = mañana (tras las 20:30)

DATABASE = "DOMO_PRO_BRONZE_DB"
SCHEMA = "RAW_APIS"
STAGE = f"@{DATABASE}.{SCHEMA}.STG_RAW_APIS"
FILE_FORMAT = f"{DATABASE}.{SCHEMA}.FF_JSON_RAW"


def get_target_date() -> str:
    tz_madrid = ZoneInfo("Europe/Madrid")
    target = datetime.now(tz_madrid) + timedelta(days=DAYS_OFFSET)
    return target.strftime("%Y-%m-%d")


def fetch_ree_pvpc(target_date: str) -> dict:
    url = "https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real"
    params = {
        "start_date": f"{target_date}T00:00",
        "end_date": f"{target_date}T23:59",
        "time_trunc": "hour",
    }
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_aemet_forecast(municipio: str) -> list:
    url = f"https://opendata.aemet.es/opendata/api/prediccion/especifica/municipio/horaria/{municipio}"
    headers = {"api_key": AEMET_API_KEY}

    # Paso 1: obtener URL temporal de datos
    resp_meta = requests.get(url, headers=headers, timeout=30)
    resp_meta.raise_for_status()
    meta = resp_meta.json()
    if meta.get("estado") != 200 or "datos" not in meta:
        raise RuntimeError(f"Error en AEMET paso 1: {meta}")

    # Paso 2: descargar JSON real (viene en ISO-8859-15)
    resp_data = requests.get(meta["datos"], timeout=30)
    resp_data.raise_for_status()
    resp_data.encoding = "iso-8859-15"
    return resp_data.json()


def upload_and_copy(cur, payload, filename: str, copy_sql: str):
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

        # Subir al stage interno (Snowflake lo comprime a .gz)
        cur.execute(
            f"PUT 'file://{filepath}' {STAGE} AUTO_COMPRESS=TRUE OVERWRITE=TRUE"
        )
        # Cargar en tabla Bronze
        cur.execute(copy_sql)


def main():
    target_date = get_target_date()
    run_ts = datetime.now(ZoneInfo("Europe/Madrid")).strftime("%Y%m%d_%H%M%S")

    print(f"Descargando REData PVPC para {target_date}...")
    ree_data = fetch_ree_pvpc(target_date)

    print(f"Descargando AEMET horaria para municipio {MUNICIPIO_INE}...")
    aemet_data = fetch_aemet_forecast(MUNICIPIO_INE)

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

        # 2. Cargar AEMET
        aemet_file = f"aemet_{MUNICIPIO_INE}_{run_ts}.json"
        aemet_copy_sql = f"""
            COPY INTO {DATABASE}.{SCHEMA}.AEMET_FORECAST_RAW (MUNICIPIO, FILE_NAME, RAW_JSON)
            FROM (
                SELECT
                    '{MUNICIPIO_INE}',
                    METADATA$FILENAME,
                    $1
                FROM {STAGE}/{aemet_file}.gz
            )
            FILE_FORMAT = (FORMAT_NAME = '{FILE_FORMAT}')
            ON_ERROR = 'ABORT_STATEMENT'
        """
        upload_and_copy(cur, aemet_data, aemet_file, aemet_copy_sql)
        print(f"OK -> Cargado {aemet_file} en AEMET_FORECAST_RAW")

    finally:
        conn.close()


if __name__ == "__main__":
    main()