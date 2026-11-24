import os
import warnings
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError
import snowflake.connector

warnings.filterwarnings("ignore", category=FutureWarning, module="snowflake.connector")
load_dotenv()

SEMANTIC_YAML_PATH = Path("models/gold/core/_core__semantic_models.yml")


def ejecutar_sql_gold(sql: str) -> str:
    """Ejecuta una consulta SELECT de solo lectura en Snowflake (capa Gold) y devuelve los resultados."""
    sql_limpio = sql.strip().rstrip(";")
    if not sql_limpio.lower().startswith(("select", "with")):
        return "Error de seguridad: solo se permiten consultas SELECT o WITH."

    print(f"\n[SQL Gobernado ejecutado en Snowflake]\n{sql_limpio}\n")

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.getenv("SNOWFLAKE_ROLE", "DOMO_REPORTING_ROLE"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", "DOMO_WH_DEV"),
        database=os.getenv("SNOWFLAKE_DATABASE", "DOMO_DEV_GOLD_DB"),
        schema="ENERGIA",
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql_limpio)
            columnas = [col[0] for col in cur.description]
            filas = cur.fetchall()
            print(f"[Snowflake] {len(filas)} filas devueltas.")
            if not filas:
                return "La consulta no devolvió filas para ese filtro."
            resultado = [dict(zip(columnas, fila)) for fila in filas]
            return str(resultado[:100])
    finally:
        conn.close()


def obtener_modelos_texto(client) -> list[str]:
    """Obtiene solo los modelos Gemini de texto activos en tu API Key (sin 2.5 ni imagen)."""
    preferidos = [
        "gemini-3-flash",
        "gemini-3.1-pro",
        "gemini-3.1-flash-lite",
        "gemini-3.8-flash",
    ]
    activos = []
    try:
        for m in client.models.list():
            nombre = m.name.replace("models/", "")
            acciones = getattr(m, "supported_actions", []) or []
            if "gemini" in nombre and "generateContent" in acciones:
                if not any(
                    x in nombre
                    for x in ("2.5", "2.0", "1.5", "image", "nano", "embedding", "veo", "tts", "audio")
                ):
                    activos.append(nombre)
    except Exception:
        pass

    ordenados = [m for m in preferidos if m in activos]
    for m in activos:
        if m not in ordenados:
            ordenados.append(m)
    return ordenados or preferidos


def consultar_con_fallback(client, modelos, config, historial, pregunta):
    """Ejecuta la consulta saltando al instante (sin esperas) si un modelo da 404/429/503."""
    ultimo_error = None
    for modelo in modelos:
        try:
            print(f"-> Consultando a {modelo}...")
            chat = client.chats.create(model=modelo, config=config, history=historial)
            respuesta = chat.send_message(pregunta)
            return respuesta, chat.get_history(), modelo
        except (ServerError, ClientError) as e:
            ultimo_error = e
            if any(code in str(e) for code in ("503", "404", "429")):
                print(f"   ({modelo} no disponible [{e.code}], pasando al siguiente)")
                continue
            raise
    raise RuntimeError(f"Todos los modelos están saturados ahora mismo. Último error: {ultimo_error}")


def iniciar_chat():
    if not SEMANTIC_YAML_PATH.exists():
        raise FileNotFoundError(
            f"No se encuentra {SEMANTIC_YAML_PATH}. Ejecuta desde la raíz del repo."
        )

    definicion_semantica = SEMANTIC_YAML_PATH.read_text(encoding="utf-8")
    db_actual = os.getenv("SNOWFLAKE_DATABASE", "DOMO_DEV_GOLD_DB")

    system_instruction = (
        "Eres un analista energético experto que responde en español sobre los datos domóticos del usuario.\n"
        "Para responder cualquier pregunta numérica o de horarios, debes usar OBLIGATORIAMENTE la herramienta ejecutar_sql_gold "
        "respetando al pie de la letra las entidades, dimensiones, medidas y fórmulas de esta capa semántica de dbt:\n\n"
        + definicion_semantica
        + "\n\nReglas de generación SQL para Snowflake:\n"
        f"- Tabla de hechos: {db_actual}.ENERGIA.FCT_PLAN_TERMO_HORARIO\n"
        f"- Dimensiones: {db_actual}.CORE.DIM_TIEMPO_HORARIO y {db_actual}.CORE.DIM_TERMO\n"
        "- Une FCT_PLAN_TERMO_HORARIO con DIM_TIEMPO_HORARIO usando fecha_hora_pk y con DIM_TERMO usando termo_sk.\n"
        "- Para referencias relativas como 'hoy' o 'esta semana', usa CONVERT_TIMEZONE('Europe/Madrid', CURRENT_TIMESTAMP())::DATE en Snowflake.\n"
        "- Respeta exactamente las fórmulas de las métricas (por ejemplo, horas_encendido suma "
        "CASE WHEN estado_termo = 'ON' THEN 1 ELSE 0 END, y precio_medio_efectivo_eur_kwh divide "
        "SUM(coste_estimado_eur) / NULLIF(SUM(consumo_estimado_kwh), 0)).\n"
        "- Nunca inventes cifras ni fórmulas fuera de este YAML.\n"
    )

    # attempts=1 evita que el SDK se quede bloqueado 60s reintentando un 503
    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
    )
    modelos = obtener_modelos_texto(client)

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[ejecutar_sql_gold],
        temperature=0.0,
    )
    historial = []

    print(
        f"Asistente semántico conectado a {db_actual} ({os.getenv('SNOWFLAKE_ROLE', 'DOMO_REPORTING_ROLE')})."
    )
    print(f"Modelos disponibles: {', '.join(modelos)}")
    print("Escribe 'salir' para terminar.\n")

    while True:
        pregunta = input("Tú: ").strip()
        if not pregunta:
            continue
        if pregunta.lower() in {"salir", "exit", "quit"}:
            break

        try:
            respuesta, historial, modelo_usado = consultar_con_fallback(
                client, modelos, config, historial, pregunta
            )
            texto = respuesta.text or "(Sin texto de respuesta)"
            print(f"\nGemini ({modelo_usado}): {texto}\n")
        except Exception as e:
            print(f"\nError: {e}\n")


if __name__ == "__main__":
    iniciar_chat()