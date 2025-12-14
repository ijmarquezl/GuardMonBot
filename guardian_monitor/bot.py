import os
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from dotenv import load_dotenv
from guardian_monitor.graph import create_graph

load_dotenv()

# Global event for approval waiting
approval_event = asyncio.Event()
# Global state to store the user's decision
user_decision = False
# Reference to the latest metrics for /status
latest_metrics = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Guardian Bot Started! Use /status to check system.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not latest_metrics:
        await update.message.reply_text("No metrics available yet.")
        return
        
    msg = "📊 *System Status*\n"
    for k, v in latest_metrics.items():
        msg += f"- *{k}*: `{v}`\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global user_decision
    query = update.callback_query
    
    try:
        await query.answer()
        
        if query.data == "approve":
            user_decision = True
            await query.edit_message_text(text=f"✅ Action Approved: {query.message.text}")
        elif query.data == "deny":
            user_decision = False
            await query.edit_message_text(text=f"❌ Action Denied: {query.message.text}")
            
    except Exception as e:
        print(f"Error in button_handler: {e}")
        # Even if UI fails to update, we should release the lock if we got the data
        # But we only know data if we got here.
        pass
        
    approval_event.set()

async def send_approval_request(diagnosis: str, action: str):
    """
    Sends a message with Inline buttons and waits for the user to click.
    """
    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        print("TELEGRAM_TOKEN or TELEGRAM_CHAT_ID missing. Auto-denying.")
        return False

    if BotGlobals.app is None:
        print("Bot application not initialized.")
        return False

    keyboard = [
        [
            InlineKeyboardButton("Approve", callback_data="approve"),
            InlineKeyboardButton("Deny", callback_data="deny"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    msg_text = f"🚨 *Issue Detected*\n\nDiagnosis: {diagnosis}\n\nProposed Action: `{action}`"
    
    approval_event.clear()
    
    approval_event.clear()
    
    await send_safe_message(chat_id, msg_text, reply_markup=reply_markup)
    
    # Wait for the button handler to set the event
    
    # Wait for the button handler to set the event
    print("Waiting for Telegram response...")
    try:
        # Wait max 120 seconds for approval to avoid blocking forever
        await asyncio.wait_for(approval_event.wait(), timeout=120)
        return user_decision
    except asyncio.TimeoutError:
        print("Telegram approval timed out.")
        return False

class BotGlobals:
    app = None
    manual_trigger = asyncio.Event()
    graph = None

def create_bot_app():
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        print("Warning: No TELEGRAM_TOKEN. Bot will not start.")
        return None
        
    app = ApplicationBuilder().token(token).connect_timeout(30.0).read_timeout(30.0).write_timeout(30.0).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    # Add Chat Handler
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        print(f"Update {update} caused error {context.error}")

    app.add_error_handler(error_handler)

    BotGlobals.app = app
    BotGlobals.graph = create_graph()
    return app

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handles natural language messages from the user.
    """
    user_message = update.message.text
    chat_id = update.effective_chat.id
    
    # Check whitelist (optional but good practice)
    env_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if str(chat_id) != str(env_chat_id):
        return

    # Check for manual trigger keywords
    triggers = ["diagnose", "scan", "check", "analiza", "revisa"]
    if any(t in user_message.lower() for t in triggers):
        await update.message.reply_text("🔎 Starting manual diagnosis...", parse_mode="Markdown")
        BotGlobals.manual_trigger.set()
        return

    # Indicate typing
    # Indicate typing (non-blocking)
    try:
        await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    except Exception as e:
        print(f"Warning: Failed to send typing action: {e}")
    
    try:
        if BotGlobals.graph is None:
             BotGlobals.graph = create_graph()

        print(f"Invoking Agent with: {user_message}")
        # Invoke Graph
        inputs = {"messages": [("user", user_message)]}
        # Use ainvoke
        response = await BotGlobals.graph.ainvoke(inputs)
        
        # Get final message
        final_message = response["messages"][-1].content
        
        await send_safe_message(chat_id, final_message)
        

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Chat Error: {e}")
        await update.message.reply_text(f"😴 My AI brain is offline right now. Error: {e}")

async def send_safe_message(chat_id: str, text: str, reply_markup=None):
    """
    Sends a message trying Markdown first, falling back to plain text if parsing fails.
    """
    if not BotGlobals.app:
        return

    try:
        await BotGlobals.app.bot.send_message(
            chat_id=chat_id, 
            text=text, 
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
    except Exception as e:
        print(f"Markdown failed, sending plain text: {e}")
        try:
            await BotGlobals.app.bot.send_message(
                chat_id=chat_id, 
                text=text, 
                reply_markup=reply_markup
                # No parse_mode
            )
        except Exception as e2:
             print(f"Failed to send message: {e2}")

async def send_execution_result(command: str, result: str):
    """
    Sends the execution result to Telegram using safe message.
    """
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        return
        
    # Truncate result if too long to avoid Telegram limits
    if len(result) > 4000:
        result = result[:4000] + "\n...(truncated)"
        
    text = f"💻 *Executed*: `{command}`\n\n📄 *Output*:\n```\n{result}\n```"
    await send_safe_message(chat_id, text)
