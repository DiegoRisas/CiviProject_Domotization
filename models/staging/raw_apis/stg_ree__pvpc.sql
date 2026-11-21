with raw as (
    select
        target_date,
        file_name,
        ingested_at,
        raw_json
    from {{ source('raw_apis', 'ree_pvpc_raw') }}
),

flattened as (
    select
        convert_timezone(
            'Europe/Madrid',
            val.value:datetime::timestamp_tz
        )::timestamp_ntz                            as fecha_hora_pk,
        r.target_date                               as fecha_objetivo,
        ind.value:id::varchar                       as indicador_id,
        ind.value:attributes:title::varchar         as tarifa,
        val.value:value::float                      as precio_eur_mwh,
        round(val.value:value::float / 1000, 5)     as precio_eur_kwh,
        r.file_name,
        r.ingested_at
    from raw as r,
    lateral flatten(input => r.raw_json:included) as ind,
    lateral flatten(input => ind.value:attributes:values) as val
    where ind.value:id::varchar = '1001'
)

select
    fecha_hora_pk,
    fecha_objetivo,
    indicador_id,
    tarifa,
    precio_eur_mwh,
    precio_eur_kwh,
    file_name,
    ingested_at
from flattened
qualify row_number() over (
    partition by fecha_hora_pk
    order by ingested_at desc
) = 1