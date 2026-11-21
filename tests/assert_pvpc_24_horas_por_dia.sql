-- Falla si algún día tiene un número anómalo de horas (fuera de 23, 24 o 25 por DST)
select
    fecha,
    count(*) as total_horas
from {{ ref('slv_energia__contexto_horario') }}
group by fecha
having count(*) not in (23, 24, 25)