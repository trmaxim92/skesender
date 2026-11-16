# 4. Развёртывание приложения из GitHub на подготовленный VPS

## 4.1 Цель и исходное состояние

**Цель.** После базового hardening сервера (глава 3) вручную развернуть веб-приложение SkySender (репозиторий GitHub) так, чтобы:

- исходный код доставлялся из системы контроля версий без секретов;
- СУБД и прикладной API не были доступны из Интернета напрямую;
- процесс приложения управлялся systemd и переживал перезагрузку сервера;
- статика и reverse proxy обслуживались nginx на портах, уже разрешённых UFW (80/443).

**Было.** Сервер усилен (пользователь `deploy`, SSH по ключу, UFW, Fail2ban), но прикладное ПО ещё не установлено.

**Сделано.** Выполнен пошаговый ручной деплой: установка рантайма, клонирование репозитория, настройка PostgreSQL, создание `.env` только на сервере, установка зависимостей backend/frontend, unit systemd от имени `deploy`, конфигурация nginx.

**Результат.** Приложение доступно по HTTP(S) через nginx; API слушает `127.0.0.1:8000`; PostgreSQL — локально; секреты не хранятся в git.

**Архитектура после развёртывания**

```text
Браузер → nginx (:80/:443)
              ├─ статика  frontend/dist
              └─ /api, /health → uvicorn 127.0.0.1:8000 → PostgreSQL 127.0.0.1:5432
```

В репозитории для локальной разработки есть `docker-compose.yml` (только Postgres/Redis). На дипломном VPS выбран эквивалентный по изоляции сетевой поверхности вариант **на хосте**: PostgreSQL и API не публикуются наружу (согласовано с политикой UFW из главы 3).

---

## 4.2 Подключение к серверу

**Было.** Администрирование выполняется только под непривилегированным пользователем.

**Сделано.**

1. Вход по SSH-ключу:
   ```bash
   ssh deploy@<IP-адрес-сервера>
   ```
   Команда устанавливает защищённый сеанс. Парольный вход и `root` по SSH отключены ранее.

2. Проверка прав `sudo` (нужны для пакетов, PostgreSQL, systemd, nginx):
   ```bash
   sudo -v
   ```
   Обновляет отметку аутентификации sudo без выполнения команды.

**Результат.** Дальнейшие шаги выполняются от `deploy` с повышением привилегий только там, где это необходимо.

---

## 4.3 Установка пакетов рантайма

**Было.** На сервере после hardening есть базовые утилиты (`git`, `curl`, `ufw`, `fail2ban`), но нет стека приложения.

**Сделано.**

1. Обновление индекса и установка компонентов:
   ```bash
   sudo apt update
   sudo apt install -y nginx postgresql postgresql-contrib \
     python3-venv python3-pip curl ca-certificates gnupg
   ```

   | Пакет | Назначение |
   |---|---|
   | `nginx` | раздача статики SPA и reverse proxy к API |
   | `postgresql`, `postgresql-contrib` | СУБД приложения |
   | `python3-venv`, `python3-pip` | изолированное окружение Python и установка зависимостей |
   | `curl`, `ca-certificates`, `gnupg` | проверки health, TLS-корни, подпись репозиториев Node |

2. Установка Node.js 22 (нужен для сборки frontend):
   ```bash
   curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
   sudo apt install -y nodejs
   node -v
   npm -v
   ```
   Скрипт NodeSource добавляет APT-репозиторий; `nodejs` включает `npm`. Версии выводятся для фиксации в отчёте.

3. Включение служб:
   ```bash
   sudo systemctl enable --now postgresql
   sudo systemctl enable --now nginx
   ```
   `enable` — автозапуск после перезагрузки; `--now` — немедленный старт.

**Результат.** На сервере доступны компоненты, достаточные для сборки и запуска приложения.

---

## 4.4 Клонирование репозитория из GitHub

**Было.** Код приложения отсутствует на сервере.

**Сделано.**

1. Каталог установки с правами пользователя `deploy`:
   ```bash
   sudo mkdir -p /opt/order-elite
   sudo chown deploy:deploy /opt/order-elite
   ```
   Приложение размещается в `/opt` (общепринятое место для стороннего ПО). Владелец `deploy` позволяет собирать зависимости и писать данные без работы процесса от `root`.

