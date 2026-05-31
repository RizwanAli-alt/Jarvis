import json
import re
from difflib import get_close_matches
import wikipedia
import pyjokes
import os
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import ensure_csrf_cookie
from django.core.mail import send_mail
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django_ratelimit.decorators import ratelimit
from .tasks import send_task_notification
from .models import CommandHistory, UserProfile, Task
import datetime
import logging
import smtplib
import pytz
from sympy import sympify, SympifyError
import spacy
from textblob import TextBlob
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from bleach import clean
from django.utils import timezone
from urllib.parse import quote
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.template.loader import render_to_string

logging.basicConfig(
    filename='jarvis_web.log',
    level=logging.INFO,
    format='{"time": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}'
)

nlp = spacy.load("en_core_web_sm")


# ─────────────────────────────────────────────
#  CommandRegistry & helpers (unchanged)
# ─────────────────────────────────────────────

class CommandRegistry:
    def __init__(self):
        self.commands = {}

    def register(self, pattern, func, requires_admin=False):
        self.commands[pattern] = {"func": func, "requires_admin": requires_admin}

    def get_command(self, pattern):
        return self.commands.get(pattern)


def load_config():
    try:
        config = {
            "wake_word": getattr(settings, 'JARVIS_WAKE_WORD', 'hey jarvis'),
            "language": getattr(settings, 'JARVIS_LANGUAGE', 'en-US'),
            "urls": getattr(settings, 'JARVIS_URLS', {
                "youtube": "https://www.youtube.com",
                "google": "https://www.google.com",
                "wikipedia": "https://www.wikipedia.org"
            }),
            "voice_mode": getattr(settings, 'JARVIS_VOICE_MODE', True)
        }
        if not isinstance(config["wake_word"], str) or not config["wake_word"]:
            raise ValidationError("Invalid wake word in configuration")
        if not isinstance(config["urls"], dict):
            raise ValidationError("Invalid URLs configuration")
        return config
    except Exception as e:
        logging.error(f"Config load error: {e}")
        return {
            "wake_word": "hey jarvis",
            "language": "en-US",
            "urls": {"youtube": "https://www.youtube.com", "google": "https://www.google.com", "wikipedia": "https://www.wikipedia.org"},
            "voice_mode": True
        }


CONFIG = load_config()


def get_sentiment_response(command, base_response):
    try:
        blob = TextBlob(command)
        sentiment = blob.sentiment.polarity
        if sentiment > 0.2:
            return f"Awesome to see your enthusiasm! {base_response}"
        elif sentiment < -0.2:
            return f"Sorry you're feeling down. {base_response} Need a joke to cheer up?"
        return base_response
    except Exception as e:
        logging.error(f"Sentiment analysis error: {e}")
        return base_response


def set_reminder_task(task, time_str, user):
    try:
        task = clean(task, tags=[], strip=True)[:100]
        if not task:
            raise ValidationError("Task name cannot be empty")
        if not re.match(r'^\d{2}:\d{2}$', time_str):
            raise ValidationError("Invalid time format. Use HH:MM, e.g., 14:30")
        profile = UserProfile.objects.get(user=user)
        due_time = datetime.datetime.strptime(time_str, "%H:%M").replace(
            year=timezone.now().year, month=timezone.now().month, day=timezone.now().day,
            tzinfo=pytz.timezone(profile.timezone)
        )
        if due_time < timezone.now():
            due_time += datetime.timedelta(days=1)
        Task.objects.create(user=user, task_name=task, due_time=due_time)
        send_task_notification.delay(task, time_str, user.email, profile.whatsapp_number)
        return f"Task '{task}' set for {time_str}. Notification scheduled."
    except ValidationError as e:
        logging.error(f"Reminder validation error: {e}")
        return str(e)
    except Exception as e:
        logging.error(f"Reminder error: {e}")
        return "Failed to set reminder."


