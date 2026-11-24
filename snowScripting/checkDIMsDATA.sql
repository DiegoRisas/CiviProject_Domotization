-- Ver todos los registros de dim_dispositivos
SELECT
    dispositivo_sk,
    dispositivo_id,
    nombre_dispositivo,
    tipo_dispositivo,
    habitacion,
    potencia_nominal_kw,
    capacidad_litros,
    horas_base_dia
FROM DOMO_DEV_GOLD_DB.CORE.DIM_DISPOSITIVOS
ORDER BY tipo_dispositivo, dispositivo_id;