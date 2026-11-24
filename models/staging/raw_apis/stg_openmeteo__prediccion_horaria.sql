with raw as (
    select
        ubicacion,
        file_name,
        ingested_at,
        raw_json
    from {{ source('raw_apis', 'openmeteo_forecast_raw') }}
)

select
    t.value::timestamp_ntz                                        as fecha_hora_pk,
    r.ubicacion::varchar                                          as ubicacion,
    r.raw_json:hourly:temperature_2m[t.index]::float              as temperatura_ext_c,
    r.raw_json:hourly:relative_humidity_2m[t.index]::float        as humedad_relativa_pct,
    r.raw_json:hourly:precipitation_probability[t.index]::float   as prob_precipitacion_pct,
    r.file_name::varchar                                          as file_name,
    r.ingested_at                                                 as ingested_at
from raw as r,
lateral flatten(input => r.raw_json:hourly:time) as t