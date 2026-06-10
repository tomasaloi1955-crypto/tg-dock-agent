# 🤖 TG Doc Agent

Бесплатный ИИ-агент в Telegram, который генерирует документы по текстовому запросу: **PDF, DOCX, XLSX, CSV, TXT, PPTX**. Работает 24/7 на бесплатном хостинге, ИИ — бесплатный Google Gemini.

## Как это работает

1. Пишешь боту: «чек-лист запуска ТГ-канала в PDF» или «презентация про нейросети»
2. Бот сам распознаёт формат и через Gemini генерит содержимое
3. Получаешь готовый файл прямо в чат

Можно прислать боту свой **файл-образец** (.txt, .docx, .pdf, .md, .csv) — он запомнит структуру и стиль и будет генерить документы по нему. Команды: `/template` — посмотреть образец, `/clear` — удалить.

## Деплой за 10 минут (всё бесплатно)

### Шаг 1. Создай бота в Telegram
1. Открой [@BotFather](https://t.me/BotFather) → `/newbot`
2. Придумай имя и username
3. Сохрани **токен** (вида `123456:ABC-DEF...`)

### Шаг 2. Получи бесплатный ключ Gemini
1. Зайди на [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. «Create API key» — карта не нужна
3. Лимиты бесплатного tier: ~15 запросов/мин, 1500/день — для личного бота более чем достаточно

### Шаг 3. Залей код на GitHub
```bash
git init
git add .
git commit -m "TG Doc Agent"
git remote add origin https://github.com/ТВОЙ_ЛОГИН/tg-doc-agent.git
git push -u origin main
```

### Шаг 4. Деплой на Render
1. Зарегистрируйся на [render.com](https://render.com) (через GitHub)
2. **New → Web Service** → выбери репозиторий
3. Настройки:
   - Runtime: **Python 3**
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `python bot.py`
   - Plan: **Free**
4. В **Environment Variables** добавь:
   - `BOT_TOKEN` — токен от BotFather
   - `GEMINI_API_KEY` — ключ Gemini
   - `WEBHOOK_URL` — URL твоего сервиса, например `https://tg-doc-agent.onrender.com` (его видно после создания сервиса; добавь переменную и нажми redeploy)

### Шаг 5. Чтобы не засыпал (опционально, но рекомендую)
Render free засыпает через 15 минут простоя. Webhook будит его при сообщении (задержка ~30-50 сек после сна), но можно держать бодрым постоянно:
1. Зайди на [cron-job.org](https://cron-job.org) (бесплатно)
2. Создай задание: пинговать `https://ТВОЙ-СЕРВИС.onrender.com` каждые 10 минут

⚠️ Render free даёт 750 часов/месяц — это ровно один сервис 24/7.

## Локальный запуск (для теста)
```bash
pip install -r requirements.txt
export BOT_TOKEN="..."
export GEMINI_API_KEY="..."
python bot.py   # без WEBHOOK_URL запустится в polling-режиме
```

## Структура проекта
```
bot.py            — весь код бота
requirements.txt  — зависимости
render.yaml       — конфиг Render (опционально)
fonts/            — шрифты DejaVu для кириллицы в PDF
templates.json    — образцы юзеров (создаётся автоматически)
```

## Известные ограничения
- На Render free диск **эфемерный**: после redeploy образцы юзеров (`templates.json`) сбрасываются. Для постоянного хранения можно прикрутить бесплатную БД (например, Supabase) — но для старта JSON хватает.
- Gemini free tier: 1500 запросов/день. При превышении бот ответит ошибкой до следующих суток.