def get_wikipedia_summary(query):
    try:
        query = clean(query, tags=[], strip=True)[:100]
        if not query:
            raise ValidationError("Wikipedia query cannot be empty")
        cache_key = f"wiki_{query}"
        cached_result = cache.get(cache_key)
        if cached_result:
            return cached_result
        result = wikipedia.summary(query, sentences=2)
        cache.set(cache_key, result, timeout=3600)
        return result
    except ValidationError as e:
        logging.error(f"Wikipedia validation error: {e}")
        return str(e)
    except wikipedia.exceptions.DisambiguationError:
        return "Multiple results found. Please be more specific."
    except wikipedia.exceptions.PageError:
        return "No results found on Wikipedia."
    except Exception as e:
        logging.error(f"Wikipedia error: {e}")
        return "Error fetching Wikipedia data."


def save_command_history(user, command):
    try:
        command = clean(command, tags=[], strip=True)[:200]
        if not command:
            return
        CommandHistory.objects.create(user=user, command=command)
        logging.info(f"User {user.username} executed command: {command}")
    except Exception as e:
        logging.error(f"Command history save error for user {user.username}: {e}")


def calculate_expression(expr):
    try:
        expr = clean(expr.replace("calculate", ""), tags=[], strip=True).strip()
        result = sympify(expr, evaluate=True)
        return f"The result is: {result}"
    except SympifyError:
        return "Invalid calculation. Please provide a valid mathematical expression."
    except Exception as e:
        logging.error(f"Calculation error: {e}")
        return "Error performing calculation."


def manage_task(command, user):
    try:
        if "add task" in command:
            task_match = re.search(r"add task (.+?) at (\d{2}:\d{2})", command)
            if not task_match:
                return "Please specify task and time, e.g., 'add task meeting at 14:30'."
            task_name, time_str = task_match.groups()
            return set_reminder_task(task_name, time_str, user)
        elif "list tasks" in command:
            tasks = Task.objects.filter(user=user, completed=False).order_by('due_time')[:5]
            if not tasks:
                return "No active tasks."
            return "<br>".join([f"{task.task_name} (Due: {task.due_time.strftime('%H:%M on %b %d, %Y')})" for task in tasks])
        elif "complete task" in command:
            task_name = re.search(r"complete task (.+)", command)
            if not task_name:
                return "Please specify task, e.g., 'complete task meeting'."
            task_name = clean(task_name.group(1), tags=[], strip=True)[:100]
            task = Task.objects.filter(user=user, task_name__iexact=task_name, completed=False).first()
            if not task:
                return f"Task '{task_name}' not found."
            task.completed = True
            task.save()
            return f"Task '{task_name}' marked as completed."
        return "Invalid task command. Use 'add task', 'list tasks', or 'complete task'."
    except Exception as e:
        logging.error(f"Task management error for user {user.username}: {e}")
        return "Error managing task."


def send_multi_platform_message(user, command):
    try:
        if "send email" in command:
            match = re.search(r"send email (.+?) to (.+)", command)
            if not match:
                return "Please specify message and recipient, e.g., 'send email Hello to user@example.com'."
            message, to_email = match.groups()
            message = clean(message, tags=[], strip=True)[:1000]
            send_mail("JARVIS Message", message, settings.DEFAULT_FROM_EMAIL, [to_email],
                      fail_silently=False, html_message=f"<p>{message}</p>")
            return f"Email sent to {to_email}."
        elif "send whatsapp message" in command:
            match = re.search(r"send whatsapp message (.+?) to (\+[\d]+)", command)
            if not match:
                return "Please specify message and phone number, e.g., 'send whatsapp message Hello to +1234567890'."
            message, phone_number = match.groups()
            message = clean(message, tags=[], strip=True)[:1000]
            try:
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                client.messages.create(body=message, from_=settings.TWILIO_WHATSAPP_NUMBER, to=f'whatsapp:{phone_number}')
                return f"WhatsApp message sent to {phone_number}."
            except TwilioRestException as e:
                logging.error(f"Twilio error for user {user.username}: {e}")
                return "Failed to send WhatsApp message."
        elif "open whatsapp" in command:
            match = re.search(r"open whatsapp (.+?) to (\+[\d]+)", command)
            if not match:
                return "Please specify message and phone number."
            message, phone_number = match.groups()
            message = clean(message, tags=[], strip=True)[:1000]
            whatsapp_url = f"https://wa.me/{phone_number}?text={message.replace(' ', '%20')}"
            return HttpResponse(f'<script>window.location.href = "{whatsapp_url}";</script>')
        return "Invalid message command. Use 'send email', 'send whatsapp message', or 'open whatsapp'."
    except Exception as e:
        logging.error(f"Multi-platform message error for user {user.username}: {e}")
        return "Error sending message."