2. Клонирование с GitHub (shallow clone — только актуальная история):
   ```bash
   git clone --depth 1 https://github.com/trmaxim92/skesender.git /opt/order-elite
   cd /opt/order-elite
   git rev-parse --short HEAD
   ```
   `--depth 1` уменьшает объём передачи. Хеш коммита фиксируется для воспроизводимости.

3. Требование ИБ — секреты не в репозитории:
   ```bash
   test ! -f /opt/order-elite/backend/.env && echo "OK: .env отсутствует в клоне"
   ```
   Файл окружения создаётся только на сервере (см. п. 4.6).

**Результат.** Исходный код получен из GitHub; каталог принадлежит `deploy`.

---

## 4.5 Настройка PostgreSQL

**Было.** СУБД установлена, но роль и база приложения не созданы.

**Сделано.**

1. Генерация пароля роли (не сохранять в git):
   ```bash
   DB_PASS=$(openssl rand -hex 16)
   echo "$DB_PASS" | sudo tee /home/deploy/order-elite-db-pass.txt >/dev/null
   sudo chmod 600 /home/deploy/order-elite-db-pass.txt
   sudo chown deploy:deploy /home/deploy/order-elite-db-pass.txt
   ```
   Пароль хранится локально с правами только для владельца.

2. Создание роли и базы:
   ```bash
   sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
   DO \$\$
   BEGIN
     IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'orderelite') THEN
       CREATE ROLE orderelite LOGIN PASSWORD '${DB_PASS}';
     ELSE
       ALTER ROLE orderelite WITH PASSWORD '${DB_PASS}';
     END IF;
   END
   \$\$;
   SELECT 'CREATE DATABASE orderelite OWNER orderelite'
   WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'orderelite')\gexec
   GRANT ALL PRIVILEGES ON DATABASE orderelite TO orderelite;
   \c orderelite
   GRANT ALL ON SCHEMA public TO orderelite;
   SQL
   ```
   Роль `orderelite` получает отдельную БД; пароль подставляется из переменной `DB_PASS` текущей сессии.

3. Сетевая изоляция: по умолчанию PostgreSQL слушает localhost. Порт `5432` **не** открывается в UFW — с Интернета СУБД недоступна.

**Результат.** База готова к подключению приложения по `127.0.0.1:5432`.

---

## 4.6 Секреты приложения (файл `.env`)

**Было.** В клоне есть только шаблон `backend/.env.example`.

**Сделано.**

1. Генерация ключа подписи JWT/секретов приложения:
   ```bash
   SECRET=$(openssl rand -hex 32)
   ```

2. Создание файла окружения (пример; пароли заменить на сгенерированные):
   ```bash
   cd /opt/order-elite/backend
   cat > .env <<EOF
   APP_NAME=SkySender
   DEBUG=false
   SECRET_KEY=${SECRET}
   DATABASE_URL=postgresql+asyncpg://orderelite:${DB_PASS}@127.0.0.1:5432/orderelite
   ACCESS_TOKEN_EXPIRE_MINUTES=1440
   CORS_ORIGINS=http://<IP-адрес-сервера>,http://127.0.0.1
   SEED_ADMIN_EMAIL=admin@order-elite.local
   SEED_ADMIN_PASSWORD=<сильный_уникальный_пароль>
   SEED_ADMIN_NAME=Admin
   SEED_MAX_BOT_TOKEN=
   MAX_API_BASE=https://platform-api2.max.ru
   MAX_API_VERIFY_SSL=true
   MAX_PERSONAL_DATA_DIR=./data/max_personal
   TELEGRAM_API_ID=
   TELEGRAM_API_HASH=
   TELEGRAM_USER_DATA_DIR=./data/telegram_user
   TELEGRAM_PROXY=
   EOF
   chmod 600 .env
   ```

   | Параметр | Назначение |
   |---|---|
   | `DEBUG=false` | запрет небезопасного режима на проде |
   | `SECRET_KEY` | криптографический секрет приложения / JWT |
   | `DATABASE_URL` | строка подключения к PostgreSQL (только localhost) |
   | `CORS_ORIGINS` | разрешённые источники браузера |
   | `SEED_ADMIN_*` | первичная учётная запись администратора при первом старте |
   | `MAX_API_VERIFY_SSL=true` | проверка TLS при обращении к API MAX (нужен CA Минцифры, см. ниже) |

   Установка корневых сертификатов Минцифры (обязательно для `platform-api2.max.ru`):
   ```bash
   sudo bash /opt/order-elite/scripts/install-russian-ca.sh
   ```
   Приложение также подмешивает `backend/certs/russian_trusted_ca_bundle.pem` в CA-бандл httpx автоматически.

