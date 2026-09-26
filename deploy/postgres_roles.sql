-- Operator-only, after Alembic upgrade. Run with ON_ERROR_STOP in one transaction.
-- Does not provision passwords or revoke unrelated PUBLIC/schema grants.
BEGIN;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alert_bot_migrator') THEN
    CREATE ROLE alert_bot_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alert_bot_worker') THEN
    CREATE ROLE alert_bot_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'alert_bot_ui') THEN
    CREATE ROLE alert_bot_ui LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ('alert_bot_migrator', 'alert_bot_worker', 'alert_bot_ui')
             AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolinherit OR rolreplication OR rolbypassrls)) THEN
    RAISE EXCEPTION 'Unsafe existing alert-bot role attributes';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.member
             WHERE r.rolname IN ('alert_bot_migrator', 'alert_bot_worker', 'alert_bot_ui')) THEN
    RAISE EXCEPTION 'Alert-bot roles must not have role memberships';
  END IF;
  IF has_schema_privilege('alert_bot_worker', 'public', 'CREATE') OR
     has_schema_privilege('alert_bot_ui', 'public', 'CREATE') OR
     has_database_privilege('alert_bot_worker', current_database(), 'CREATE') OR
     has_database_privilege('alert_bot_ui', current_database(), 'CREATE') THEN
    RAISE EXCEPTION 'Runtime has inherited CREATE rights; isolate database or review PUBLIC grants first';
  END IF;
END $$;

GRANT USAGE, CREATE ON SCHEMA public TO alert_bot_migrator;
GRANT USAGE ON SCHEMA public TO alert_bot_worker, alert_bot_ui;
ALTER TABLE public.user_settings OWNER TO alert_bot_migrator;
ALTER TABLE public.user_triggers OWNER TO alert_bot_migrator;
ALTER TABLE public.user_activity_daily OWNER TO alert_bot_migrator;
ALTER TABLE public.alembic_version OWNER TO alert_bot_migrator;

REVOKE ALL ON public.user_settings, public.user_triggers, public.user_activity_daily, public.alembic_version
  FROM alert_bot_worker, alert_bot_ui;
GRANT SELECT ON public.user_settings, public.user_triggers TO alert_bot_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_activity_daily TO alert_bot_worker;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_settings, public.user_triggers, public.user_activity_daily
  TO alert_bot_ui;

ALTER TABLE public.user_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_triggers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_activity_daily ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS alert_bot_ui_access ON public.user_settings;
CREATE POLICY alert_bot_ui_access ON public.user_settings TO alert_bot_ui USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS alert_bot_ui_access ON public.user_triggers;
CREATE POLICY alert_bot_ui_access ON public.user_triggers TO alert_bot_ui USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS alert_bot_ui_access ON public.user_activity_daily;
CREATE POLICY alert_bot_ui_access ON public.user_activity_daily TO alert_bot_ui USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS alert_bot_worker_read ON public.user_settings;
CREATE POLICY alert_bot_worker_read ON public.user_settings FOR SELECT TO alert_bot_worker USING (true);
DROP POLICY IF EXISTS alert_bot_worker_read ON public.user_triggers;
CREATE POLICY alert_bot_worker_read ON public.user_triggers FOR SELECT TO alert_bot_worker USING (true);
DROP POLICY IF EXISTS alert_bot_worker_activity ON public.user_activity_daily;
CREATE POLICY alert_bot_worker_activity ON public.user_activity_daily TO alert_bot_worker USING (true) WITH CHECK (true);
COMMIT;