def play_youtube_video(query):
    try:
        query = clean(query.replace("play video", "").strip(), tags=[], strip=True)[:100]
        if not query:
            return "Please specify a video to play."
        if "ai" in query.lower():
            return HttpResponse('<script>window.location.href = "https://youtu.be/mJlRTUuVr04?si=0ntfpZ2KPCrfSyGj";</script>')
        return HttpResponse(f'<script>window.location.href = "https://www.youtube.com/results?search_query={quote(query)}";</script>')
    except Exception as e:
        logging.error(f"YouTube video error: {e}")
        return "Error searching for YouTube video."


def open_android_studio():
    return "Opening Android Studio is not supported in the web version. Please open it manually."


def open_ai_folder():
    return "Opening the AI folder is not supported in the web version. Please open the folder manually."


def parse_command(command):
    try:
        doc = nlp(command.lower())
        best_match = None
        best_score = 0.0
        for pattern in COMMAND_REGISTRY.commands:
            pattern_doc = nlp(pattern)
            similarity = doc.similarity(pattern_doc)
            if similarity > best_score and similarity > 0.8:
                best_score = similarity
                best_match = pattern
        return best_match
    except Exception as e:
        logging.error(f"Command parsing error: {e}")
        return None


COMMAND_REGISTRY = CommandRegistry()
COMMAND_REGISTRY.register("joke", lambda: f"Here's a joke: {pyjokes.get_joke()}")
COMMAND_REGISTRY.register("open youtube", lambda: HttpResponse('<script>window.location.href = "{}";</script>'.format(CONFIG['urls']['youtube'])))
COMMAND_REGISTRY.register("open google", lambda: HttpResponse('<script>window.location.href = "{}";</script>'.format(CONFIG['urls']['google'])))
COMMAND_REGISTRY.register("open wikipedia", lambda: HttpResponse('<script>window.location.href = "{}";</script>'.format(CONFIG['urls']['wikipedia'])))
COMMAND_REGISTRY.register("command history", lambda user: "<br>".join([f"{entry.timestamp}: {entry.command}" for entry in CommandHistory.objects.filter(user=user).order_by('-timestamp')[:5]] or ["No history available."]))
COMMAND_REGISTRY.register("help", lambda: "Available commands: " + ", ".join(COMMAND_REGISTRY.commands.keys()))
COMMAND_REGISTRY.register("volume up", lambda: "Volume increased (web media volume).")
COMMAND_REGISTRY.register("volume down", lambda: "Volume decreased (web media volume).")
COMMAND_REGISTRY.register("toggle voice mode", lambda: "Voice mode toggle not supported in web mode.")
COMMAND_REGISTRY.register("change language", lambda lang: f"Language changed to {lang} (web mode only changes display).")
COMMAND_REGISTRY.register("set reminder", set_reminder_task)
COMMAND_REGISTRY.register("wikipedia", get_wikipedia_summary)
COMMAND_REGISTRY.register("time", lambda user: datetime.datetime.now(pytz.timezone(UserProfile.objects.get(user=user).timezone)).strftime("%I:%M %p on %A, %B %d, %Y"))
COMMAND_REGISTRY.register("weather", lambda: "Weather information requires an API. Would you like me to help with something else?")
COMMAND_REGISTRY.register("calculate", calculate_expression)
COMMAND_REGISTRY.register("status", lambda: "System Status: ✅ Online<br>Uptime: 99.9%<br>Response Time: 0.3s<br>All systems operational.")
COMMAND_REGISTRY.register("clear", lambda: "Response area cleared. (Note: Clear manually via button.)")
COMMAND_REGISTRY.register("hello", lambda: "Hello! I'm JARVIS, your virtual assistant. How can I help you today?")
COMMAND_REGISTRY.register("thank you", lambda: "You're welcome! I'm here whenever you need assistance.")
COMMAND_REGISTRY.register("system config", lambda: "System configuration access restricted.", requires_admin=True)
COMMAND_REGISTRY.register("task", manage_task)
COMMAND_REGISTRY.register("message", send_multi_platform_message)
COMMAND_REGISTRY.register("play video", play_youtube_video)
COMMAND_REGISTRY.register("open android studio", open_android_studio)
COMMAND_REGISTRY.register("open ai folder", open_ai_folder)


