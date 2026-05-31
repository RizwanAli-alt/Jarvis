# JARVIS

An advanced multifunctional web-based virtual assistant inspired by J.A.R.V.I.S. from Iron Man. Built with Django, Celery, Twilio, and a blend of AI and automation libraries. JARVIS provides conversational command and control, task management, reminders, Wikipedia queries, sentiment analysis, and multi-platform messaging—including email and WhatsApp.

---

## Table of Contents
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture-overview)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Usage](#usage)
- [Task Notifications](#task-notifications)
- [Contribution](#contribution)
- [License](#license)

---

## Features

- **Conversational AI Assistant**: Command-based interaction using a web interface, with natural language processing via spaCy.
- **Task Management**: Add, list, and complete daily tasks, set reminders, and receive notifications.
- **Reminders & Notifications**: Get notifications via email and WhatsApp for scheduled tasks.
- **Knowledge Retrieval**: Fetch summaries from Wikipedia.
- **Sentiment Analysis**: Understands user sentiment using TextBlob for a more engaging response.
- **Multi-Platform Messaging**: Send messages via email or WhatsApp directly from chat.
- **Command History**: Maintains recent executed commands per user.
- **Joke Generator**: Lighten the mood with random jokes using pyjokes.
- **Custom Wake Word** and **Language Preferences**
- **Secure User Profiles**: Per-user timezone, language, and preferences.
- **Rate Limiting & Admin Controls**
- **Extensible Command Registry**: Easily add custom commands and actions.

---

## Tech Stack

- **Backend:** Python, Django, Celery
- **Frontend:** HTML, JavaScript, CSS (integrated into Django templates)
- **Task Queues/Notifications:** Celery, Redis, Twilio (for WhatsApp)
- **Database:** SQLite (default, configurable via Django)
- **AI Libraries:** spaCy, TextBlob, pyjokes, wikipedia

---

## Architecture Overview

- `JarvisWebsite/`: Django project root (settings, URLs, ASGI/WSGI config)
- `assistant/`: Django app with all assistant logic (views, models, tasks, static files, templates).
  - `views.py`: Main conversational logic, command parsing, business logic handlers
  - `tasks.py`: Celery background tasks (e.g., reminder notifications)
  - `models.py`: User profiles, tasks, and command history
  - `static/` and `templates/`: UI and assets
- `command_history.json` / `jarvis_config.json`: Persistent configuration/history support
- **Celery Worker & Broker:** Uses Redis for async task scheduling/notifications
- **Twilio integration:** For WhatsApp messaging

---

## Getting Started

### Prerequisites

- Python 3.8+
- Redis (for Celery task queue)
- (optional) Twilio account for WhatsApp messaging and credentials
- Git

### Installation

```bash
git clone https://github.com/RizwanAli-alt/Jarvis.git
cd Jarvis
python -m venv venv
source venv/bin/activate    # or .\venv\Scripts\activate on Windows

pip install -r requirements.txt
```

### Environment Configuration

Create a `.env` file in the project root and configure the following (see `JarvisWebsite/settings.py`):

```env
DJANGO_SECRET_KEY=your-secret-key
DEBUG=True
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=youremail@example.com
EMAIL_HOST_PASSWORD=your-email-password
DEFAULT_FROM_EMAIL=youremail@example.com

# Celery/Redis
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# Twilio settings (for WhatsApp support)
TWILIO_ACCOUNT_SID=your-twilio-account-sid
TWILIO_AUTH_TOKEN=your-twilio-auth-token
TWILIO_WHATSAPP_NUMBER=whatsapp:+1234567890

# API Keys
YOUTUBE_API_KEY=your-youtube-api-key
```

---

## Usage

### Run Migrations

```bash
python manage.py migrate
```

### Start Django Server

```bash
python manage.py runserver
```

### Start Celery Worker (in a new terminal)

```bash
celery -A JarvisWebsite worker -l info
```

---

## Features & Example Commands

Interact with JARVIS through the web UI (login required):

- **General:**  
  - `hey jarvis help` — List available commands  
  - `hey jarvis joke` — Get a random joke  
  - `hey jarvis open youtube` — Open YouTube  
  - `hey jarvis play video [query]` — Play or search for YouTube videos  
  - `hey jarvis wikipedia [topic]` — Get a Wikipedia summary

- **Task Management:**  
  - `hey jarvis add task meeting at 14:30` — Add new task  
  - `hey jarvis list tasks` — List tasks  
  - `hey jarvis complete task meeting` — Complete a task  

- **Reminders:**  
  - `hey jarvis set reminder for math class at 16:00` — Set a reminder (get notified by email/WhatsApp)

- **Multi-Platform Messaging:**  
  - `hey jarvis send email Hello to someone@example.com`  
  - `hey jarvis send whatsapp message Hello to +1234567890`  

---

## Task Notifications

Reminders use Celery for background scheduling and Twilio for WhatsApp. Email reminders are sent via your configured SMTP provider.

---

## Contribution

1. Fork the repo and clone your fork
2. Create a new branch (`git checkout -b feature/your-feature`)
3. Commit your changes
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

### Code Style

Follow Django and PEP8 standards. Describe your feature/bugfix thoroughly in the PR.

---

## License

_(No explicit license detected — please add a LICENSE file to clarify usage rights.)_

---

## Credits

- Inspired by intelligent assistants like JARVIS from Iron Man
- Built with Django, Celery, Twilio, spaCy, TextBlob, pyjokes, wikipedia, and more

---

## Contact

For support and feature requests, open an issue or contact the repository owner.
