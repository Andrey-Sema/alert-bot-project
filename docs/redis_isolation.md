# Redis 7.2: роли сервисов и переход с общего пароля

Compose требует выделенного Redis приложения, database 0 и файл ACL. Пользователь
`default` отключён. Runtime URL должен содержать имя соответствующей роли;
production entrypoints требуют SERVICE_ROLE и перед началом работы выполняют
`ACL WHOAMI`. Readiness повторяет эту проверку. WHOAMI подтверждает имя, но не
отсутствие дополнительных разрешений: действующие ACL дополнительно проверяет
оператор. Development-профиль предназначен для тестов и локальных утилит.

| Роль | Назначение и ограничения |
| --- | --- |
| alert_scraper | Публикация source stream и маркеры дедупликации; чтение содержимого stream запрещено. |
| alert_worker | Чтение/ACK source stream; доставка, lease, rate limits и trigger reconciliation. Privacy deletion/generation читаются, но их изменение запрещено. |
| alert_bot_ui | Mute/throttle, изменение triggers, privacy fence и очистка очередей; публикация source/delivery stream запрещена. |
| alert_monitor | INFO и безопасные агрегаты latency/slowlog length; нет key access, CONFIG, SLOWLOG GET, SCAN или Lua. |
| alert_health | Только аутентификация, PING и QUIT. |
| alert_operator | Администрирование; пароль не передаётся сервисам или exporter. |

Команды и шаблоны ключей задаёт `core_shared/redis_acl.py` через Redis selectors.
Источник: [официальная документация Redis ACL](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/).
Один selector должен разрешать все ключи конкретной команды: это учтено для
многоключевого DEL при удалении профиля. Lua получает разрешение на вызов, а
выполняемые им команды отдельно ограничены ACL; ошибка после записи не означает
автоматический rollback предыдущих команд скрипта.

## Подготовка оператором

1. В защищённом каталоге `secrets/` подготовить шесть файлов
   `redis_scraper_password`, `redis_worker_password`, `redis_bot_ui_password`,
   `redis_monitor_password`, `redis_health_password`, `redis_operator_password`.
   Каждый содержит независимо сгенерированные 32 случайных байта в виде 64
   lowercase hex символов. Не выводить значения в терминал, не хранить в Git.
   Для генерации подходит `secrets.token_hex(32)`; не повторять примерные значения.
2. Выполнить из корня проекта:

   ```bash
   python -m alert_bot_project.scripts.build_redis_acl \
     --password-dir secrets \
     --acl-output secrets/redis_users.acl \
     --exporter-output secrets/redis_exporter_credentials.json
   ```

   Генератор не требует Telegram/DB env. Он ограничивает чтение обычных файлов,
   отклоняет неполный набор/повторные пароли и пишет новые файлы с mode 0600.
   Существующие файлы не перезаписывает. ACL содержит только SHA-256 password
   hashes; JSON для exporter содержит только пароль monitor с ключом
   `redis://redis:6379`. Не монтировать весь каталог secrets в контейнер.
3. Защитить каталог от других пользователей хоста и предоставить чтение каждому
   файлу только нужному UID контейнера. Проверить UID закреплённого образа и
   фактические права после mount. В локальном Compose file-backed secrets являются
   bind mounts: uid/gid/mode декларации не заменяют host permissions. На Windows
   нужен ACL хоста; POSIX mode 0600 сам по себе его не подтверждает. Не исправлять
   ошибку доступа открытием всего каталога секретов всем пользователям.
4. В `.env.worker`, `.env.bot_ui`, `.env.scraper` указать соответствующие named
   Redis URL с их независимыми паролями; `_FILE` поддерживается. Worker/Bot UI
   не получают scraper/operator/monitor credentials. Мигратор не использует Redis.
   Проверить `docker compose config --format json` через
   `python -m alert_bot_project.scripts.validate_service_environment`, не сохранять
   и не печатать rendered JSON с реальными секретами.
5. Переход требует согласованной остановки runtime, смены ACL/URL и перезапуска;
   старый общий пароль не сохраняется как fallback. Проверить health/readiness,
   source publish, доставку настоящему тестовому получателю и удаление профиля.
   AOF/очереди сохранять. Без этих действий новая конфигурация не запустится.

Exporter использует отдельный password JSON secret и named user. CONFIG-сбор,
client list и извлечение key values выключены. Подтверждение совместимости
закреплённого образа — `test_pinned_exporter_scrapes_without_payload_access`.
Настройки password file описаны [в проекте exporter](https://github.com/oliver006/redis_exporter).

## Проверки и открытые границы

CI поднимает отдельный Redis 7.2 на loopback 6380 с этой ACL и закреплённый
exporter на 9122. Тесты проверяют реальный отказ без AUTH/с неверным паролем,
конкурентную дедупликацию, delivery Lua/lease/rate/transaction, privacy deletion,
trigger reconciliation, чужие ключи и попытку обхода через Lua. Опасные
административные команды проверяются ACL DRYRUN и не исполняются. Временные
пароли CI генерируются заново и не передаются в аргументах команд Docker.

SCAN у scraper/Bot UI необходим для существующей очистки и раскрывает имена
ключей: key patterns не делают его фильтром конфиденциальности. Эти роли
предназначены для одного приложения, не для разделения независимых tenants.
Worker/Bot UI всё ещё имеют широкие полномочия внутри своего сервисного scope.
Redis Cluster/Sentinel и metadata isolation этим пакетом не подтверждены.

Внутренний Redis/exporter остаётся plaintext в закрытой Docker-сети; ACL не
заменяет TLS. PKI, реальная ротация/отзыв, права файлов, провайдер и recovery
остаются GAP/UNTESTED. При ротации отключение user само по себе не отзывает уже
аутентифицированные соединения: оператор должен завершить старые connections
либо согласованно перезапустить сервисы и проверить старые credentials.
Полное соответствие ASVS и оценка 9/10 пока не заявляются.
