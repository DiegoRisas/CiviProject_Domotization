USE ROLE DOMO_INGEST_ROLE;
USE WAREHOUSE DOMO_WH_DEV;
USE DATABASE DOMO_DEV_BRONZE_DB;
USE SCHEMA RAW_DOMOTICA;

-- Parseamos en DEV para inspeccionar sensores disponibles
CREATE OR REPLACE TABLE KAGGLE_POOL_DEV_TMP AS
WITH lineas_insert AS (
    SELECT
        REGEXP_REPLACE(
            REGEXP_REPLACE(RAW_SQL_LINE, '^INSERT INTO `stats` VALUES \\(', ''),
            '\\);\\s*$', ''
        ) AS cuerpo_tuplas
    FROM KAGGLE_SQL_DUMP_RAW
    WHERE RAW_SQL_LINE LIKE 'INSERT INTO `stats`%'
),
tuplas AS (
    SELECT f.value::VARCHAR AS tupla
    FROM lineas_insert,
    LATERAL FLATTEN(input => SPLIT(cuerpo_tuplas, '),(')) f
)
SELECT
    REGEXP_SUBSTR(tupla, '^''([^'']+)''', 1, 1, 'e', 1)::VARCHAR(50)        AS SENSOR,
    REGEXP_SUBSTR(tupla, ',''([^'']+)''', 1, 1, 'e', 1)::TIMESTAMP_NTZ      AS FECHA_HORA_ORIGINAL,
    REGEXP_SUBSTR(tupla, ',([+-]?[0-9]+\\.?[0-9]*)$', 1, 1, 'e', 1)::FLOAT   AS VALOR
FROM tuplas;

-- Ver lista de sensores, volumen y fechas
SELECT
    SENSOR,
    COUNT(*) AS LECTURAS,
    MIN(FECHA_HORA_ORIGINAL) AS DESDE,
    MAX(FECHA_HORA_ORIGINAL) AS HASTA
FROM KAGGLE_POOL_DEV_TMP
GROUP BY SENSOR
ORDER BY SENSOR;

//-----------------------------------------------------------------------------------------
//Paso a bronze pro de source of truth , solo lo necesario, los sensores interiores.

USE ROLE DOMO_INGEST_ROLE;
USE WAREHOUSE DOMO_WH_PRO;
USE DATABASE DOMO_PRO_BRONZE_DB;

CREATE SCHEMA IF NOT EXISTS RAW_DOMOTICA;

-- 1. Almacén limpio en PRO solo con los 7 sensores interiores seleccionados
CREATE OR REPLACE TABLE RAW_DOMOTICA.KAGGLE_POOL_HISTORICO AS
SELECT
    SENSOR,
    FECHA_HORA_ORIGINAL,
    VALOR
FROM DOMO_DEV_BRONZE_DB.RAW_DOMOTICA.KAGGLE_POOL_DEV_TMP
WHERE SENSOR IN (
    'T_bathroom',
    'T_bedroom1',
    'T_bedroom2',
    'T_bedroom3',
    'T_desk',
    'T_kitchen',
    'T_living'
);

-- 2. Tabla Bronze "viva" (Source of Truth para dbt con source freshness)
CREATE TABLE IF NOT EXISTS RAW_DOMOTICA.SENSORES_KAGGLE_RAW (
    INGESTED_AT         TIMESTAMP_TZ DEFAULT CURRENT_TIMESTAMP(),
    SENSOR              VARCHAR(50),
    FECHA_HORA_ORIGINAL TIMESTAMP_NTZ,
    FECHA_HORA_SIMULADA TIMESTAMP_NTZ,
    VALOR               FLOAT
);