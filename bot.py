
"""
Asistente Personal - Bot de Telegram con Groq (GRATIS)
======================================================
Variables de entorno necesarias en Railway:
  TELEGRAM_TOKEN  → Token del bot (de @BotFather)
  GROQ_KEY        → API Key de Groq (gratis)
  CHAT_ID         → Tu ID numérico de Telegram
  TZ              → Europe/Berlin
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
INTERVALO_MIN   = 5  # Minutos entre cada confirmación

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
                "confirmaciones": 0,  # 0=sin iniciar, 1=primer hecho, 2=segundo, 3=completado
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
- "ya hice / hecho / listo / confirmado" → completar con id correcto
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

# ── Botones según nivel de confirmación ───────────────────────
def boton_confirmacion(tarea_id: int, nivel: int) -> InlineKeyboardMarkup:
    """
    nivel 0 → primera notificación
    nivel 1 → segunda confirmación
    nivel 2 → confirmación final
    """
    textos = [
        "✅ ¡Hecho!",
        "✅ ¡Sí, lo hice!",
        "✅ ¡Confirmado definitivamente!"
    ]
    label = textos[min(nivel, 2)]
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(label, callback_data=f"confirmar_{tarea_id}_{nivel}"),
        InlineKeyboardButton("⏰ En 5 min", callback_data=f"posponer_{tarea_id}")
    ]])

# ── Handlers ───────────────────────────────────────────────────
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *¡Hola! Soy tu asistente personal.*\n\n"
        "Háblame natural:\n"
        "• _Recuérdame tomar agua a las 08:00_\n"
        "• _Tengo reunión a las 15:30_\n"
        "• _¿Qué tengo pendiente hoy?_\n\n"
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
        conf = t.get("confirmaciones", 0)
        estado = f"({conf}/3 ✓)" if conf > 0 else ""
        texto += f"  #{t['id']} · {hora} → {t['tarea']} {estado}\n"
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
            "confirmaciones": 0,
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

    elif accion == "guardar_rutina":
        nueva_rutina = resultado.get("rutina", [])
        if nueva_rutina:
            guardar_rutina(nueva_rutina)
            cargar_rutina_del_dia()

    await update.message.reply_text(resultado.get("respuesta", "Entendido ✅"), parse_mode="Markdown")

async def manejar_boton(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    tareas = cargar_tareas()

    if data.startswith("confirmar_"):
        partes = data.split("_")
        tarea_id = int(partes[1])
        nivel = int(partes[2])
        nombre = ""

        for t in tareas:
            if t["id"] == tarea_id:
                nombre = t["tarea"]
                nuevo_nivel = nivel + 1
                t["confirmaciones"] = nuevo_nivel
                t["ultima_notificacion_ts"] = datetime.now().timestamp()

                if nuevo_nivel >= 3:
                    # ✅ Completado definitivamente
                    t["completada"] = True
                    await query.edit_message_text(
                        f"🎉 *¡Excelente! '{nombre}' completada definitivamente.*\n¡Buen trabajo! 💪",
                        parse_mode="Markdown"
                    )
                elif nuevo_nivel == 1:
                    await query.edit_message_text(
                        f"👍 Bien. En 5 minutos te pregunto de nuevo para confirmar que *'{nombre}'* sigue hecho.",
                        parse_mode="Markdown"
                    )
                elif nuevo_nivel == 2:
                    await query.edit_message_text(
                        f"👍 Casi listo. En 5 minutos te pido la *confirmación final* de *'{nombre}'*.",
                        parse_mode="Markdown"
                    )
                break

        guardar_tareas(tareas)

    elif data.startswith("posponer_"):
        tarea_id = int(data.split("_")[1])
        nombre = ""
        for t in tareas:
            if t["id"] == tarea_id:
                t["posponer_hasta"] = datetime.now().timestamp() + INTERVALO_MIN * 60
                nombre = t["tarea"]
                break
        guardar_tareas(tareas)
        await query.edit_message_text(
            f"⏰ Te recuerdo *'{nombre}'* en {INTERVALO_MIN} min.",
            parse_mode="Markdown"
        )

# ── Recordatorios automáticos ──────────────────────────────────
async def loop_recordatorios(app: Application):
    while True:
        await asyncio.sleep(60)
        ahora = datetime.now()
        hora_actual = ahora.strftime("%H:%M")
        hoy = date.today().isoformat()

        cargar_rutina_del_dia()
        tareas = cargar_tareas()
        cambios = False

        for t in tareas:
            if t["completada"] or t.get("fecha", hoy) != hoy:
                continue
            hora_tarea = t.get("hora")
            if not hora_tarea:
                continue

            ahora_ts = ahora.timestamp()
            confirmaciones = t.get("confirmaciones", 0)
            ya_notificado = t.get("notificaciones_enviadas", 0) > 0
            posponer_hasta = t.get("posponer_hasta", 0)

            if posponer_hasta and ahora_ts < posponer_hasta:
                continue

            mins_desde_ultima = (ahora_ts - t.get("ultima_notificacion_ts", 0)) / 60

            # Primera notificación — hora exacta
            if hora_tarea == hora_actual and not ya_notificado:
                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"⏰ *Es hora de:* {t['tarea']}",
                    reply_markup=boton_confirmacion(t["id"], 0),
                    parse_mode="Markdown"
                )
                t["notificaciones_enviadas"] = 1
                t["ultima_notificacion_ts"] = ahora_ts
                cambios = True

            # Confirmación 2 — 5 min después del primer "hecho"
            elif confirmaciones == 1 and mins_desde_ultima >= INTERVALO_MIN:
                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"🔔 *Segunda confirmación:* ¿Sigues habiendo hecho *{t['tarea']}*?",
                    reply_markup=boton_confirmacion(t["id"], 1),
                    parse_mode="Markdown"
                )
                t["ultima_notificacion_ts"] = ahora_ts
                cambios = True

            # Confirmación 3 — 5 min después de la segunda
            elif confirmaciones == 2 and mins_desde_ultima >= INTERVALO_MIN:
                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=f"✅ *Confirmación final:* ¿Confirmas definitivamente que hiciste *{t['tarea']}*?",
                    reply_markup=boton_confirmacion(t["id"], 2),
                    parse_mode="Markdown"
                )
                t["ultima_notificacion_ts"] = ahora_ts
                cambios = True

            # Si no ha respondido nada, re-notificar cada 5 min
            elif ya_notificado and confirmaciones == 0 and hora_tarea <= hora_actual and mins_desde_ultima >= INTERVALO_MIN:
                veces = t["notificaciones_enviadas"]
                frases = [
                    f"👋 Oye, ¿ya hiciste: *{t['tarea']}*?",
                    f"🔔 Sigo esperando tu confirmación: *{t['tarea']}*",
                    f"📣 ¡Ey! ¿Ya lo hiciste: *{t['tarea']}*?",
                    f"⚡ Te sigo recordando: *{t['tarea']}*",
                ]
                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=frases[min(veces - 1, 3)],
                    reply_markup=boton_confirmacion(t["id"], 0),
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
