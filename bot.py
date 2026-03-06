"""
Asistente Personal - Bot de Telegram con Google Gemini (GRATIS)
===============================================================
Variables de entorno necesarias en Railway:
  TELEGRAM_TOKEN  → Token del bot (de @BotFather)
  GEMINI_KEY      → API Key de Google Gemini (gratis)
  CHAT_ID         → Tu ID numérico de Telegram
"""

import os
import json
import asyncio
import re
from datetime import datetime, date
import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)

TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY      = os.getenv("GEMINI_KEY")
CHAT_ID         = os.getenv("CHAT_ID")
TAREAS_FILE     = "tareas.json"
RENOTIFICAR_MIN = 15

genai.configure(api_key=GEMINI_KEY)
modelo = genai.GenerativeModel("gemini-1.5-flash")

def cargar_tareas() -> list:
    if os.path.exists(TAREAS_FILE):
        with open(TAREAS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []

def guardar_tareas(tareas: list):
    with open(TAREAS_FILE, "w", encoding="utf-8") as f:
        json.dump(tareas, f, ensure_ascii=False, indent=2)

def siguiente_id(tareas: list) -> int:
    return max((t["id"] for t in tareas), default=0) + 1

def procesar_con_gemini(mensaje: str, tareas: list) -> dict:
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
    tareas_resumen = [
        {"id": t["id"], "tarea": t["tarea"], "hora": t.get("hora"), "completada": t["completada"]}
        for t in tareas
    ]
    prompt = f"""Eres un asistente personal amigable que habla español.
Fecha y hora actual: {ahora}
Tareas actuales: {json.dumps(tareas_resumen, ensure_ascii=False)}
El usuario dice: "{mensaje}"

Responde ÚNICAMENTE con JSON válido, sin texto adicional ni comillas de código:
{{"accion": "agregar"|"listar"|"completar"|"eliminar"|"conversar","tarea":"(si agregar)","hora":"HH:MM o null","id":0,"respuesta":"mensaje amigable corto en español"}}

Reglas:
- "recuérdame X a las Y" → agregar con hora
- "tengo que hacer X" sin hora → agregar hora=null  
- "ya hice" o "listo" → completar
- "qué tengo pendiente" → listar
- otro → conversar"""

    try:
        respuesta = modelo.generate_content(prompt)
        texto = respuesta.text.strip()
        texto = re.sub(r"^```json\s*|\s*```$", "", texto, flags=re.MULTILINE).strip()
        return json.loads(texto)
    except Exception as e:
        return {"accion": "conversar", "respuesta": f"Ups, tuve un problemita. ¿Puedes repetirme eso?"}

def boton_completar(tarea_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ ¡Ya lo hice!", callback_data=f"completar_{tarea_id}"),
        InlineKeyboardButton("⏰ En 15 min", callback_data=f"posponer_{tarea_id}")
    ]])

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *¡Hola! Soy tu asistente personal.*\n\n"
        "Háblame natural:\n\n"
        "• _Recuérdame tomar agua a las 08:00_\n"
        "• _Tengo reunión a las 15:30_\n"
        "• _¿Qué tengo pendiente hoy?_\n"
        "• _Ya hice la reunión_\n\n"
        "Usa /pendientes para ver tu lista 📋",
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

async def manejar_mensaje(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    tareas = cargar_tareas()
    resultado = procesar_con_gemini(update.message.text, tareas)
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
        for t in tareas:
            if t["id"] == resultado.get("id"):
                t["completada"] = True
                break
        guardar_tareas(tareas)
    elif accion == "eliminar":
        tareas = [t for t in tareas if t["id"] != resultado.get("id")]
        guardar_tareas(tareas)
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

async def loop_recordatorios(app: Application):
    while True:
        await asyncio.sleep(60)
        ahora = datetime.now()
        hora_actual = ahora.strftime("%H:%M")
        hoy = date.today().isoformat()
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
            if hora_tarea == hora_actual and not ya_notificado:
                await app.bot.send_message(chat_id=CHAT_ID, text=f"⏰ *Recordatorio:* {t['tarea']}", reply_markup=boton_completar(t["id"]), parse_mode="Markdown")
                t["notificaciones_enviadas"] = 1
                t["ultima_notificacion_ts"] = ahora_ts
                cambios = True
            elif ya_notificado and hora_tarea <= hora_actual:
                posponer_hasta = t.get("posponer_hasta", 0)
                if posponer_hasta and ahora_ts < posponer_hasta:
                    continue
                if (ahora_ts - t.get("ultima_notificacion_ts", 0)) / 60 >= RENOTIFICAR_MIN:
                    veces = t["notificaciones_enviadas"]
                    frases = [f"👋 Oye, ¿ya hiciste: *{t['tarea']}*?", f"🔔 Sigo esperando: *{t['tarea']}*", f"📣 ¿Ya estuvo: *{t['tarea']}*?", f"⚡ ¡Ey! *{t['tarea']}* — ¿ya lo hiciste?"]
                    await app.bot.send_message(chat_id=CHAT_ID, text=frases[min(veces-1, 3)], reply_markup=boton_completar(t["id"]), parse_mode="Markdown")
                    t["notificaciones_enviadas"] = veces + 1
                    t["ultima_notificacion_ts"] = ahora_ts
                    t.pop("posponer_hasta", None)
                    cambios = True
        if cambios:
            guardar_tareas(tareas)

async def loop_resumen_diario(app: Application):
    ultima_fecha = None
    while True:
        await asyncio.sleep(60)
        ahora = datetime.now()
        if ahora.strftime("%H:%M") == "08:00" and ahora.date() != ultima_fecha:
            tareas = cargar_tareas()
            hoy = ahora.date().isoformat()
            pendientes = [t for t in tareas if not t["completada"] and t.get("fecha", hoy) == hoy]
            if pendientes:
                texto = "🌅 *¡Buenos días! Tu agenda de hoy:*\n\n" + "".join(f"  • {t.get('hora','sin hora')} — {t['tarea']}\n" for t in pendientes) + "\n¡Mucho éxito! 💪"
            else:
                texto = "🌅 *¡Buenos días!* No tienes tareas hoy. ¡Disfruta! 🎉"
            await app.bot.send_message(chat_id=CHAT_ID, text=texto, parse_mode="Markdown")
            ultima_fecha = ahora.date()

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("pendientes", cmd_pendientes))
    app.add_handler(CallbackQueryHandler(manejar_boton))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    async def post_init(application: Application):
        asyncio.create_task(loop_recordatorios(application))
        asyncio.create_task(loop_resumen_diario(application))
    app.post_init = post_init
    print("🤖 Bot iniciado con Gemini. Esperando mensajes...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
