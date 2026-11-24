with habitaciones as (
    select * from {{ ref('slv_domotica__habitaciones') }}
)

select
    {{ dbt_utils.generate_surrogate_key(['habitacion_id']) }} as habitacion_sk,
    habitacion_id,
    nombre_habitacion,
    temp_confort_min_c,
    temp_confort_max_c
from habitaciones