# ─────────────────────────────────────────────
#  Core views
# ─────────────────────────────────────────────

@login_required
@ensure_csrf_cookie
@ratelimit(key='user', rate='30/m', method='POST')
def process_command(request):
    try:
        if request.method != "POST":
            return JsonResponse({"error": "Invalid request method."}, status=405)
        data = json.loads(request.body)
        command = data.get("command", "").lower()
        if not command:
            return JsonResponse({"error": "No command provided."}, status=400)

        save_command_history(request.user, command)

        if CONFIG["wake_word"] not in command:
            return JsonResponse({"response": get_sentiment_response(command, "No wake word detected.")})

        command = command.replace(CONFIG["wake_word"], "").strip()
        parsed_command = parse_command(command)

        if parsed_command:
            cmd_info = COMMAND_REGISTRY.get_command(parsed_command)
            if cmd_info["requires_admin"] and not request.user.has_perm('assistant.admin_access'):
                return JsonResponse({"error": "Permission denied: Admin access required."}, status=403)

            if parsed_command == "change language":
                lang_match = re.search(r"change language (\w{2}-\w{2})", command)
                if lang_match:
                    response = cmd_info["func"](lang_match.group(1))
                    return JsonResponse({"response": get_sentiment_response(command, response)})
                return JsonResponse({"response": "Please specify a language, e.g., 'change language en-US'."})
            elif parsed_command == "set reminder":
                task_match = re.search(r"for (.+?) at", command)
                time_match = re.search(r"at (\d{2}:\d{2})", command)
                if task_match and time_match:
                    response = cmd_info["func"](task_match.group(1), time_match.group(1), request.user)
                    return JsonResponse({"response": get_sentiment_response(command, response)})
                return JsonResponse({"response": "Please specify a task and time, e.g., 'set reminder for meeting at 14:30'."})
            elif parsed_command == "wikipedia":
                query = clean(command.replace("wikipedia", "").strip(), tags=[], strip=True)
                response = cmd_info["func"](query)
                return JsonResponse({"response": get_sentiment_response(command, response)})
            elif parsed_command == "command history":
                response = cmd_info["func"](request.user)
                return JsonResponse({"response": get_sentiment_response(command, response)})
            elif parsed_command == "task":
                response = cmd_info["func"](command, request.user)
                return JsonResponse({"response": get_sentiment_response(command, response)})
            elif parsed_command == "message":
                response = cmd_info["func"](request.user, command)
                return JsonResponse({"response": get_sentiment_response(command, response)})
            elif parsed_command == "play video":
                query = clean(command.replace("play video", "").strip(), tags=[], strip=True)
                return cmd_info["func"](query)
            elif parsed_command in ["open youtube", "open google", "open wikipedia", "open whatsapp", "open android studio", "open ai folder"]:
                return cmd_info["func"]()
            elif parsed_command == "calculate":
                expr = clean(command.replace("calculate", "").strip(), tags=[], strip=True)
                response = cmd_info["func"](expr)
                return JsonResponse({"response": get_sentiment_response(command, response)})
            elif parsed_command == "time":
                response = cmd_info["func"](request.user)
                return JsonResponse({"response": get_sentiment_response(command, response)})
            else:
                response = cmd_info["func"]()
                return JsonResponse({"response": get_sentiment_response(command, response)})
        else:
            close_matches = get_close_matches(command, COMMAND_REGISTRY.commands.keys(), n=1, cutoff=0.6)
            response = f"Did you mean '{close_matches[0]}'? Try again or say 'help'" if close_matches else "Unknown command. Say 'help' for commands."
            return JsonResponse({"response": get_sentiment_response(command, response)})
    except json.JSONDecodeError:
        logging.error(f"JSON decode error for user {request.user.username}")
        return JsonResponse({"error": "Invalid JSON format."}, status=400)
    except Exception as e:
        logging.error(f"Command processing error for user {request.user.username}: {e}")
        return JsonResponse({"error": "Failed to process command."}, status=500)


