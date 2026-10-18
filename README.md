<div align="center">

# Kwork Analytics

**Неофициальный дашборд расширенной аналитики для фриланс-биржи Kwork**

[![React](https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![Vite](https://img.shields.io/badge/Vite-646CFF?style=for-the-badge&logo=vite&logoColor=white)](https://vite.dev/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-D71F00?style=for-the-badge&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://www.docker.com/)
[![Nginx](https://img.shields.io/badge/Nginx-009639?style=for-the-badge&logo=nginx&logoColor=white)](https://nginx.org/)

[Открыть приложение](http://195.133.49.165:8080/) · [Сообщить об ошибке](https://github.com/dog-bobik/Kwork-Analytics/issues/new) · [Предложить улучшение](https://github.com/dog-bobik/Kwork-Analytics/issues/new)

</div>

---

## ✨ Возможности

- аналитика откликов, кворков и работ из портфолио;
- отслеживание прироста просмотров кворков и портфолио;
- просмотр своего и публичных профилей внутри приложения;
- автоматическое фоновое обновление данных каждые 15 минут;
- хранение исторических снимков аналитики в PostgreSQL;
- адаптивный интерфейс с фильтрами, карточками и подробным просмотром;
- серверная авторизация с шифрованием Kwork API-токена.

> [!IMPORTANT]
> Проект не является официальным продуктом Kwork и не связан с администрацией биржи.

## 🧰 Технологии

| Часть проекта | Стек |
| --- | --- |
| Интерфейс | React, TypeScript, Vite, Recharts, Lucide |
| Backend | Python, FastAPI, SQLAlchemy, aiohttp |
| База данных | PostgreSQL, asyncpg |
| Инфраструктура | Docker Compose, Nginx |

## 🌐 Онлайн версия

Стабильная версия доступна по адресу:

<div align="center">

### [🚀 Открыть Kwork Analytics](http://195.133.49.165:8080/)

**http://195.133.49.165:8080/**

</div>

## 🚀 Локальный запуск

### Требования

- Docker;
- Docker Compose;
- Make — необязательно, команды можно запускать напрямую через Docker Compose.

Запустите весь проект:

```bash
make up
```

После сборки будут доступны:

| Сервис | Адрес |
| --- | --- |
| Frontend | [http://127.0.0.1:8080](http://127.0.0.1:8080) |
| Backend API | [http://127.0.0.1:8081](http://127.0.0.1:8081) |

Отдельный запуск frontend или backend:

```bash
make up frontend
make up backend
```

При первом входе приложение запросит данные аккаунта Kwork. Пароль используется только для авторизации и не сохраняется. Полученный API-токен шифруется перед записью в PostgreSQL.

## 📊 Как собирается статистика

Backend самостоятельно обновляет подключённые аккаунты каждые 15 минут, даже если браузер закрыт. Интерфейс получает данные из PostgreSQL, а при устаревшем кэше сервер автоматически запускает фоновую синхронизацию.

Показатель **«Сегодня»** у кворка — это разница между текущим числом просмотров и первым снимком после полуночи в часовом поясе `Asia/Yekaterinburg`.

PostgreSQL хранит:

- пользователей и серверные сессии;
- актуальный кэш данных;
- исторические снимки аналитики;
- историю запусков синхронизации.

## 🐳 Развёртывание

Перед первым публичным запуском создайте локальный файл окружения:

```bash
cp .env.example .env
```

Замените `APP_SECRET` в `.env` на длинное случайное значение. После появления пользователей этот ключ нельзя менять: им зашифрованы сохранённые Kwork-токены. Сам файл `.env` исключён из Git.

Обновление сервера:

```bash
git pull --ff-only origin main
docker compose up --build -d
```

> [!CAUTION]
> Не используйте `docker compose down -v`: параметр `-v` удаляет PostgreSQL volume вместе с накопленной статистикой.

## 🤝 Участие в разработке

### 🐛 Ошибки и предложения

Если вы нашли ошибку или хотите предложить новую возможность, создайте [новый issue](https://github.com/dog-bobik/Kwork-Analytics/issues/new). Постарайтесь описать ожидаемое поведение, фактический результат и шаги для воспроизведения.

### 🔀 Pull Requests

Хотите помочь развитию проекта — создайте [Pull Request](https://github.com/dog-bobik/Kwork-Analytics/pulls). Перед отправкой убедитесь, что frontend собирается, а backend-тесты проходят успешно.

## 📝 Лицензия

Проект распространяется по лицензии MIT. Подробности доступны в файле [LICENSE](https://github.com/dog-bobik/Kwork-Analytics/blob/main/LICENSE).

---

<div align="center">

Сделано для более удобной и наглядной работы со статистикой Kwork.

</div>
