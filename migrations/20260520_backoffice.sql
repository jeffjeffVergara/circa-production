-- Backoffice Circa: auditoría (auth vía env BACKOFFICE_EMAIL/PASSWORD en MVP)

CREATE TABLE IF NOT EXISTS backoffice_audit_log (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id text,
  user_email text,
  action text NOT NULL,
  entity_type text NOT NULL,
  entity_id text,
  comment text,
  before_json jsonb,
  after_json jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_backoffice_audit_created
  ON backoffice_audit_log (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_backoffice_audit_entity
  ON backoffice_audit_log (entity_type, entity_id);

COMMENT ON TABLE backoffice_audit_log IS 'Acciones del backoffice de soporte Circa';
