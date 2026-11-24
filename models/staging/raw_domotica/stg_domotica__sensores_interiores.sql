with source as (
    select
        ingested_at,
        timestamp_lectura,
        sensor,
        temp_interior_c,
        humedad_interior_pct
    from {{ source('raw_domotica', 'sensores_interiores_raw') }}
    where timestamp_lectura is not null
      and sensor is not null
      and temp_interior_c is not null
      and temp_interior_c between -10 and 50
      and (humedad_interior_pct is null or humedad_interior_pct between 0 and 100)
)

select
    timestamp_lectura::timestamp_ntz                            as fecha_hora_lectura,
    date_trunc('hour', timestamp_lectura)::timestamp_ntz        as fecha_hora_pk,
    regexp_replace(lower(trim(sensor)), '^t_', '')::varchar    as habitacion_id,
    sensor::varchar                                             as sensor_raw,
    temp_interior_c::float                                      as temp_interior_c,
    humedad_interior_pct::float                                 as humedad_interior_pct,
    ingested_at                                                 as ingested_at
from source