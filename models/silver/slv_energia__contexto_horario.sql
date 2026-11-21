with pvpc as (
    select * from {{ ref('stg_ree__pvpc') }}
),

clima as (
    select * from {{ ref('stg_openmeteo__prediccion_horaria') }}
)

select
    p.fecha_hora_pk,
    p.fecha_hora_pk::date                     as fecha,
    extract(hour from p.fecha_hora_pk)::int   as hora,
    c.ubicacion,
    p.precio_eur_mwh,
    p.precio_eur_kwh,
    c.temperatura_ext_c,
    c.humedad_relativa_pct,
    c.prob_precipitacion_pct,
    p.ingested_at                             as pvpc_ingested_at,
    c.ingested_at                             as clima_ingested_at
from pvpc as p
left join clima as c
    on p.fecha_hora_pk = c.fecha_hora_pk