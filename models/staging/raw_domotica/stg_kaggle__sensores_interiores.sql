with raw as (
    select
        ingested_at,
        sensor,
        fecha_hora_original,
        fecha_hora_simulada,
        valor
    from {{ source('raw_domotica', 'sensores_kaggle_raw') }}
    where valor is not null
      and valor between -10 and 50
),

deduplicado as (
    -- Protege contra posibles re-ejecuciones manuales del backfill o la Task
    select
        ingested_at,
        sensor,
        fecha_hora_simulada,
        valor
    from raw
    qualify row_number() over (
        partition by sensor, fecha_hora_simulada
        order by ingested_at desc
    ) = 1
)

select
    date_trunc('hour', fecha_hora_simulada)::timestamp_ntz  as fecha_hora_pk,
    lower(replace(sensor, 'T_', ''))::varchar               as habitacion,
    round(avg(valor), 2)::float                             as temp_interior_c,
    round(min(valor), 2)::float                             as temp_interior_min_c,
    round(max(valor), 2)::float                             as temp_interior_max_c,
    count(*)::integer                                       as num_lecturas,
    max(ingested_at)                                        as ingested_at
from deduplicado
group by 1, 2