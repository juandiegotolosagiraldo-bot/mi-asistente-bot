
"""
Asistente Personal - Bot de Telegram con Groq (GRATIS)
======================================================
Variables de entorno necesarias en Railway:
  TELEGRAM_TOKEN  → Token del bot (de @BotFather)
  GROQ_KEY        → API Key de Groq (gratis)
  CHAT_ID         → Tu ID numérico de Telegram
"""

import os
import json
import asyncio
import re
from datetime import datetime, date
from groq import Groq
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN")
GROQ_KEY        = os.getenv("GROQ_KEY")
CHAT_ID         = os.getenv("CHAT_ID")
TAREAS_FILE     = "tareas.json"
RUTINA_FILE     = "rutina.json"
RENOTIFICAR_MIN = 5  # Re-notifica cada 5 minutos hasta que diga "Hecho"

client = Groq(api_key=GROQ_KEY)

# ── Base de datos ──────────────────────────────────────────────
def cargar_tareas() -> list:
    if os.path.exists(TAREAS_FILE):
        with open(TAREAS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []

def guardar_tareas(tareas: list):
    with open(TAREAS_FILE, "w", encoding="utf-8") as f:
        json.dump(tareas, f, ensure_ascii=False, indent=2)

def cargar_rutina() -> list:
    if os.path.exists(RUTINA_FILE):
        with open(RUTINA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []

def guardar_rutina(rutina: list):
    with open(RUTINA_FILE, "w", encoding="utf-8") as f:
        json.dump(rutina, f, ensure_ascii=False, indent=2)

def siguiente_id(tareas: list) -> int:
    return max((t["id"] for t in tareas), default=0) + 1

def cargar_rutina_del_dia():
    """Carga la rutina fija en las tareas de hoy si aún no están."""
    rutina = cargar_rutina()
    if not rutina:
        return
    tareas = cargar_tareas()
    hoy = date.today().isoformat()
    tareas_hoy = [t["tarea"] for t in tareas if t.get("fecha") == hoy]
    nuevas = []
    for item in rutina:
        if item["tarea"] not in tareas_hoy:
            nuevas.append({
                "id": siguiente_id(tareas + nuevas),
                "tarea": item["tarea"],
                "hora": item["hora"],
                "completada": False,
                "fecha": hoy,
                "notificaciones_enviadas": 0,
                "es_rutina": True
            })
    if nuevas:
        tareas.extend(nuevas)
        guardar_tareas(tareas)

# ── IA con Groq ────────────────────────────────────────────────
def procesar_con_groq(mensaje: str, tareas: list, rutina: list) -> dict:
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
    tareas_resumen = [
        {"id": t["id"], "tarea": t["tarea"], "hora": t.get("hora"), "completada": t["completada"]}
        for t in tareas
    ]
    rutina_resumen = [{"tarea": r["tarea"], "hora": r["hora"]} for r in rutina]

    prompt = f"""Eres un asistente personal amigable que habla español.
Fecha y hora actual: {ahora}
Tareas de hoy: {json.dumps(tareas_resumen, ensure_ascii=False)}
Rutina fija: {json.dumps(rutina_resumen, ensure_ascii=False)}
El usuario dice: "{mensaje}"

Responde ÚNICAMENTE con JSON válido sin texto adicional:
{{"accion":"agregar|listar|completar|eliminar|guardar_rutina|ver_rutina|conversar","tarea":"descripcion","hora":"HH:MM o null","id":0,"rutina":[{{"tarea":"x","hora":"HH:MM"}}],"respuesta":"mensaje corto en español"}}

Reglas:
- "recuérdame X a las Y" → agregar
- "ya hice / hecho / listo" → completar con id correcto
- "qué tengo pendiente" → listar
- "mi rutina diaria es..." o "todos los días..." → guardar_rutina con array rutina
- "cuál es mi rutina" → ver_rutina
- otro → conversar
- Respuesta máximo 2 oraciones, cálida"""

    try:
        respuesta = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
            temperature=0.3
        )
        texto = respuesta.choices[0].message.content.strip()
        texto = re.sub(r"^```json\s*|\s*```$", "", texto, flags=re.MULTILINE).strip()
        return json.loads(texto)
    except Exception as e:
        return {"accion": "conversar", "respuesta": "Ups, tuve un problemita. ¿Puedes repetirme eso?"}

# ── Botones ────────────────────────────────────────────────────
def boton_hecho(tarea_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ ¡Hecho!", callback_data=f"completar_{tarea_id}"),
        InlineKeyboardButton("⏰ En 5 min", callback_data=f"posponer_{tarea_id}")
    ]])

