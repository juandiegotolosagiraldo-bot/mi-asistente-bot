"""
Asistente Personal - Bot de Telegram con Groq (GRATIS)
======================================================
Variables Railway:
  TELEGRAM_TOKEN, GROQ_KEY, CHAT_ID, TZ=Europe/Berlin

FUNCIONES:
  1. Lenguaje natural — guarda cualquier tarea
  2. Rutinas recurrentes — todos los dias, lunes a viernes, cada lunes, etc.
  3. Recordatorios con hora — exacta + ultimo aviso 10min despues
  4. Resumen matutino 8AM con TODO (tareas + rutinas + notas)
  5. Plan dia siguiente 9PM
  6. Notas mentales 9:05PM con botones
  7. Resumen semanal domingos 8PM
  8. Comandos: /pendientes /rutina /rutinas /notas /semana
"""

import os, json, asyncio, re
from datetime import datetime, date, timedelta
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_KEY       = os.getenv("GROQ_KEY")
CHAT_ID        = os.getenv("CHAT_ID")
TAREAS_FILE    = "tareas.json"
RUTINAS_FILE   = "rutinas.json"

client = Groq(api_key=GROQ_KEY)

DIAS_ES = {
    0:"lunes", 1:"martes", 2:"miercoles", 3:"jueves",
    4:"viernes", 5:"sabado", 6:"domingo"
}
DIAS_NUM = {
    "lunes":0,"martes":1,"miercoles":2,"miercoles":2,
    "jueves":3,"viernes":4,"sabado":5,"domingo":6
}

# ══════════════════════════════════════════════════════════════
# BASE DE DATOS
# ══════════════════════════════════════════════════════════════