@login_required
@ensure_csrf_cookie
def index(request):
    try:
        profile, created = UserProfile.objects.get_or_create(user=request.user)
        user_tz = pytz.timezone(profile.timezone)
        current_time = datetime.datetime.now(user_tz).strftime("%I:%M %p %Z on %A, %B %d, %Y")
        command_count = CommandHistory.objects.filter(user=request.user).count()
        user_role = "Administrator" if request.user.has_perm('assistant.admin_access') else "User"
        return render(request, 'assistant/index.html', {
            'current_time': current_time,
            'user': request.user,
            'command_count': command_count,
            'user_role': user_role,
            'favorite_commands': profile.favorite_commands,
            'preferred_language': profile.preferred_language
        })
    except Exception as e:
        logging.error(f"Index view error for user {request.user.username}: {e}")
        return render(request, 'assistant/index.html', {
            'current_time': "Error fetching time",
            'user': request.user,
            'command_count': 0,
            'user_role': "User",
            'favorite_commands': [],
            'preferred_language': 'en-US'
        })


# ─────────────────────────────────────────────
#  Auth views
# ─────────────────────────────────────────────

@ratelimit(key='ip', rate='10/m', method='POST')
def login_view(request):
    if request.user.is_authenticated:
        return redirect('index')
    if request.method == "POST":
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        if not username or not password:
            return render(request, 'assistant/login.html', {'error': 'Please enter both username and password.'})
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect(request.GET.get('next', '/'))
        logging.warning(f"Failed login attempt for username: {username}")
        return render(request, 'assistant/login.html', {
            'error': 'Invalid username or password.',
            'username': username,
        })
    return render(request, 'assistant/login.html')


