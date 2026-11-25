USE ROLE sysadmin;
USE WAREHOUSE DOMO_WH_PRO;

SELECT
    fecha,
    hora,
    tramo_pvpc,
    bloque_dia,
    precio_eur_kwh,
    temperatura_ext_c,
    estado_termo,
    color_semaforo,
    coste_estimado_eur,
    coste_total_dia_eur,
    total_horas_on_dia
FROM DOMO_dev_GOLD_DB.ENERGIA.MART_PANEL_TERMO_24H
WHERE fecha = (SELECT (MAX(fecha) - 2) FROM DOMO_DEV_GOLD_DB.ENERGIA.MART_PANEL_TERMO_24H)
ORDER BY hora;



GRANT CREATE STREAMLIT ON SCHEMA DOMO_PRO_GOLD_DB.ENERGIA TO ROLE DOMO_REPORTING_ROLE;
GRANT CREATE STAGE ON SCHEMA DOMO_PRO_GOLD_DB.ENERGIA TO ROLE DOMO_REPORTING_ROLE;

USE ROLE DOMO_PRO_TRANSFORM_ROLE;
USE WAREHOUSE DOMO_WH_PRO;

SELECT 'ree_pvpc_raw' AS tabla, MAX(ingested_at) AS ultima_ingesta
FROM DOMO_PRO_BRONZE_DB.RAW_APIS.REE_PVPC_RAW
UNION ALL
SELECT 'openmeteo_forecast_raw', MAX(ingested_at)
FROM DOMO_PRO_BRONZE_DB.RAW_APIS.OPENMETEO_FORECAST_RAW;





USE ROLE SECURITYADMIN;
GRANT USAGE, OPERATE ON WAREHOUSE DOMO_WH_PRO TO ROLE DOMO_PRO_TRANSFORM_ROLE;

-- Prueba exacta simulando cómo se conecta dbt:
USE ROLE DOMO_PRO_TRANSFORM_ROLE;
USE SECONDARY ROLES NONE;
USE WAREHOUSE DOMO_WH_PRO;
SELECT CURRENT_ROLE(), CURRENT_WAREHOUSE();


//-----------------------------------------

SELECT *
FROM SLV_ENERGIA__CONTEXTO_HORARIO
ORDER BY FECHA_HORA_PK ASC;

-- 1. Ver base de datos, esquema, rol y warehouse activos
SELECT CURRENT_ROLE(), CURRENT_WAREHOUSE(), CURRENT_DATABASE(), CURRENT_SCHEMA();

-- 2. Buscar la tabla en todas las bases de datos y esquemas a los que tienes acceso
SHOW TABLES LIKE 'SLV_ENERGIA__CONTEXTO_HORARIO' IN ACCOUNT;

//-------------------------------------------------
//Comprobaciones del nuevo silver 3FN

USE ROLE DOMO_DEV_TRANSFORM_ROLE;
USE WAREHOUSE DOMO_WH_DEV;
USE DATABASE DOMO_DEV_SILVER_DB;

-- =============================================================================
-- 1. SEEDS (Esquema SEEDS)
-- =============================================================================
SELECT * FROM SEEDS.CATALOGO_HABITACIONES ORDER BY HABITACION_ID;

SELECT * FROM SEEDS.CATALOGO_DISPOSITIVOS ORDER BY DISPOSITIVO_ID;

-- =============================================================================
-- 2. SILVER EN 3FN (Esquema SILVER)
-- =============================================================================

-- Maestros normalizados
SELECT * FROM SILVER.SLV_DOMOTICA__HABITACIONES ORDER BY HABITACION_ID;

SELECT * FROM SILVER.SLV_DOMOTICA__DISPOSITIVOS ORDER BY DISPOSITIVO_ID;

-- Series temporales horarias (ordenadas por las más recientes)
SELECT * FROM SILVER.SLV_ENERGIA__PRECIOS_PVPC ORDER BY FECHA_HORA_PK DESC LIMIT 100;

SELECT * FROM SILVER.SLV_CLIMA__PREDICCION_HORARIA ORDER BY FECHA_HORA_PK DESC, UBICACION LIMIT 100;

SELECT * FROM SILVER.SLV_DOMOTICA__LECTURAS_SENSORES ORDER BY FECHA_HORA_PK DESC, HABITACION_ID LIMIT 100;



// -----------------------------------------------------------------------------------
SHOW CORTEX BASE MODELS IN SCHEMA SNOWFLAKE.MODELS;

SHOW PARAMETERS LIKE 'CORTEX_ENABLED_CROSS_REGION' IN ACCOUNT;

ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'AWS_EU';

SELECT SNOWFLAKE.CORTEX.COMPLETE(
  'mistral-large2',
  'Responde en una palabra: ¿funciona?'
) AS respuesta;