3. Каталоги данных (вложения, сессии интеграций):
   ```bash
   mkdir -p data/attachments data/max_personal data/telegram_user
   ```

**Результат.** Секреты существуют только на сервере с правами `600`; схема БД будет создана приложением при старте (`create_all` / seed).

---

## 4.7 Backend: виртуальное окружение и зависимости

**Было.** Исходники Python есть, зависимости не установлены.

**Сделано.**

```bash
cd /opt/order-elite/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
deactivate
```

- `python3 -m venv` создаёт изолированное окружение (системный Python не засоряется).
- `pip install -r requirements.txt` ставит FastAPI, SQLAlchemy, драйвер PostgreSQL и прочие зависимости из манифеста репозитория.

Проверка импорта (опционально):
```bash
cd /opt/order-elite/backend
.venv/bin/python -c "from app.main import app; print('backend_ok')"
```

**Результат.** Backend готов к запуску через uvicorn из `.venv`.

---

## 4.8 Frontend: установка и production-сборка

**Было.** Исходники Vue есть; production-бандл отсутствует.

**Сделано.**

```bash
cd /opt/order-elite/frontend
npm install
npm run build
ls -la dist | head
```

- `npm install` — зависимости Node по `package-lock.json`.
- `npm run build` — typecheck и сборка Vite в каталог `frontend/dist`, который раздаёт nginx.

**Результат.** Статические файлы UI готовы к публикации.

---

## 4.9 Unit systemd (процесс API от пользователя `deploy`)

**Было.** API не зарегистрирован как системная служба.

**Сделано.**

1. Файл unit:
   ```bash
   sudo tee /etc/systemd/system/order-elite.service >/dev/null <<'UNIT'
   [Unit]
   Description=SkySender API
   After=network.target postgresql.service
   Requires=postgresql.service

   [Service]
   Type=simple
   User=deploy
   Group=deploy
   WorkingDirectory=/opt/order-elite/backend
   Environment=PATH=/opt/order-elite/backend/.venv/bin:/usr/bin
   ExecStart=/opt/order-elite/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
   Restart=always
   RestartSec=3

   [Install]
   WantedBy=multi-user.target
   UNIT
   ```

   | Параметр | Назначение |
   |---|---|
   | `User=deploy` / `Group=deploy` | процесс не работает от `root` |
   | `--host 127.0.0.1` | API доступен только локально (через nginx) |
   | `--port 8000` | внутренний порт; в UFW не открывается |
   | `Restart=always` | автовосстановление после сбоя |
   | `Requires=postgresql.service` | старт после СУБД |

