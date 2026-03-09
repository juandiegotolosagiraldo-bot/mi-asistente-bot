"""
Asistente Personal - Bot de Telegram con Groq (GRATIS)
======================================================
Variables de entorno necesarias en Railway:
  TELEGRAM_TOKEN  → Token del bot (de @BotFather)
  GROQ_KEY        → API Key de Groq (gratis)
  CHAT_ID         → Tu ID numérico de Telegram
  TZ              → Europe/Berlin

CAMBIO: Sistema de recordatorios simplificado
  - Sin botones de confirmación
  - Sin 3 confirmaciones
  - Solo: recordatorio a la hora + último aviso a los 10 min
  - Tú marcas como hecho escribiendo "hecho" o "listo"
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
                "recordatorio_enviado": False,
                "ultimo_aviso_enviado": False,
                "ultima_notificacion_ts": 0,
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
- "ya hice / hecho / listo / confirmado / done" → completar con id correcto
- "qué tengo pendiente" → listar
- "mi rutina diaria es..." → guardar_rutina con array rutina
- "cuál es mi rutina" → ver_rutina
- otro → conversar"""

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
    except Exception:
        return {"accion": "conversar", "respuesta": "Ups, tuve un problemita. ¿Puedes repetirme eso?"}

# ── Handlers ───────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *¡Hola! Soy tu asistente personal.*\n\n"
        "Háblame natural:\n"
        "• _Recuérdame tomar agua a las 08:00_\n"
        "• _Tengo reunión a las 15:30_\n"
        "• _¿Qué tengo pendiente hoy?_\n\n"
        "Para marcar como hecho:\n"
        "• _Hecho_ · _Listo_ · _Ya lo hice_\n\n"
        "Para tu rutina:\n"
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
        await update.message.reply_text("No tienes rutina guardada. Dime tu rutina y la guardo 📝")
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
            "recordatorio_enviado": False,
            "ultimo_aviso_enviado": False,
            "ultima_notificacion_ts": 0,
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

    elif accion == "guardar_rutina":
        nueva_rutina = resultado.get("rutina", [])
        if nueva_rutina:
            guardar_rutina(nueva_rutina)
            cargar_rutina_del_dia()

    await update.message.reply_text(resultado.get("respuesta", "Entendido ✅"), parse_mode="Markdown")

# ── Recordatorios automáticos — SIMPLIFICADOS ─────────────────
# Flujo nuevo:
#   1. A la hora exacta → "⏰ Recuerda: [tarea]"  (sin botones)
#   2. 10 minutos después → "🔔 Último recordatorio: [tarea]"  (sin botones)
#   3. Si escribes "hecho" o "listo" → se marca completada
#   Sin más mensajes. Sin confirmaciones. Sin botones.
# ──────────────────────────────────────────────────────────────

async def loop_recordatorios(app: Application):
    while True:
        await asyncio.sleep(60)
        ahora    = datetime.now()
        hora_actual = ahora.strftime("%H:%M")
        hoy      = date.today().isoformat()

        cargar_rutina_del_dia()
        tareas   = cargar_tareas()
        cambios  = False

        for t in tareas:
            if t["completada"] or t.get("fecha", hoy) != hoy:
                continue
            hora_tarea = t.get("hora")
            if not hora_tarea:
                continue

            ahora_ts = ahora.timestamp()
            mins_desde_primera = (ahora_ts - t.get("ultima_notificacion_ts", 0)) / 60

            # ── Recordatorio 1: a la hora exacta ──────────────
            if hora_tarea == hora_actual and not t.get("recordatorio_enviado"):
                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"⏰ Recuerda: *{t['tarea']}*",
                    parse_mode="Markdown"
                )
                t["recordatorio_enviado"]  = True
                t["ultimo_aviso_enviado"]  = False
                t["ultima_notificacion_ts"] = ahora_ts
                cambios = True

            # ── Recordatorio 2: último aviso 10 min después ───
            elif (t.get("recordatorio_enviado") and
                  not t.get("ultimo_aviso_enviado") and
                  mins_desde_primera >= 10):
                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"🔔 Último recordatorio: *{t['tarea']}*",
                    parse_mode="Markdown"
                )
                t["ultimo_aviso_enviado"] = True
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))

    async def post_init(application: Application):
        asyncio.create_task(loop_recordatorios(application))
        asyncio.create_task(loop_resumen_diario(application))

    app.post_init = post_init
    print("🤖 Bot iniciado. Esperando mensajes...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