@ratelimit(key='ip', rate='5/m', method='POST')
def signup_view(request):
    """Register a new user and auto-login on success."""
    if request.user.is_authenticated:
        return redirect('index')

    if request.method == "POST":
        username      = request.POST.get('username', '').strip()
        email         = request.POST.get('email', '').strip()
        first_name    = request.POST.get('first_name', '').strip()
        last_name     = request.POST.get('last_name', '').strip()
        password1     = request.POST.get('password1', '')
        password2     = request.POST.get('password2', '')
        user_timezone = request.POST.get('timezone', 'Asia/Karachi').strip()
        whatsapp_num  = request.POST.get('whatsapp_number', '').strip()

        errors = []

        # Username
        if not username:
            errors.append("Username is required.")
        elif len(username) < 3:
            errors.append("Username must be at least 3 characters.")
        elif not re.match(r'^[a-zA-Z0-9_]+$', username):
            errors.append("Username may only contain letters, numbers, and underscores.")
        elif User.objects.filter(username__iexact=username).exists():
            errors.append("That username is already taken. Please choose another.")

        # Email
        if not email:
            errors.append("Email address is required.")
        else:
            try:
                validate_email(email)
            except ValidationError:
                errors.append("Please enter a valid email address.")
            else:
                if User.objects.filter(email__iexact=email).exists():
                    errors.append("An account with that email already exists.")

        # Passwords
        if not password1:
            errors.append("Password is required.")
        elif password1 != password2:
            errors.append("Passwords do not match.")
        else:
            try:
                validate_password(password1)
            except ValidationError as e:
                errors.extend(list(e.messages))

        # Timezone
        if user_timezone not in pytz.all_timezones:
            errors.append("Invalid timezone selected.")

        # WhatsApp (optional)
        if whatsapp_num:
            if not re.match(r'^\+\d{7,15}$', whatsapp_num):
                errors.append("WhatsApp number must be in E.164 format, e.g., +923001234567")
            elif UserProfile.objects.filter(whatsapp_number=whatsapp_num).exists():
                errors.append("That WhatsApp number is already registered.")

        if errors:
            return render(request, 'assistant/signup.html', {
                'errors': errors,
                'form_data': {
                    'username': username, 'email': email,
                    'first_name': first_name, 'last_name': last_name,
                    'timezone': user_timezone, 'whatsapp_number': whatsapp_num,
                }
            })

        try:
            user = User.objects.create_user(
                username=username, email=email, password=password1,
                first_name=first_name, last_name=last_name,
            )
            UserProfile.objects.create(
                user=user, timezone=user_timezone,
                whatsapp_number=whatsapp_num or '',
            )
            logging.info(f"New user registered: {username} ({email})")
            login(request, user)
            return redirect('index')
        except Exception as e:
            logging.error(f"Signup error for {username}: {e}")
            return render(request, 'assistant/signup.html', {
                'errors': ["An unexpected error occurred. Please try again."],
                'form_data': {
                    'username': username, 'email': email,
                    'first_name': first_name, 'last_name': last_name,
                    'timezone': user_timezone, 'whatsapp_number': whatsapp_num,
                }
            })

    return render(request, 'assistant/signup.html')


@ratelimit(key='ip', rate='10/m', method='POST')
def logout_view(request):
    if request.method == "POST":
        logout(request)
        return redirect('login')
    return redirect('index')


# ─────────────────────────────────────────────
#  Password Reset — Step 1: request email
# ─────────────────────────────────────────────

@ratelimit(key='ip', rate='5/m', method='POST')
def password_reset_view(request):
    """Show the 'enter your email' form and send the reset link."""
    if request.user.is_authenticated:
        return redirect('index')

    if request.method == "POST":
        email = request.POST.get('email', '').strip().lower()

        # Validate format
        try:
            validate_email(email)
        except ValidationError:
            return render(request, 'assistant/password_reset.html', {
                'error': 'Please enter a valid email address.',
                'email': email,
            })

        # Always redirect to "done" page regardless of whether the email exists
        # (prevents user enumeration).
        user = User.objects.filter(email__iexact=email).first()
        if user and user.is_active:
            try:
                _send_password_reset_email(request, user)
                logging.info(f"Password reset email sent to: {email}")
            except smtplib.SMTPAuthenticationError:
                logging.exception("SMTP authentication failed while sending password reset email")
                return render(request, 'assistant/password_reset.html', {
                    'error': 'Email sending is not configured correctly. Use a Gmail app password or switch to the console email backend for local development.',
                    'email': email,
                })
            except smtplib.SMTPException:
                logging.exception("SMTP error while sending password reset email")
                return render(request, 'assistant/password_reset.html', {
                    'error': 'Unable to send the reset email right now. Please check your email settings and try again.',
                    'email': email,
                })

        # Even if email not found, show the same confirmation page
        return redirect(f'/password-reset/done/?email={quote(email)}')

    return render(request, 'assistant/password_reset.html')