2. Применение:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now order-elite
   sudo systemctl status order-elite --no-pager
   ```

3. Журнал при ошибках:
   ```bash
   sudo journalctl -u order-elite -n 50 --no-pager
   ```

**Результат.** API запущен от `deploy`, слушает только loopback, переживает перезагрузку сервера.

---

## 4.10 Конфигурация nginx (статика + reverse proxy)

**Было.** nginx установлен, сайт приложения не настроен.

**Сделано.**

1. Конфигурация виртуального хоста (базовый HTTP для дипломного стенда):
   ```bash
   sudo tee /etc/nginx/sites-available/order-elite >/dev/null <<'NGINX'
   server {
       listen 80 default_server;
       listen [::]:80 default_server;
       server_name _;

       root /opt/order-elite/frontend/dist;
       index index.html;
       client_max_body_size 50m;

       location /api/ {
           proxy_pass http://127.0.0.1:8000;
           proxy_http_version 1.1;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
           proxy_set_header X-Forwarded-Proto $scheme;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_read_timeout 3600s;
           proxy_send_timeout 3600s;
       }

       location /health {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
       }

       location / {
           try_files $uri $uri/ /index.html;
       }
   }
   NGINX
   ```

   - `/` — SPA (`try_files` отдаёт `index.html` для client-side routing);
   - `/api/` и `/health` — прокси на uvicorn;
   - `client_max_body_size 50m` — загрузка вложений.

2. Активация сайта:
   ```bash
   sudo rm -f /etc/nginx/sites-enabled/default
   sudo ln -sfn /etc/nginx/sites-available/order-elite /etc/nginx/sites-enabled/order-elite
   sudo nginx -t
   sudo systemctl reload nginx
   ```
   `nginx -t` проверяет синтаксис до применения — снижает риск потери HTTP-доступа.

**Результат.** Снаружи доступны только порты UFW (80/443); прикладной порт 8000 скрыт за reverse proxy.

---

## 4.11 Проверка работоспособности (чеклист)

| № | Проверка | Команда / действие | Ожидание |
|---|---|---|---|
| 1 | Служба API | `systemctl is-active order-elite` | `active` |
| 2 | Health напрямую | `curl -sf http://127.0.0.1:8000/health` | JSON со `"status":"ok"` |
| 3 | Health через nginx | `curl -sf http://127.0.0.1/health` | тот же ответ |
| 4 | UI | `curl -sf -o /dev/null -w "%{http_code}\n" http://127.0.0.1/` | `200` |
| 5 | Снаружи | браузер: `http://<IP-адрес-сервера>/` | страница входа кабинета |
| 6 | Файрвол | `sudo ufw status` | разрешены OpenSSH, 80/tcp, 443/tcp |
| 7 | Коммит | `cd /opt/order-elite && git rev-parse --short HEAD` | зафиксировать в отчёте |

Дополнительно:
```bash
ss -lntp | grep -E ':8000|:5432' || true
```
Порты должны слушаться на `127.0.0.1` (или unix-socket у PostgreSQL), а не на `0.0.0.0` для публичного доступа.

**Результат.** Подтверждена работоспособность стека и соответствие сетевой модели главы 3.

---

## 4.12 Повторный деплой (обновление из `main`)

При появлении новых коммитов в GitHub:

```bash
cd /opt/order-elite
git fetch --depth 1 origin main
git reset --hard origin/main
echo "COMMIT=$(git rev-parse --short HEAD)"

cd /opt/order-elite/backend
source .venv/bin/activate
pip install -r requirements.txt
deactivate

cd /opt/order-elite/frontend
npm install
npm run build

sudo systemctl restart order-elite
curl -sf http://127.0.0.1/health
```

- `git reset --hard origin/main` приводит дерево к состоянию удалённой ветки (локальные правки на сервере не сохраняются — конфигурация живёт в `.env` и unit-файлах вне git).
- Переустановка зависимостей нужна при изменении `requirements.txt` / `package-lock.json`; при косметических правках UI достаточно `npm run build` и перезапуска API при изменениях backend.

Файл `.env` **не** перезаписывать из репозитория.

---

## 4.13 Опционально: HTTPS (Let's Encrypt)

Если назначен домен, указывающий на VPS:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d <домен>
```

Certbot изменит конфиг nginx (слушатели 443, редирект с 80). Порт 443 уже разрешён в UFW (глава 3).

---

## 4.14 Итоговые требования после развёртывания

1. Код получен из GitHub; секреты только в `backend/.env` с `chmod 600`.
2. PostgreSQL и uvicorn слушают localhost; снаружи — nginx на 80/443.
3. Процесс API запускается от `User=deploy`, автозапуск через systemd.
4. UFW по-прежнему ограничивает вход до SSH/HTTP/HTTPS.
5. Зафиксированы коммит развёртывания и успешный ответ `/health`.

---

## 4.15 Краткая формулировка для выводов главы

На подготовленном VPS вручную развёрнуто веб-приложение из репозитория GitHub: установлены рантайм-зависимости, создана изолированная СУБД на localhost, секреты вынесены в защищённый `.env`, backend запущен через systemd от непривилегированного пользователя `deploy` на loopback-интерфейсе, frontend собран в статику и опубликован через nginx. Сетевая модель согласована с hardening: порты СУБД и API не экспонируются в Интернет, что снижает поверхность атаки на этапе эксплуатации.
