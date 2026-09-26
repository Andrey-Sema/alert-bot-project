# PostgreSQL: сервисные роли и включение

Пакет отделяет schema owner от runtime: `alert_bot_migrator`, `alert_bot_worker`, `alert_bot_ui`. Роли LOGIN, NOINHERIT, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS, без memberships. Пароли не создаются в коде: новые роли не могут войти до назначения отдельного секрета оператором. PostgreSQL NOINHERIT само по себе не запрещает SET ROLE, поэтому дополнительно запрещены memberships и проверены реальные отказы ([PostgreSQL 16](https://www.postgresql.org/docs/16/role-membership.html)).

| Сервис | Таблицы и операции |
|---|---|
| worker | SELECT user_settings/user_triggers; SELECT/INSERT/UPDATE/DELETE user_activity_daily для записи доставки и retention |
| bot_ui | SELECT/INSERT/UPDATE/DELETE user_settings/user_triggers/user_activity_daily; privacy delete с FK cascade |
| migrator | owner трёх таблиц и alembic_version; CREATE в public для Alembic |
| scraper | PostgreSQL URL отсутствует; PostgreSQL role не нужна |

Runtime не получает TRUNCATE, REFERENCES, TRIGGER, grant option, schema/database CREATE или доступ к alembic_version. Будущие таблицы не получают wildcard/default runtime grants. Существующие grants других таблиц/схем, функции SECURITY DEFINER, storage/provider permissions и LOGIN/password lifecycle требуют отдельного аудита. Контракт запуска проверяет только перечисленные четыре таблицы и роли; это не полный аудит аккаунта PostgreSQL.

## Порядок включения

1. Остановить Python-сервисы и сохранить проверенный backup. На первом включении выполнить Alembic доверенным оператором с отдельным `MIGRATION_DATABASE_URL`/`MIGRATION_DATABASE_URL_FILE`; fallback на `DATABASE_URL` удалён. Для существующей БД предварительно изучить текущих владельцев и политики. Не применять операторский SQL автоматически к общей Supabase БД.
2. Выполнить `psql ... -v ON_ERROR_STOP=1 -f deploy/postgres_roles.sql` доверенным администратором. Скрипт одной транзакцией создаёт/проверяет роли, передаёт владение ровно четырьмя таблицами и задаёт точные grants/RLS policies. Существующие небезопасные attributes/memberships или наследуемый CREATE приводят к отказу, а не глобальному REVOKE. Скрипт не отзывает PUBLIC/schema grants других приложений: администратор должен выбрать отдельную БД либо отдельно исправить конфликт. Неизвестные существующие RLS policies не удаляются автоматически.
3. Через защищённый канал управления БД назначить отдельные пароли ролям, ограничить подключения БД/сетью. Не помещать пароль в shell history, исходники или чат. Сохранить owner/migrator secret отдельно от runtime и использовать TLS с проверкой сертификата. Pooler/custom role login нужно проверить на конкретном провайдере: проверяются и current_user, и session_user.
4. Скопировать только соответствующий `deploy/{service}.env.example` в `.env.{service}` и заполнить значения. Compose больше не передаёт общую `.env` приложениям; root `.env` служит только интерполяции инфраструктуры. Для secret files требуется отдельный read-only mount через операторский Compose override. Нельзя копировать весь root `.env` в runtime-файлы. SERVICE_ROLE задан Compose и не зависит от содержимого env-файла.
5. Запустить migrator с его отдельным URL, затем worker/bot_ui/scraper. Для scraper отсутствуют BOT_TOKEN и DATABASE_URL; worker/UI не получают API_HASH/Pyrogram session. Runtime отвергает migration secret, включая `_FILE`, ещё до чтения файла. Проверить readiness, первое уведомление, изменение/удаление профиля и отсутствие secret leakage. Для ручного запуска модулей SERVICE_ROLE также обязателен.

Проверка фактических runtime-полномочий выполняется до polling/consuming и в readiness: повышенные attributes, login/role mismatch, memberships, DDL, владение таблицей, отсутствие RLS, лишние/недостающие table grants, grant options и лишние column grants приводят к отказу. Два SQL запроса заменяют десятки отдельных сетевых проверок. Доступные сервисные RLS policies разрешают сервису свою работу со всеми профилями; это **не** per-user RLS. Проверка владельца пользователя в Bot UI остаётся задачей серверных handlers. Мигратор как owner может обходить RLS и намеренно не доступен runtime.

Локально проверяется временный PostgreSQL 18 на loopback; CI использует отдельную disposable БД PostgreSQL 16. Тест покрывает авторизованный CRUD, denied writes/DDL/SET ROLE, недоступную будущую таблицу, ownership, profile mismatch, column grant, role membership, отключение RLS и privacy FK cascade. Пароли тестов генерируются заново и существуют только в тестовом кластере. Это не подтверждает доступы или восстановление production.

Следующие открытые пункты: отдельные Redis ACL/monitoring credentials, TLS внутреннего Redis/monitoring, vault/rotation, запуск на провайдере, backup restore и нагрузочная приёмка. Изменение grants после старта будет замечено readiness, но автоматическое прекращение всех текущих задач по такому событию отдельно не реализовано; неподходящая роль не может выполнить запрещённый SQL благодаря самой БД.
