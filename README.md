# SynthesisFinder — Автоматический банк задач по полному синтезу

**SynthesisFinder** — это автоматизированный пайплайн и статический веб-сайт для поиска новых научных статей по полному синтезу природных соединений (Total Synthesis), извлечения схем реакций с помощью бесплатных AI-моделей, рендеринга 2D-структур через RDKit и публикации интерактивных задач и офлайн-флешкарт на **GitHub Pages**.

## Возможности

- **Автоматический сбор статей**: мониторинг свежих публикаций (ChemASAP / ChemRxiv) и поиск Open-Access PDF (ChemRxiv, Unpaywall, EuropePMC).
- **AI-фильтрация и извлечение схем**: быстрая текстовая фильтрация (Groq / NVIDIA NIM) и мультимодальное извлечение пошаговых схем синтеза из PDF (Google Gemini).
- **Рендеринг молекул (RDKit)**: валидация и канонизация SMILES, генерация SVG-структур для сайта и офлайн-флешкарт в стиле «змейки» (`cbd2`).
- **Интерактивный веб-интерфейс (`site/`)**:
  - Каталог задач с поиском и фильтрацией по сложности, журналу, году, тегам и статусу.
  - Режим решения задач с переключением режимов флешкарт: **Hide Reagents**, **Hide Products**, **Reveal Step by Step**.
  - Сохранение прогресса (**Solved**, **In Progress**, **Bookmarked**) в `localStorage` браузера.
  - Кнопка открытия и скачивания автономной HTML-флешкарты.
- **Полная автоматизация через GitHub Actions**: обновление каталога каждые 12 часов и автоматический деплой на GitHub Pages.

---

## Быстрый старт на GitHub

### 1. Сделайте Fork или загрузите проект в свой репозиторий

1. Нажмите **Fork** в правом верхнем углу репозитория (или создайте новый репозиторий на GitHub и выполните `git push`).
2. Убедитесь, что основная ветка называется `main`.

### 2. Получите бесплатные API-ключи

Для работы пайплайна достаточно бесплатных тарифов:

1. **Google Gemini (`GEMINI_API_KEY`)** — обязателен для мультимодального извлечения схем из PDF:
   - Перейдите в [Google AI Studio](https://aistudio.google.com/apikey) и создайте API-ключ.
2. **Groq (`GROQ_API_KEY`)** — опционально, для быстрой первичной фильтрации:
   - Зарегистрируйтесь в [Groq Console](https://console.groq.com/keys) и создайте API-ключ.
3. **NVIDIA NIM (`NVIDIA_API_KEY`)** — опционально, как резервный провайдер:
   - Получите ключ в [NVIDIA Build](https://build.nvidia.com/).
4. **Unpaywall Email (`UNPAYWALL_EMAIL`)** — ваш email для вежливых запросов к API Unpaywall при поиске Open-Access PDF.

### 3. Добавьте ключи в GitHub Secrets

1. Откройте ваш репозиторий на GitHub → **Settings** → **Secrets and variables** → **Actions**.
2. Нажмите **New repository secret** и добавьте следующие секреты:
   - `GEMINI_API_KEY`
   - `GROQ_API_KEY` *(опционально)*
   - `NVIDIA_API_KEY` *(опционально)*
   - `UNPAYWALL_EMAIL`

### 4. Включите GitHub Pages

1. Перейдите в **Settings** → **Pages**.
2. В разделе **Build and deployment** → **Source** выберите **GitHub Actions**.
3. Перейдите на вкладку **Actions** вашего репозитория, выберите workflow **Update Synthesis Catalog & Deploy Pages** и нажмите **Run workflow** для первого запуска.

Через несколько минут сайт будет доступен по адресу `https://<ваш-логин>.github.io/<имя-репозитория>/`.

---

## Локальный запуск

Для локальной разработки используется менеджер пакетов `uv` и Python 3.11+:

```bash
# Установка зависимостей
uv sync

# Запуск пайплайна (обработка до 5 новых статей)
export GEMINI_API_KEY="ваш_ключ"
export UNPAYWALL_EMAIL="you@example.com"
uv run python -m synthesis_finder.pipeline --max-articles 5 --out-dir site/data

# Локальный просмотр сайта
python -m http.server 8000 --directory site
```

После запуска локального сервера откройте [http://localhost:8000](http://localhost:8000) в браузере.
