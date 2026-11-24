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

SEMANTIC_VIEW_SQL_PATH = Path("models/gold/energy/sv_plan_termo.sql")


def ejecutar_sql_semantic_view(sql: str) -> str:
    """Ejecuta una consulta SELECT gobernada contra la Snowflake Semantic View SV_PLAN_TERMO."""
    sql_limpio = sql.strip().rstrip(";")
    sql_lower = sql_limpio.lower()

    if not sql_lower.startswith(("select", "with")):
        return "Error de seguridad: solo se permiten consultas SELECT o WITH."
    if "semantic_view(" not in sql_lower:
        return "Error de gobierno: debes consultar obligatoriamente usando FROM SEMANTIC_VIEW(...)."

    print(f"\n[SQL sobre Snowflake Semantic View]\n{sql_limpio}\n")

    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        role=os.getenv("SNOWFLAKE_ROLE", "DOMO_SEMANTIC_AI_ROLE"),
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
    """Obtiene los modelos Gemini de texto activos en tu API Key."""
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
    if not SEMANTIC_VIEW_SQL_PATH.exists():
        raise FileNotFoundError(
            f"No se encuentra {SEMANTIC_VIEW_SQL_PATH}. Ejecuta git pull desde la raíz del repo."
        )

    definicion_sv = SEMANTIC_VIEW_SQL_PATH.read_text(encoding="utf-8")
    db_actual = os.getenv("SNOWFLAKE_DATABASE", "DOMO_DEV_GOLD_DB")
    sv_fqn = f"{db_actual}.ENERGIA.SV_PLAN_TERMO"

    system_instruction = (
        "Eres un analista energético experto que responde en español sobre el termo eléctrico del usuario.\n"
        "Para cualquier pregunta sobre horarios, consumos o costes, debes usar OBLIGATORIAMENTE la herramienta "
        "ejecutar_sql_semantic_view consultando la Snowflake Semantic View nativa:\n"
        f"  {sv_fqn}\n\n"
        "Definición oficial de la Semantic View en dbt:\n"
        + definicion_sv
        + "\n\nReglas estrictas de sintaxis SEMANTIC_VIEW en Snowflake:\n"
        f"- Usa SIEMPRE el formato:\n"
        f"  SELECT * FROM SEMANTIC_VIEW(\n"
        f"      {sv_fqn}\n"
        "      DIMENSIONS <lista de dimensiones cualificadas, ej. tiempo.hora, tiempo.tramo_pvpc>\n"
        "      METRICS <lista de métricas cualificadas, ej. plan_termo.coste_termo_eur>\n"
        "      WHERE <condiciones sobre dimensiones o facts>\n"
        "  ) ORDER BY ...\n"
        "- No escribas JOINs manuales ni consultes tablas base directamente; Snowflake resuelve los joins.\n"
        "- No mezcles FACTS y METRICS en la misma llamada SEMANTIC_VIEW(). Si necesitas datos horarios de encendido "
        "(sin agregar o por hora), usa DIMENSIONS + METRICS o DIMENSIONS + FACTS.\n"
        "- Para 'hoy' o 'esta semana' usa CONVERT_TIMEZONE('Europe/Madrid', CURRENT_TIMESTAMP())::DATE.\n"
        "- Nunca inventes cifras ni fórmulas fuera de la Semantic View.\n"
    )

    client = genai.Client(
        api_key=os.environ["GEMINI_API_KEY"],
        http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
    )
    modelos = obtener_modelos_texto(client)

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=[ejecutar_sql_semantic_view],
        temperature=0.0,
    )
    historial = []

    print(
        f"Asistente conectado a Semantic View {sv_fqn} ({os.getenv('SNOWFLAKE_ROLE', 'DOMO_REPORTING_ROLE')})."
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