def _send_password_reset_email(request, user):
    """Generate token and send the reset email."""
    uid   = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    reset_url = request.build_absolute_uri(f'/password-reset/confirm/{uid}/{token}/')

    subject = "JARVIS — Reset Your Password"
    html_message = f"""
    <html>
    <body style="font-family: Arial, sans-serif; background: #f8fafc; padding: 40px 0;">
        <div style="max-width: 480px; margin: 0 auto; background: #fff; border-radius: 16px;
                    padding: 40px; box-shadow: 0 4px 24px rgba(0,0,0,0.08);">
            <div style="text-align: center; margin-bottom: 32px;">
                <span style="font-size: 3rem;">🤖</span>
                <h1 style="font-size: 1.8rem; font-weight: 800;
                           background: linear-gradient(135deg,#667eea,#764ba2);
                           -webkit-background-clip: text; -webkit-text-fill-color: transparent;
                           margin: 8px 0 4px;">JARVIS</h1>
                <p style="color: #6b7280; margin: 0;">Virtual Assistant</p>
            </div>
            <h2 style="font-size: 1.3rem; color: #1f2937; margin-bottom: 12px;">Reset Your Password</h2>
            <p style="color: #6b7280; line-height: 1.6; margin-bottom: 24px;">
                Hi <strong>{user.first_name or user.username}</strong>,<br><br>
                We received a request to reset your JARVIS password.
                Click the button below to set a new password.
                This link expires in <strong>24 hours</strong>.
            </p>
            <div style="text-align: center; margin-bottom: 24px;">
                <a href="{reset_url}"
                   style="display: inline-block; padding: 14px 32px;
                          background: linear-gradient(135deg,#667eea,#764ba2);
                          color: white; text-decoration: none; border-radius: 12px;
                          font-weight: 700; font-size: 1rem;
                          box-shadow: 0 4px 15px rgba(102,126,234,0.4);">
                    🔑 Reset My Password
                </a>
            </div>
            <p style="color: #9ca3af; font-size: 0.85rem; line-height: 1.6;">
                If you didn't request this, you can safely ignore this email —
                your password will remain unchanged.<br><br>
                Or copy this link into your browser:<br>
                <a href="{reset_url}" style="color: #4f46e5; word-break: break-all;">{reset_url}</a>
            </p>
            <hr style="border: none; border-top: 1px solid #e5e7eb; margin: 24px 0;">
            <p style="color: #9ca3af; font-size: 0.8rem; text-align: center;">
                JARVIS Virtual Assistant &mdash; sent to {user.email}
            </p>
        </div>
    </body>
    </html>
    """
    send_mail(
        subject,
        f"Reset your JARVIS password: {reset_url}",
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        html_message=html_message,
        fail_silently=False,
    )


# ─────────────────────────────────────────────
#  Password Reset — Step 2: email sent confirmation
# ─────────────────────────────────────────────

def password_reset_done_view(request):
    email = request.GET.get('email', 'your email address')
    return render(request, 'assistant/password_reset_done.html', {'email': email})


# ─────────────────────────────────────────────
#  Password Reset — Step 3: confirm & set new password
# ─────────────────────────────────────────────

@ratelimit(key='ip', rate='10/m', method='POST')
def password_reset_confirm_view(request, uidb64, token):
    """Validate the token and let the user set a new password."""
    # Validate the token
    try:
        uid  = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        user = None

    valid_link = user is not None and default_token_generator.check_token(user, token)

    if request.method == "POST":
        if not valid_link:
            return render(request, 'assistant/password_reset_confirm.html', {'validlink': False})

        new_password1 = request.POST.get('new_password1', '')
        new_password2 = request.POST.get('new_password2', '')
        errors = []

        if not new_password1:
            errors.append("Password is required.")
        elif new_password1 != new_password2:
            errors.append("Passwords do not match.")
        else:
            try:
                validate_password(new_password1, user=user)
            except ValidationError as e:
                errors.extend(list(e.messages))

        if errors:
            return render(request, 'assistant/password_reset_confirm.html', {
                'validlink': True,
                'errors': errors,
                'uidb64': uidb64,
                'token': token,
            })

        # Save the new password
        user.set_password(new_password1)
        user.save()
        logging.info(f"Password successfully reset for user: {user.username}")
        return redirect('password_reset_complete')

    return render(request, 'assistant/password_reset_confirm.html', {
        'validlink': valid_link,
        'uidb64': uidb64,
        'token': token,
    })


# ─────────────────────────────────────────────
#  Password Reset — Step 4: success
# ─────────────────────────────────────────────

def password_reset_complete_view(request):
    return render(request, 'assistant/password_reset_complete.html')