def cargar_tareas() -> list:
    try:
        if os.path.exists(TAREAS_FILE):
            with open(TAREAS_FILE, encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
    except Exception as e:
        print(f"Error cargando tareas: {e}")
    return []

def guardar_tareas(tareas: list):
    try:
        with open(TAREAS_FILE, "w", encoding="utf-8") as f:
            json.dump(tareas, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error guardando tareas: {e}")

def cargar_rutinas() -> list:
    try:
        if os.path.exists(RUTINAS_FILE):
            with open(RUTINAS_FILE, encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
    except Exception as e:
        print(f"Error cargando rutinas: {e}")
    return []

def guardar_rutinas(rutinas: list):
    try:
        with open(RUTINAS_FILE, "w", encoding="utf-8") as f:
            json.dump(rutinas, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error guardando rutinas: {e}")

def nuevo_id(tareas: list) -> int:
    return max((t.get("id", 0) for t in tareas), default=0) + 1

def nuevo_id_rutina(rutinas: list) -> int:
    return max((r.get("id", 0) for r in rutinas), default=0) + 1

# ══════════════════════════════════════════════════════════════
# RUTINAS RECURRENTES
# ══════════════════════════════════════════════════════════════

def dias_de_patron(patron: str) -> list:
    patron = patron.lower().strip()
    if any(x in patron for x in ["todos los dias","todos los dias","diario","cada dia"]):
        return [0,1,2,3,4,5,6]
    if any(x in patron for x in ["lunes a viernes","lunes-viernes","dias de semana","entre semana"]):
        return [0,1,2,3,4]
    if any(x in patron for x in ["fin de semana","fines de semana","sabado y domingo"]):
        return [5,6]
    dias = []
    for nombre, num in DIAS_NUM.items():
        if nombre in patron and num not in dias:
            dias.append(num)
    return sorted(dias) if dias else [0,1,2,3,4,5,6]

def rutinas_del_dia(dia_num: int) -> list:
    return [r for r in cargar_rutinas()
            if r.get("activa", True) and dia_num in r.get("dias", [])]

def formato_dias(dias: list) -> str:
    if dias == [0,1,2,3,4,5,6]: return "todos los dias"
    if dias == [0,1,2,3,4]:     return "lunes a viernes"
    if dias == [5,6]:            return "fines de semana"
    nombres = [DIAS_ES[d].capitalize() for d in dias]
    if len(nombres) == 1: return nombres[0]
    return ", ".join(nombres[:-1]) + " y " + nombres[-1]

# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════

def tareas_del_dia(tareas: list, dia_str: str) -> list:
    resultado = [
        t for t in tareas
        if not t.get("completada") and t.get("fecha") == dia_str
    ]
    resultado.sort(key=lambda x: x.get("hora") or "99:99")
    return resultado

def notas_sin_fecha(tareas: list) -> list:
    return [t for t in tareas if not t.get("completada") and not t.get("fecha")]

def todos_pendientes(tareas: list) -> list:
    hoy = date.today().isoformat()
    return [
        t for t in tareas
        if not t.get("completada") and
        (not t.get("fecha") or t.get("fecha") >= hoy)
    ]

def formato_tarea(t: dict) -> str:
    if t.get("hora"):    return f"🕐 {t['hora']} -- {t['tarea']}"
    elif t.get("fecha"): return f"📌 {t['tarea']}"
    else:                return f"📎 {t['tarea']}"

def formato_rutina(r: dict) -> str:
    hora = f" a las {r['hora']}" if r.get("hora") else ""
    return f"🔁 {r['tarea']}{hora} -- {formato_dias(r.get('dias', []))}"

# ══════════════════════════════════════════════════════════════
# IA CON GROQ
# ══════════════════════════════════════════════════════════════

def procesar_con_groq(mensaje: str, tareas: list, rutinas: list) -> dict:
    ahora   = datetime.now()
    hoy_str = ahora.strftime("%Y-%m-%d")
    manana  = (ahora + timedelta(days=1)).strftime("%Y-%m-%d")

    proximos = {}
    for i in range(1, 8):
        d = ahora + timedelta(days=i)
        proximos[DIAS_ES[d.weekday()]] = d.strftime("%Y-%m-%d")

    resumen_t = [
        {"id": t.get("id"), "tarea": t.get("tarea"),
         "fecha": t.get("fecha"), "hora": t.get("hora"),
         "completada": t.get("completada")}
        for t in tareas[-15:]
    ]
    resumen_r = [
        {"id": r.get("id"), "tarea": r.get("tarea"),
         "hora": r.get("hora"), "dias": r.get("dias")}
        for r in rutinas
    ]

    prompt = f"""Eres un asistente personal que habla español. Siempre llamas al usuario "Juan Diego".
Tu trabajo principal es GUARDAR TAREAS. Ante cualquier duda, guarda la tarea.

Fecha hoy: {hoy_str} ({DIAS_ES[ahora.weekday()]})
Hora: {ahora.strftime("%H:%M")}
Manana: {manana}
Proximos dias: {json.dumps(proximos, ensure_ascii=False)}
Tareas guardadas: {json.dumps(resumen_t, ensure_ascii=False)}
Rutinas: {json.dumps(resumen_r, ensure_ascii=False)}

Mensaje de Juan Diego: "{mensaje}"

RESPONDE SOLO CON JSON VALIDO. Sin texto extra. Sin comillas de codigo. Sin markdown.

{{
  "accion": "agregar|agregar_rutina|completar|eliminar|eliminar_rutina|listar|listar_semana|listar_notas|listar_rutinas|conversar",
  "tarea": "descripcion completa de la tarea",
  "fecha": "YYYY-MM-DD o null",
  "hora": "HH:MM o null",
  "patron_dias": "texto del patron de dias",
  "id": null,
  "respuesta": "confirmacion corta mencionando Juan Diego"
}}

REGLAS CRITICAS — LEE CON ATENCION:

SIEMPRE agregar cuando el mensaje mencione algo que hacer, recordar, comprar, cancelar, llamar, ir, etc.
Ejemplos que SIEMPRE son agregar:
  "el 12 de abril cancelar gemini"  -> agregar, fecha=2026-04-12, hora=null
  "recuerdame llamar al banco"      -> agregar, fecha={hoy_str}, hora=null
  "manana comprar leche"            -> agregar, fecha={manana}, hora=null
  "el lunes tengo reunion"          -> agregar, fecha={proximos.get('lunes','')}, hora=null
  "recuerdame X a las Y"            -> agregar, fecha={hoy_str}, hora=Y en HH:MM
  "recuerdame X el [dia] a las Y"   -> agregar, fecha=ese dia, hora=Y en HH:MM
  "necesito X / pendiente X"        -> agregar, fecha=null, hora=null

RUTINAS (solo cuando dice todos los dias, lunes a viernes, cada semana, etc.):
  "recuerdame X todos los dias"     -> agregar_rutina

COMPLETAR solo cuando dice hecho, listo, ya lo hice, done, termine:
  "hecho la reunion"                -> completar, id=el correcto

LISTAR solo cuando pregunta que tiene:
  "que tengo hoy"                   -> listar
  "agenda de esta semana"           -> listar_semana

CONVERSAR solo para saludos puros como "hola", "como estas", "gracias".
NUNCA uses conversar si el mensaje menciona una tarea o accion concreta.

Para fechas especificas como "el 12 de abril" -> calcular fecha correcta en formato YYYY-MM-DD
Para meses: enero=01 febrero=02 marzo=03 abril=04 mayo=05 junio=06
            julio=07 agosto=08 septiembre=09 octubre=10 noviembre=11 diciembre=12
Año actual: 2026

hora SIEMPRE en HH:MM: 3pm=15:00, 9am=09:00, mediodia=12:00"""

    try:
        r = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=350,
            temperature=0.2
        )
        txt = r.choices[0].message.content.strip()
        txt = re.sub(r"^```json\s*|\s*```$", "", txt, flags=re.MULTILINE).strip()
        txt = re.sub(r"^```\s*|\s*```$", "", txt, flags=re.MULTILINE).strip()
        return json.loads(txt)
    except Exception as e:
        print(f"Error Groq: {e}")
        return {"accion": "conversar", "respuesta": "Ups, tuve un problemita Juan Diego. Puedes repetirme eso?"}

# ══════════════════════════════════════════════════════════════
# HANDLERS
# ══════════════════════════════════════════════════════════════

async def cmd_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(
        "*Hola Juan Diego! Soy tu asistente personal.*\n\n"
        "Hablame natural:\n\n"
        "*Con fecha y hora:*\n"
        "Recuerdame reunion el martes a las 3pm\n"
        "Manana a las 9am llamar al banco\n\n"
        "*Con fecha sin hora:*\n"
        "El viernes tengo entrega de documentos\n\n"
        "*Rutinas recurrentes:*\n"
        "Recuerdame tomar agua todos los dias a las 8am\n"
        "De lunes a viernes a las 7pm revisar correos\n"
        "Cada lunes a las 9am reunion de equipo\n\n"
        "*Notas mentales (sin fecha):*\n"
        "Pendiente llamar al medico\n"
        "Necesito comprar...\n\n"
        "*Para marcar como hecho:*\n"
        "Hecho - Listo - Ya lo hice\n\n"
        "Comandos: /pendientes /rutinas /notas /semana",
        parse_mode="Markdown"
    )

async def cmd_pendientes(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tareas    = cargar_tareas()
    hoy       = date.today().isoformat()
    hoy_num   = date.today().weekday()
    hoy_t     = tareas_del_dia(tareas, hoy)
    notas     = notas_sin_fecha(tareas)
    rutinas_h = rutinas_del_dia(hoy_num)

    txt = "*Juan Diego -- Pendientes de hoy:*\n\n"

    if rutinas_h:
        txt += "*Rutinas de hoy:*\n"
        for r in rutinas_h:
            hora = f"  {r['hora']} -- " if r.get("hora") else "  "
            txt += f"🔁{hora}{r['tarea']}\n"
        txt += "\n"

    if hoy_t:
        txt += "*Tareas de hoy:*\n"
        for t in hoy_t:
            txt += f"  {formato_tarea(t)}\n"
        txt += "\n"

    if notas:
        txt += f"*Notas mentales ({len(notas)}):*\n"
        for t in notas:
            txt += f"  {t['tarea']}\n"

    if not hoy_t and not notas and not rutinas_h:
        txt = "No tienes pendientes para hoy, Juan Diego!"

    await u.message.reply_text(txt, parse_mode="Markdown")

async def cmd_rutina(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await cmd_rutinas(u, ctx)

async def cmd_rutinas(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rutinas = cargar_rutinas()
    activas = [r for r in rutinas if r.get("activa", True)]
    if not activas:
        await u.message.reply_text(
            "*No tienes rutinas guardadas, Juan Diego.*\n\n"
            "Ejemplo: Recuerdame tomar agua todos los dias a las 8am",
            parse_mode="Markdown")
        return
    txt = "*Tus rutinas activas:*\n\n"
    for r in activas:
        txt += f"  #{r['id']} {formato_rutina(r)}\n"
    txt += "\nPara eliminar: Eliminar rutina #ID"
    await u.message.reply_text(txt, parse_mode="Markdown")

async def cmd_notas(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tareas = cargar_tareas()
    notas  = notas_sin_fecha(tareas)
    if not notas:
        await u.message.reply_text("No tienes notas mentales pendientes, Juan Diego.")
        return
    txt = "*Notas mentales pendientes:*\n\n"
    for t in notas:
        txt += f"  #{t['id']} -- {t['tarea']}\n"
    txt += "\nEscribe hecho + la tarea para marcarla."
    await u.message.reply_text(txt, parse_mode="Markdown")

async def cmd_semana(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tareas = cargar_tareas()
    notas  = notas_sin_fecha(tareas)
    hoy    = date.today()
    txt    = "*Juan Diego -- Tu agenda de esta semana:*\n\n"
    tiene  = False

    for i in range(7):
        dia       = hoy + timedelta(days=i)
        dia_str   = dia.isoformat()
        dia_num   = dia.weekday()
        nombre    = DIAS_ES[dia_num].capitalize()
        tareas_d  = tareas_del_dia(tareas, dia_str)
        rutinas_d = rutinas_del_dia(dia_num)

        if tareas_d or rutinas_d:
            tiene = True
            txt  += f"*{nombre} {dia.strftime('%d/%m')}:*\n"
            for r in rutinas_d:
                hora = f"  {r['hora']} -- " if r.get("hora") else "  "
                txt += f"🔁{hora}{r['tarea']} (rutina)\n"
            for t in tareas_d:
                txt += f"  {formato_tarea(t)}\n"
            txt += "\n"

    if notas:
        tiene = True
        txt  += f"*Notas mentales ({len(notas)}):*\n"
        for t in notas:
            txt += f"  {t['tarea']}\n"

    if not tiene:
        txt += "No tienes tareas esta semana, Juan Diego."

    await u.message.reply_text(txt, parse_mode="Markdown")

# ══════════════════════════════════════════════════════════════
# HANDLER -- MENSAJES TEXTO
# ══════════════════════════════════════════════════════════════

async def manejar_mensaje(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tareas    = cargar_tareas()
    rutinas   = cargar_rutinas()
    resultado = procesar_con_groq(u.message.text, tareas, rutinas)
    accion    = resultado.get("accion", "conversar")

    if accion == "agregar":
        nueva = {
            "id":                   nuevo_id(tareas),
            "tarea":                resultado.get("tarea", "Tarea sin nombre"),
            "fecha":                resultado.get("fecha"),
            "hora":                 resultado.get("hora"),
            "completada":           False,
            "recordatorio_enviado": False,
            "ultimo_aviso_enviado": False,
            "ultima_notificacion_ts": 0,
        }
        tareas.append(nueva)
        guardar_tareas(tareas)
        print(f"Guardada: {nueva['tarea']} | fecha={nueva['fecha']} | hora={nueva['hora']}")

    elif accion == "agregar_rutina":
        patron  = resultado.get("patron_dias", "todos los dias")
        dias    = dias_de_patron(patron)
        nueva_r = {
            "id":     nuevo_id_rutina(rutinas),
            "tarea":  resultado.get("tarea", "Rutina"),
            "hora":   resultado.get("hora"),
            "dias":   dias,
            "activa": True,
        }
        rutinas.append(nueva_r)
        guardar_rutinas(rutinas)
        print(f"Rutina: {nueva_r['tarea']} | dias={dias}")

    elif accion == "completar":
        tid = resultado.get("id")
        for t in tareas:
            if t.get("id") == tid:
                t["completada"] = True
                break
        guardar_tareas(tareas)

    elif accion == "eliminar":
        tareas = [t for t in tareas if t.get("id") != resultado.get("id")]
        guardar_tareas(tareas)

    elif accion == "eliminar_rutina":
        rutinas = [r for r in rutinas if r.get("id") != resultado.get("id")]
        guardar_rutinas(rutinas)

    elif accion == "listar":
        await cmd_pendientes(u, ctx); return
    elif accion == "listar_semana":
        await cmd_semana(u, ctx); return
    elif accion == "listar_notas":
        await cmd_notas(u, ctx); return
    elif accion == "listar_rutinas":
        await cmd_rutinas(u, ctx); return

    await u.message.reply_text(
        resultado.get("respuesta", "Entendido Juan Diego"),
        parse_mode="Markdown"
    )

# ══════════════════════════════════════════════════════════════
# HANDLER -- BOTONES
# ══════════════════════════════════════════════════════════════

async def manejar_boton(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    await q.answer()
    d      = q.data
    tareas = cargar_tareas()

    if d.startswith("hecho_"):
        tid    = int(d.split("_")[1])
        nombre = ""
        for t in tareas:
            if t.get("id") == tid:
                t["completada"] = True
                nombre = t["tarea"]
                break
        guardar_tareas(tareas)
        await q.edit_message_text(f"Hecho! {nombre} completada, Juan Diego.", parse_mode="Markdown")

    elif d.startswith("continuar_"):
        tid    = int(d.split("_")[1])
        nombre = next((t["tarea"] for t in tareas if t.get("id") == tid), "la tarea")
        await q.edit_message_text(f"Seguire recordandote: {nombre}, Juan Diego.", parse_mode="Markdown")

# ══════════════════════════════════════════════════════════════
# LOOP -- RECORDATORIOS CON HORA
# ══════════════════════════════════════════════════════════════

async def loop_recordatorios(app: Application):
    while True:
        await asyncio.sleep(60)
        ahora       = datetime.now()
        hora_actual = ahora.strftime("%H:%M")
        hoy         = date.today().isoformat()
        hoy_num     = date.today().weekday()
        cambios     = False
        tareas      = cargar_tareas()

        for t in tareas:
            if t.get("completada") or not t.get("fecha") or not t.get("hora"):
                continue
            if t.get("fecha") != hoy:
                continue
            ahora_ts = ahora.timestamp()
            mins     = (ahora_ts - t.get("ultima_notificacion_ts", 0)) / 60

            if t["hora"] == hora_actual and not t.get("recordatorio_enviado"):
                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"Recuerda Juan Diego: *{t['tarea']}*",
                    parse_mode="Markdown")
                t["recordatorio_enviado"]   = True
                t["ultimo_aviso_enviado"]   = False
                t["ultima_notificacion_ts"] = ahora_ts
                cambios = True

            elif (t.get("recordatorio_enviado") and
                  not t.get("ultimo_aviso_enviado") and
                  mins >= 10):
                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"Ultimo recordatorio Juan Diego: *{t['tarea']}*",
                    parse_mode="Markdown")
                t["ultimo_aviso_enviado"] = True
                cambios = True

        if cambios:
            guardar_tareas(tareas)

        rutinas   = cargar_rutinas()
        cambios_r = False
        for r in rutinas:
            if not r.get("activa") or not r.get("hora"):
                continue
            if hoy_num not in r.get("dias", []):
                continue
            clave_hoy = f"notif_{hoy}"
            if hora_actual == r["hora"] and not r.get(clave_hoy):
                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"Rutina diaria Juan Diego: *{r['tarea']}*",
                    parse_mode="Markdown")
                r[clave_hoy] = True
                cambios_r = True
        if cambios_r:
            guardar_rutinas(rutinas)

# ══════════════════════════════════════════════════════════════
# LOOP -- RESUMEN MATUTINO 8AM
# ══════════════════════════════════════════════════════════════

async def loop_resumen_diario(app: Application):
    ultima_fecha = None
    while True:
        await asyncio.sleep(60)
        ahora = datetime.now()
        if ahora.strftime("%H:%M") == "08:00" and ahora.date() != ultima_fecha:
            hoy       = ahora.date().isoformat()
            hoy_num   = ahora.date().weekday()
            tareas    = cargar_tareas()
            hoy_t     = tareas_del_dia(tareas, hoy)
            notas     = notas_sin_fecha(tareas)
            rutinas_h = rutinas_del_dia(hoy_num)

            txt = f"Buenos dias Juan Diego! Agenda de hoy:\n"
            txt += f"{DIAS_ES[hoy_num].capitalize()} {ahora.strftime('%d/%m')}\n\n"

            if rutinas_h:
                txt += "*Rutinas:*\n"
                for r in rutinas_h:
                    hora = f"  {r['hora']} -- " if r.get("hora") else "  "
                    txt += f"🔁{hora}{r['tarea']}\n"
                txt += "\n"

            if hoy_t:
                txt += "*Tareas:*\n"
                for t in hoy_t:
                    txt += f"  {formato_tarea(t)}\n"
                txt += "\n"

            if notas:
                txt += f"*Notas mentales ({len(notas)}):*\n"
                for t in notas[:5]:
                    txt += f"  {t['tarea']}\n"
                if len(notas) > 5:
                    txt += f"  ...y {len(notas)-5} mas. Usa /notas\n"

            if not hoy_t and not notas and not rutinas_h:
                txt += "No tienes tareas hoy Juan Diego. Disfruta!"
            else:
                txt += "\nMucho exito hoy Juan Diego!"

            await app.bot.send_message(chat_id=CHAT_ID, text=txt, parse_mode="Markdown")
            ultima_fecha = ahora.date()

# ══════════════════════════════════════════════════════════════
# LOOP -- PLAN DIA SIGUIENTE 9PM
# ══════════════════════════════════════════════════════════════

async def loop_plan_siguiente(app: Application):
    ultima_fecha = None
    while True:
        await asyncio.sleep(60)
        ahora = datetime.now()
        if ahora.strftime("%H:%M") == "21:00" and ahora.date() != ultima_fecha:
            manana      = (ahora + timedelta(days=1)).date()
            manana_str  = manana.isoformat()
            manana_num  = manana.weekday()
            dia_nombre  = DIAS_ES[manana_num].capitalize()
            tareas      = cargar_tareas()
            notas       = notas_sin_fecha(tareas)
            tareas_man  = tareas_del_dia(tareas, manana_str)
            rutinas_man = rutinas_del_dia(manana_num)

            txt = f"Buenas noches Juan Diego -- Manana:\n"
            txt += f"{dia_nombre} {manana.strftime('%d/%m')}\n\n"

            if rutinas_man:
                txt += "*Rutinas:*\n"
                for r in rutinas_man:
                    hora = f"  {r['hora']} -- " if r.get("hora") else "  "
                    txt += f"🔁{hora}{r['tarea']}\n"
                txt += "\n"

            if tareas_man:
                txt += "*Tareas:*\n"
                for t in tareas_man:
                    txt += f"  {formato_tarea(t)}\n"
                txt += "\n"

            if not tareas_man and not rutinas_man:
                txt += "No tienes tareas para manana.\n"

            if notas:
                txt += f"Recuerda: {len(notas)} nota(s) mental(es) pendiente(s).\n"

            txt += "\nQue descanses bien Juan Diego!"
            await app.bot.send_message(chat_id=CHAT_ID, text=txt, parse_mode="Markdown")
            ultima_fecha = ahora.date()

# ══════════════════════════════════════════════════════════════
# LOOP -- NOTAS MENTALES 9:05PM
# ══════════════════════════════════════════════════════════════

async def loop_notas_mentales(app: Application):
    ultima_fecha = None
    while True:
        await asyncio.sleep(60)
        ahora = datetime.now()
        if ahora.strftime("%H:%M") == "21:05" and ahora.date() != ultima_fecha:
            tareas = cargar_tareas()
            notas  = notas_sin_fecha(tareas)
            if notas:
                txt = "*Juan Diego -- Notas mentales pendientes:*\n\n"
                for t in notas:
                    txt += f"  {t['tarea']}\n"
                txt += "\nMarca las que ya completaste:"
                botones = []
                for t in notas[:8]:
                    botones.append([
                        InlineKeyboardButton(
                            f"Hecho: {t['tarea'][:28]}",
                            callback_data=f"hecho_{t['id']}"),
                        InlineKeyboardButton(
                            "Continuar",
                            callback_data=f"continuar_{t['id']}")
                    ])
                await app.bot.send_message(
                    chat_id=CHAT_ID, text=txt,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(botones))
            ultima_fecha = ahora.date()

# ══════════════════════════════════════════════════════════════
# LOOP -- RESUMEN SEMANAL DOMINGOS 8PM
# ══════════════════════════════════════════════════════════════

async def loop_resumen_semanal(app: Application):
    ultima_fecha = None
    while True:
        await asyncio.sleep(60)
        ahora      = datetime.now()
        es_domingo = ahora.weekday() == 6
        if ahora.strftime("%H:%M") == "20:00" and es_domingo and ahora.date() != ultima_fecha:
            tareas = cargar_tareas()
            notas  = notas_sin_fecha(tareas)
            hoy    = ahora.date()
            txt    = "*Juan Diego -- Tu semana que viene:*\n\n"
            tiene  = False

            for i in range(1, 8):
                dia       = hoy + timedelta(days=i)
                dia_str   = dia.isoformat()
                dia_num   = dia.weekday()
                nombre    = DIAS_ES[dia_num].capitalize()
                tareas_d  = tareas_del_dia(tareas, dia_str)
                rutinas_d = rutinas_del_dia(dia_num)

                if tareas_d or rutinas_d:
                    tiene = True
                    txt  += f"*{nombre} {dia.strftime('%d/%m')}:*\n"
                    for r in rutinas_d:
                        hora = f"  {r['hora']} -- " if r.get("hora") else "  "
                        txt += f"🔁{hora}{r['tarea']} (rutina)\n"
                    for t in tareas_d:
                        txt += f"  {formato_tarea(t)}\n"
                    txt += "\n"

            if notas:
                tiene = True
                txt  += f"*Notas mentales ({len(notas)}):*\n"
                for t in notas[:5]:
                    txt += f"  {t['tarea']}\n"

            if not tiene:
                txt += "No tienes tareas la semana que viene Juan Diego."

            txt += "\nQue tengas una excelente semana Juan Diego!"
            await app.bot.send_message(chat_id=CHAT_ID, text=txt, parse_mode="Markdown")
            ultima_fecha = ahora.date()

# ══════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("pendientes", cmd_pendientes))
    app.add_handler(CommandHandler("rutina",     cmd_rutina))
    app.add_handler(CommandHandler("rutinas",    cmd_rutinas))
    app.add_handler(CommandHandler("notas",      cmd_notas))
    app.add_handler(CommandHandler("semana",     cmd_semana))
    app.add_handler(CallbackQueryHandler(manejar_boton))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

    async def post_init(application: Application):
        asyncio.create_task(loop_recordatorios(application))
        asyncio.create_task(loop_resumen_diario(application))
        asyncio.create_task(loop_plan_siguiente(application))
        asyncio.create_task(loop_notas_mentales(application))
        asyncio.create_task(loop_resumen_semanal(application))

    app.post_init = post_init
    print("Asistente Personal Juan Diego iniciado...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
