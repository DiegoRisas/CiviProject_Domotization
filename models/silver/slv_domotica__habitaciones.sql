select
    lower(trim(habitacion_id))::varchar         as habitacion_id,
    trim(nombre_habitacion)::varchar            as nombre_habitacion,
    temp_confort_min_c::float                   as temp_confort_min_c,
    temp_confort_max_c::float                   as temp_confort_max_c
from {{ ref('catalogo_habitaciones') }}