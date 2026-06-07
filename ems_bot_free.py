import os
import json
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler, ContextTypes, filters
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request
import gspread
from gspread.exceptions import SpreadsheetNotFound
import google.generativeai as genai

# Load environment variables
load_dotenv()

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize clients
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
GOOGLE_CREDS_JSON = os.getenv('GOOGLE_CREDS_JSON')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
SPREADSHEET_NAME = 'EMS_Expenses_2026'

# Initialize Gemini
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Google Sheets setup
def get_google_sheets():
    try:
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        credentials = Credentials.from_service_account_info(
            creds_dict,
            scopes=['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        )
        gc = gspread.authorize(credentials)
        return gc
    except Exception as e:
        logger.error(f"Google Sheets error: {e}")
        return None

# Conversation states
ADD_EXPENSE, SELECT_CATEGORY, ENTER_AMOUNT, ENTER_DESCRIPTION = range(4)
SPLIT_AMOUNT, SPLIT_PEOPLE = range(4, 6)
SET_BUDGET_CATEGORY, SET_BUDGET_AMOUNT = range(6, 8)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Hi {user.first_name}! I'm **Ems AI**, your personal finance assistant.\n\n"
        "I help you:\n"
        "💰 Track expenses\n"
        "🧮 Split bills\n"
        "📊 Monitor spending\n"
        "💡 Save money\n\n"
        "Use /help to see all commands!",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    help_text = """
🤖 **Ems AI Commands:**

📝 **Expense Tracking:**
/add - Add a new expense
/list - View recent expenses
/summary - Get monthly summary

🧮 **Bill Splitting:**
/split - Split a bill with friends

💰 **Budget Management:**
/setbudget - Set monthly budget for category
/viewbudget - View all budgets

📊 **Analytics:**
/tips - Get money-saving tips
/spending - See spending breakdown

🔧 **Other:**
/help - Show this message
/reset - Clear all data (careful!)

**Quick Tips:**
• Type: "Food 50" to quickly add expense
• Use /split to calculate bill splits
• Set budgets to track spending goals
"""
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def add_expense_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start adding expense"""
    categories = [
        ['🍽️ Food & Dining', '🚗 Transport'],
        ['🎬 Entertainment', '🛍️ Shopping'],
        ['💡 Utilities', '📱 Other']
    ]
    reply_markup = ReplyKeyboardMarkup(categories, one_time_keyboard=True)
    
    await update.message.reply_text(
        "📝 **Add Expense**\n\nSelect a category:",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )
    return SELECT_CATEGORY

async def select_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle category selection"""
    text = update.message.text
    # Extract category name (remove emoji)
    category = ' '.join(text.split()[1:]) if len(text.split()) > 1 else text
    context.user_data['category'] = category
    
    await update.message.reply_text(
        f"💵 Enter amount (RM): ",
        reply_markup=ReplyKeyboardRemove()
    )
    return ENTER_AMOUNT

async def enter_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle amount input"""
    try:
        amount = float(update.message.text)
        if amount <= 0:
            await update.message.reply_text("❌ Amount must be greater than 0")
            return ENTER_AMOUNT
        
        context.user_data['amount'] = amount
        await update.message.reply_text(f"📝 Description (e.g., Lunch at restaurant):")
        return ENTER_DESCRIPTION
    except ValueError:
        await update.message.reply_text("❌ Please enter a valid number")
        return ENTER_AMOUNT

async def enter_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle description and save expense"""
    description = update.message.text
    
    category = context.user_data.get('category', 'Other')
    amount = context.user_data.get('amount', 0)
    user_id = update.effective_user.id
    
    # Save to Google Sheets
    success = await save_expense_to_sheets(user_id, category, amount, description)
    
    if success:
        await update.message.reply_text(
            f"✅ **Expense Saved!**\n"
            f"Category: {category}\n"
            f"Amount: RM {amount:.2f}\n"
            f"Description: {description}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ Failed to save expense. Try again later.")
    
    return ConversationHandler.END

async def save_expense_to_sheets(user_id, category, amount, description):
    """Save expense to Google Sheets"""
    try:
        gc = get_google_sheets()
        if not gc:
            return False
        
        # Open or create spreadsheet
        try:
            sh = gc.open(SPREADSHEET_NAME)
        except SpreadsheetNotFound:
            sh = gc.create(SPREADSHEET_NAME)
            sh.share('', perm_type='anyone', role='reader')
        
        # Get or create worksheet for current month
        current_month = datetime.now().strftime('%B %Y')
        
        try:
            worksheet = sh.worksheet(current_month)
        except:
            worksheet = sh.add_worksheet(title=current_month, rows=100, cols=6)
            # Add headers
            worksheet.append_row(['Date', 'Category', 'Amount (RM)', 'Description', 'User', 'Time'])
        
        # Append expense
        date = datetime.now().strftime('%Y-%m-%d')
        time = datetime.now().strftime('%H:%M:%S')
        worksheet.append_row([date, category, amount, description, user_id, time])
        
        return True
    except Exception as e:
        logger.error(f"Error saving to sheets: {e}")
        return False

async def split_bill_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start bill split"""
    await update.message.reply_text(
        "💵 Enter total bill amount (RM):"
    )
    return SPLIT_AMOUNT

async def split_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get split amount"""
    try:
        amount = float(update.message.text)
        context.user_data['bill_amount'] = amount
        await update.message.reply_text("👥 Number of people:")
        return SPLIT_PEOPLE
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Try again:")
        return SPLIT_AMOUNT

async def split_people(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Calculate split"""
    try:
        people = int(update.message.text)
        if people < 2:
            await update.message.reply_text("❌ Need at least 2 people")
            return SPLIT_PEOPLE
        
        amount = context.user_data.get('bill_amount', 0)
        per_person = amount / people
        
        await update.message.reply_text(
            f"🧮 **Bill Split**\n"
            f"Total: RM {amount:.2f}\n"
            f"People: {people}\n"
            f"Per person: **RM {per_person:.2f}**",
            parse_mode='Markdown'
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Invalid number. Try again:")
        return SPLIT_PEOPLE

async def list_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List recent expenses"""
    try:
        gc = get_google_sheets()
        if not gc:
            await update.message.reply_text("❌ Cannot connect to Google Sheets")
            return
        
        sh = gc.open(SPREADSHEET_NAME)
        current_month = datetime.now().strftime('%B %Y')
        
        try:
            worksheet = sh.worksheet(current_month)
            values = worksheet.get_all_values()
            
            if len(values) <= 1:
                await update.message.reply_text("📊 No expenses this month yet")
                return
            
            # Get last 10 expenses
            expenses_text = "📊 **Recent Expenses:**\n\n"
            for row in values[-10:][::-1]:
                if len(row) >= 4:
                    expenses_text += f"• {row[1]}: RM {row[2]} - {row[3]}\n"
            
            await update.message.reply_text(expenses_text, parse_mode='Markdown')
        except:
            await update.message.reply_text("📊 No expenses found this month")
    except Exception as e:
        logger.error(f"Error listing expenses: {e}")
        await update.message.reply_text("❌ Error retrieving expenses")

async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Monthly summary"""
    try:
        gc = get_google_sheets()
        if not gc:
            await update.message.reply_text("❌ Cannot connect to Google Sheets")
            return
        
        sh = gc.open(SPREADSHEET_NAME)
        current_month = datetime.now().strftime('%B %Y')
        
        try:
            worksheet = sh.worksheet(current_month)
            values = worksheet.get_all_values()
            
            if len(values) <= 1:
                await update.message.reply_text("📊 No expenses this month yet")
                return
            
            # Calculate totals by category
            category_totals = {}
            grand_total = 0
            
            for row in values[1:]:  # Skip header
                if len(row) >= 3:
                    try:
                        category = row[1]
                        amount = float(row[2])
                        category_totals[category] = category_totals.get(category, 0) + amount
                        grand_total += amount
                    except:
                        pass
            
            summary_text = f"📊 **{current_month} Summary**\n\n"
            for category, total in sorted(category_totals.items(), key=lambda x: x[1], reverse=True):
                percentage = (total / grand_total * 100) if grand_total > 0 else 0
                summary_text += f"{category}: RM {total:.2f} ({percentage:.1f}%)\n"
            
            summary_text += f"\n**Total: RM {grand_total:.2f}**"
            
            await update.message.reply_text(summary_text, parse_mode='Markdown')
        except:
            await update.message.reply_text("📊 No data available")
    except Exception as e:
        logger.error(f"Error in summary: {e}")
        await update.message.reply_text("❌ Error generating summary")

async def get_tips(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get AI-powered money-saving tips using Gemini"""
    try:
        gc = get_google_sheets()
        if not gc:
            await update.message.reply_text("💡 Unable to connect to Google Sheets for analysis")
            return
        
        sh = gc.open(SPREADSHEET_NAME)
        current_month = datetime.now().strftime('%B %Y')
        
        try:
            worksheet = sh.worksheet(current_month)
            values = worksheet.get_all_values()
            
            # Prepare spending data for AI
            expenses_data = []
            for row in values[1:]:
                if len(row) >= 4:
                    expenses_data.append(f"{row[1]}: RM {row[2]} - {row[3]}")
            
            if not expenses_data:
                await update.message.reply_text("💡 Add some expenses first to get personalized tips!")
                return
            
            # Ask Gemini for tips
            prompt = f"""You are Ems AI, a friendly personal finance advisor. Analyze the user's spending and provide 2-3 specific, actionable money-saving tips. Be encouraging and practical. Keep response under 200 words.

User's expenses this month:
{chr(10).join(expenses_data)}

Give specific tips to save money."""
            
            response = model.generate_content(prompt)
            
            tips_text = f"💡 **Money-Saving Tips**\n\n{response.text}"
            await update.message.reply_text(tips_text, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error processing expenses: {e}")
            await update.message.reply_text("💡 No data yet. Add expenses to get personalized tips!")
    except Exception as e:
        logger.error(f"Error getting tips: {e}")
        await update.message.reply_text("💡 Unable to generate tips right now")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle quick expense entry"""
    text = update.message.text.strip()
    
    # Format: "Category Amount" or "Amount Category"
    parts = text.split()
    
    if len(parts) >= 2:
        try:
            # Try to parse as "Food 50" or "50 Food"
            amount = None
            category = None
            
            for part in parts:
                try:
                    amount = float(part)
                except:
                    if not category:
                        category = part
                    else:
                        category += f" {part}"
            
            if amount and category:
                success = await save_expense_to_sheets(
                    update.effective_user.id,
                    category,
                    amount,
                    text
                )
                
                if success:
                    await update.message.reply_text(
                        f"✅ Logged: {category} - RM {amount:.2f}"
                    )
                else:
                    await update.message.reply_text("❌ Failed to save. Try /add instead")
                return
        except:
            pass
    
    # If not a quick entry, ask Gemini for conversational response
    try:
        prompt = f"""You are Ems AI, a friendly personal finance assistant. The user said: "{text}"

Answer briefly and helpfully about personal finance, budgeting, or expense tracking. Keep response under 150 characters."""
        
        response = model.generate_content(prompt)
        
        await update.message.reply_text(response.text)
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("Sorry, I didn't understand. Use /help to see commands.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel conversation"""
    await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

def main():
    """Start the bot"""
    app = Application.builder().token(TOKEN).build()
    
    # Command handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('list', list_expenses))
    app.add_handler(CommandHandler('summary', summary))
    app.add_handler(CommandHandler('tips', get_tips))
    
    # Add expense conversation
    add_conv = ConversationHandler(
        entry_points=[CommandHandler('add', add_expense_start)],
        states={
            SELECT_CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_category)],
            ENTER_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_amount)],
            ENTER_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_description)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    app.add_handler(add_conv)
    
    # Split bill conversation
    split_conv = ConversationHandler(
        entry_points=[CommandHandler('split', split_bill_start)],
        states={
            SPLIT_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, split_amount)],
            SPLIT_PEOPLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, split_people)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    app.add_handler(split_conv)
    
    # Message handler (for quick entries and chat)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Start bot
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
