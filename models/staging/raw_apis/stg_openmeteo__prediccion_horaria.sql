with raw as (
    select
        ubicacion,
        file_name,
        ingested_at,
        raw_json
    from {{ source('raw_apis', 'openmeteo_forecast_raw') }}
),

flattened as (
    select
        t.value::timestamp_ntz                                        as fecha_hora_pk,
        r.ubicacion,
        r.raw_json:hourly:temperature_2m[t.index]::float              as temperatura_ext_c,
        r.raw_json:hourly:relative_humidity_2m[t.index]::float        as humedad_relativa_pct,
        r.raw_json:hourly:precipitation_probability[t.index]::float   as prob_precipitacion_pct,
        r.file_name,
        r.ingested_at
    from raw as r,
    lateral flatten(input => r.raw_json:hourly:time) as t
)

select
    fecha_hora_pk,
    ubicacion,
    temperatura_ext_c,
    humedad_relativa_pct,
    prob_precipitacion_pct,
    file_name,
    ingested_at
from flattened
qualify row_number() over (
    partition by fecha_hora_pk, ubicacion
    order by ingested_at desc
) = 1