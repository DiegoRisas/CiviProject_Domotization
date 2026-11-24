select
    upper(trim(dispositivo_id))::varchar        as dispositivo_id,
    trim(nombre_dispositivo)::varchar           as nombre_dispositivo,
    lower(trim(tipo_dispositivo))::varchar      as tipo_dispositivo,
    lower(trim(habitacion_id))::varchar         as habitacion_id,
    potencia_nominal_kw::float                  as potencia_nominal_kw,
    capacidad_litros::integer                   as capacidad_litros,
    horas_base_dia::integer                     as horas_base_dia
from {{ ref('catalogo_dispositivos') }}