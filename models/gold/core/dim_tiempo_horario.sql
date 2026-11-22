with contexto as (
    select distinct
        fecha_hora_pk,
        fecha,
        hora
    from {{ ref('slv_energia__contexto_horario') }}
)

select
    fecha_hora_pk,
    fecha,
    hora,
    dayofweekiso(fecha_hora_pk)                 as dia_semana_num,
    dayname(fecha_hora_pk)                      as dia_semana,
    dayofweekiso(fecha_hora_pk) in (6, 7)       as es_fin_de_semana,
    month(fecha_hora_pk)                        as mes,
    quarter(fecha_hora_pk)                      as trimestre,
    {{ tramo_horario_pvpc('fecha_hora_pk') }}   as tramo_pvpc,
    case
        when hora between 0 and 7   then 'Madrugada'
        when hora between 8 and 16  then 'Mediodia'
        else 'Tarde_Noche'
    end                                         as bloque_dia
from contexto