-- =============================================================================
-- snowScripting/setup_semantic_views_role.sql
-- Permisos de creación para dbt + rol aislado de solo lectura para IA/Python
-- =============================================================================

USE ROLE SECURITYADMIN;

-- 1. Crear rol específico para el agente IA / script Python (principio de mínimo privilegio)
CREATE ROLE IF NOT EXISTS DOMO_SEMANTIC_AI_ROLE
    COMMENT = 'Rol de solo lectura exclusiva sobre Semantic Views en Gold (ENERGIA) para consultas desde Python/Gemini.';

-- Jerarquía estándar hacia SYSADMIN y asignación a tu usuario
GRANT ROLE DOMO_SEMANTIC_AI_ROLE TO ROLE SYSADMIN;
GRANT ROLE DOMO_SEMANTIC_AI_ROLE TO USER DIEGOSV;

-- 2. Permitir a dbt crear/actualizar Semantic Views en DEV y PRO
GRANT CREATE SEMANTIC VIEW ON SCHEMA DOMO_DEV_GOLD_DB.ENERGIA TO ROLE DOMO_DEV_TRANSFORM_ROLE;
GRANT CREATE SEMANTIC VIEW ON SCHEMA DOMO_PRO_GOLD_DB.ENERGIA TO ROLE DOMO_PRO_TRANSFORM_ROLE;

-- 3. Permiso mínimo de cómputo (solo USAGE; con AUTO_RESUME=TRUE basta para consultar)
GRANT USAGE ON WAREHOUSE DOMO_WH_DEV TO ROLE DOMO_SEMANTIC_AI_ROLE;
GRANT USAGE ON WAREHOUSE DOMO_WH_PRO TO ROLE DOMO_SEMANTIC_AI_ROLE;

-- 4. Lectura exclusiva de Semantic Views en DEV (sin acceso a tablas ni vistas base)
GRANT USAGE  ON DATABASE DOMO_DEV_GOLD_DB                                     TO ROLE DOMO_SEMANTIC_AI_ROLE;
GRANT USAGE  ON SCHEMA   DOMO_DEV_GOLD_DB.ENERGIA                             TO ROLE DOMO_SEMANTIC_AI_ROLE;
GRANT SELECT ON ALL      SEMANTIC VIEWS IN SCHEMA DOMO_DEV_GOLD_DB.ENERGIA    TO ROLE DOMO_SEMANTIC_AI_ROLE;
GRANT SELECT ON FUTURE   SEMANTIC VIEWS IN SCHEMA DOMO_DEV_GOLD_DB.ENERGIA    TO ROLE DOMO_SEMANTIC_AI_ROLE;

-- 5. Lectura exclusiva de Semantic Views en PRO (sin acceso a tablas ni vistas base)
GRANT USAGE  ON DATABASE DOMO_PRO_GOLD_DB                                     TO ROLE DOMO_SEMANTIC_AI_ROLE;
GRANT USAGE  ON SCHEMA   DOMO_PRO_GOLD_DB.ENERGIA                             TO ROLE DOMO_SEMANTIC_AI_ROLE;
GRANT SELECT ON ALL      SEMANTIC VIEWS IN SCHEMA DOMO_PRO_GOLD_DB.ENERGIA    TO ROLE DOMO_SEMANTIC_AI_ROLE;
GRANT SELECT ON FUTURE   SEMANTIC VIEWS IN SCHEMA DOMO_PRO_GOLD_DB.ENERGIA    TO ROLE DOMO_SEMANTIC_AI_ROLE;

-- =============================================================================
-- 6. Verificación (simulando la sesión aislada del script de Python)
-- =============================================================================
USE ROLE DOMO_SEMANTIC_AI_ROLE;
USE SECONDARY ROLES NONE;
USE WAREHOUSE DOMO_WH_DEV;

SELECT CURRENT_ROLE(), CURRENT_SECONDARY_ROLES(), CURRENT_WAREHOUSE();

-- Tras ejecutar `dbt build --select sv_plan_termo`, esta consulta debe funcionar:
-- SELECT * FROM SEMANTIC_VIEW(
--     DOMO_DEV_GOLD_DB.ENERGIA.SV_PLAN_TERMO
--     DIMENSIONS tiempo.tramo_pvpc
--     METRICS plan_termo.coste_termo_eur, plan_termo.horas_encendido
-- );