# ── Handlers ───────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *¡Hola! Soy tu asistente personal.*\n\n"
        "Háblame natural:\n\n"
        "• _Recuérdame tomar agua a las 08:00_\n"
        "• _Tengo reunión a las 15:30_\n"
        "• _¿Qué tengo pendiente hoy?_\n"
        "• _Hecho_ (para marcar la última tarea)\n\n"
        "Para guardar tu rutina diaria dime:\n"
        "• _Mi rutina: despertar 07:00, ejercicio 08:00..._\n\n"
        "Comandos: /pendientes · /rutina",
        parse_mode="Markdown"
    )

async def cmd_pendientes(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tareas = cargar_tareas()
    hoy = date.today().isoformat()
    pendientes = [t for t in tareas if not t["completada"] and t.get("fecha", hoy) == hoy]
    if not pendientes:
        await update.message.reply_text("🎉 ¡No tienes pendientes para hoy!")
        return
    texto = "📋 *Tus pendientes de hoy:*\n\n"
    for t in pendientes:
        hora = t.get("hora") or "sin hora"
        texto += f"  #{t['id']} · {hora} → {t['tarea']}\n"
    await update.message.reply_text(texto, parse_mode="Markdown")

async def cmd_rutina(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rutina = cargar_rutina()
    if not rutina:
        await update.message.reply_text("No tienes rutina fija guardada. Dime tu rutina y la guardo 📝")
        return
    texto = "🔄 *Tu rutina diaria:*\n\n"
    for r in rutina:
        texto += f"  • {r['hora']} → {r['tarea']}\n"
    await update.message.reply_text(texto, parse_mode="Markdown")

async def manejar_mensaje(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tareas = cargar_tareas()
    rutina = cargar_rutina()
    resultado = procesar_con_groq(update.message.text, tareas, rutina)
    accion = resultado.get("accion")

    if accion == "agregar":
        tareas.append({
            "id": siguiente_id(tareas),
            "tarea": resultado.get("tarea", "Tarea sin nombre"),
            "hora": resultado.get("hora"),
            "completada": False,
            "fecha": date.today().isoformat(),
            "notificaciones_enviadas": 0
        })
        guardar_tareas(tareas)

    elif accion == "completar":
        tarea_id = resultado.get("id")
        for t in tareas:
            if t["id"] == tarea_id:
                t["completada"] = True
                break
        guardar_tareas(tareas)

    elif accion == "eliminar":
        tareas = [t for t in tareas if t["id"] != resultado.get("id")]
        guardar_tareas(tareas)

    elif accion == "guardar_rutina":
        nueva_rutina = resultado.get("rutina", [])
        if nueva_rutina:
            guardar_rutina(nueva_rutina)
            cargar_rutina_del_dia()

    await update.message.reply_text(resultado.get("respuesta", "Entendido ✅"), parse_mode="Markdown")

async def manejar_boton(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    accion, tarea_id_str = query.data.split("_", 1)
    tarea_id = int(tarea_id_str)
    tareas = cargar_tareas()

    if accion == "completar":
        nombre = ""
        for t in tareas:
            if t["id"] == tarea_id:
                t["completada"] = True
                nombre = t["tarea"]
                break
        guardar_tareas(tareas)
        await query.edit_message_text(f"✅ *¡Perfecto! '{nombre}' completada.* 🎉", parse_mode="Markdown")

    elif accion == "posponer":
        nombre = ""
        for t in tareas:
            if t["id"] == tarea_id:
                t["posponer_hasta"] = datetime.now().timestamp() + RENOTIFICAR_MIN * 60
                nombre = t["tarea"]
                break
        guardar_tareas(tareas)
        await query.edit_message_text(f"⏰ Te recuerdo *'{nombre}'* en {RENOTIFICAR_MIN} min.", parse_mode="Markdown")

# ── Recordatorios automáticos ──────────────────────────────────
async def loop_recordatorios(app: Application):
    while True:
        await asyncio.sleep(60)
        ahora = datetime.now()
        hora_actual = ahora.strftime("%H:%M")
        hoy = date.today().isoformat()

        # Cargar rutina al inicio del día
        cargar_rutina_del_dia()

        tareas = cargar_tareas()
        cambios = False

        for t in tareas:
            if t["completada"] or t.get("fecha", hoy) != hoy:
                continue
            hora_tarea = t.get("hora")
            if not hora_tarea:
                continue

            ya_notificado = t.get("notificaciones_enviadas", 0) > 0
            ahora_ts = ahora.timestamp()

            # Primera notificación
            if hora_tarea == hora_actual and not ya_notificado:
                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"⏰ *Recordatorio:* {t['tarea']}",
                    reply_markup=boton_hecho(t["id"]),
                    parse_mode="Markdown"
                )
                t["notificaciones_enviadas"] = 1
                t["ultima_notificacion_ts"] = ahora_ts
                cambios = True

            # Re-notificación cada 5 min hasta que confirme
            elif ya_notificado and hora_tarea <= hora_actual:
                posponer_hasta = t.get("posponer_hasta", 0)
                if posponer_hasta and ahora_ts < posponer_hasta:
                    continue
                if (ahora_ts - t.get("ultima_notificacion_ts", 0)) / 60 >= RENOTIFICAR_MIN:
                    veces = t["notificaciones_enviadas"]
                    frases = [
                        f"👋 Oye, ¿ya hiciste: *{t['tarea']}*?",
                        f"🔔 Sigo esperando tu confirmación: *{t['tarea']}*",
                        f"📣 ¡Ey! ¿Ya hiciste: *{t['tarea']}*?",
                        f"⚡ Te sigo recordando: *{t['tarea']}* — toca ✅ cuando lo hayas hecho",
                    ]
                    await app.bot.send_message(
                        chat_id=CHAT_ID,
                        text=frases[min(veces - 1, 3)],
                        reply_markup=boton_hecho(t["id"]),
                        parse_mode="Markdown"
                    )
                    t["notificaciones_enviadas"] = veces + 1
                    t["ultima_notificacion_ts"] = ahora_ts
                    t.pop("posponer_hasta", None)
                    cambios = True

        if cambios:
            guardar_tareas(tareas)

# ── Resumen matutino ───────────────────────────────────────────
async def loop_resumen_diario(app: Application):
    ultima_fecha = None
    while True:
        await asyncio.sleep(60)
        ahora = datetime.now()
        if ahora.strftime("%H:%M") == "08:00" and ahora.date() != ultima_fecha:
            cargar_rutina_del_dia()
            tareas = cargar_tareas()
            hoy = ahora.date().isoformat()
            pendientes = [t for t in tareas if not t["completada"] and t.get("fecha", hoy) == hoy]
            if pendientes:
                texto = "🌅 *¡Buenos días! Tu agenda de hoy:*\n\n"
                for t in pendientes:
                    hora = t.get("hora") or "sin hora"
                    texto += f"  • {hora} — {t['tarea']}\n"
                texto += "\n¡Mucho éxito! 💪"
            else:
                texto = "🌅 *¡Buenos días!* No tienes tareas hoy. ¡Disfruta! 🎉"
            await app.bot.send_message(chat_id=CHAT_ID, text=texto, parse_mode="Markdown")
            ultima_fecha = ahora.date()

# ── Main ───────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("pendientes", cmd_pendientes))
    app.add_handler(CommandHandler("rutina", cmd_rutina))
    app.add_handler(CallbackQueryHandler(manejar_boton))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

    async def post_init(application: Application):
        asyncio.create_task(loop_recordatorios(application))
        asyncio.create_task(loop_resumen_diario(application))

    app.post_init = post_init
    print("🤖 Bot iniciado. Esperando mensajes...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
