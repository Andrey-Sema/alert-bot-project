# Черговий оператор: перевірки та відновлення

## Початкова перевірка

1. `docker compose ps` — перевірити стан Redis, migrator, scraper, worker, bot_ui, Prometheus та Alertmanager.
2. `docker compose logs --tail=100 scraper worker bot_ui alertmanager` — перевірити причину. Не копіювати токени чи сирі повідомлення до публічних задач.
3. `docker compose run --rm --entrypoint=/bin/amtool alertmanager check-config /etc/alertmanager/alertmanager.yml` — перевірити файл, який бачить контейнер. Файли `./secrets/alertmanager_bot_token` та `./secrets/alertmanager_chat_id` мають існувати до запуску Compose; перший містить токен бота, другий — числовий chat ID адміністратора. Доступ лише оператору, не додавати файли в Git.
4. `docker compose exec prometheus promtool check rules /etc/prometheus/alerts.yml` — перевірити правила.

## Контрольний алерт

Після налаштування реальних секретів на робочому стенді надішліть `POST http://127.0.0.1:9093/api/v2/alerts` із JSON-масивом `[{"labels":{"alertname":"OdesaAlertRoutingTest","severity":"warning","instance":"manual-YYYYMMDD"},"annotations":{"summary":"Перевірка маршруту операційних алертів"}}]`. Унікальний `instance` потрібен для нового маршруту, а не повтору вже згрупованого алерту. Перевірте, що Alertmanager показує alert, а адміністратор отримав Telegram-повідомлення протягом `group_wait` плюс мережевий час. Відмітьте час, середовище та факт отримання в приватному журналі чергування. CI перевіряє синтаксис; фактичну доставку без робочих секретів CI не підтверджує.

## Redis недоступний

Перевірити стан Redis і вільне місце для AOF: `docker compose ps redis` та `docker compose logs --tail=100 redis`. Відновити контейнер/мережу без видалення тома `redis_data`. Після відновлення перевірити `scraper_outbox_depth`, `worker_source_stream_depth`, `worker_delivery_stream_depth`, `worker_delayed_queue_depth` та обидва DLQ. Scraper повторно публікує локальний outbox; worker забирає pending stream через XAUTOCLAIM. Порівняти лічильники прийнятих/відправлених повідомлень і провести контрольне тестове джерело.

## Pyrogram втратив авторизацію

Зупинити тільки scraper, зберегти копію файлу сесії з обмеженим доступом, перевірити причину logout у приватних логах. Повторно авторизувати Pyrogram вручну, оновити секрет/том сесії та запустити scraper. Не стирати outbox: до відновлення Redis він зберігає ще не прийняті повідомлення. Після старту перевірити, що `scraper_source_published_total` зростає, а outbox зменшується.

## Telegram 429 або збій доставки

Перевірити `worker_delivery_outcomes_total{outcome="retry"}`, найстаріше завдання та `worker_delivery_permanent_failures_total`. Не збільшувати паралелізм під час 429. Rate limiter виконує паузу за `retry_after`, задачі залишаються pending і повторюються після lease. Для заблокованого бота потрібна повторна реєстрація користувача. Після відновлення перевірити реальні успішні доставки, а не лише спад backlog.

## PostgreSQL недоступний

Перевірити TLS, DNS, ліміт з'єднань та статус Supabase/PostgreSQL. Не запускати ручне `create_all` і не вимикати RLS. Worker не підтверджує вихідне повідомлення, доки не збереже завдання адресатів; після п'яти невдалих спроб джерело потрапляє до `dead_letter_queue`. Після відновлення БД перевірити міграційну версію та повторити обробку тільки перевірених DLQ-елементів.

## DLQ

`dead_letter_queue` містить вихідні події після збоїв БД; `delivery_dead_letter_queue` — невдалі адресні доставки. Перед повтором перевірити причину, актуальність загрози, чи не видалив користувач профіль, та чи не було відбою. Републікація без перевірки може надіслати застарілу або повторну тривогу. Рішення і ID елемента фіксуються в приватному журналі інциденту. Масовий автоматичний replay не дозволений.
