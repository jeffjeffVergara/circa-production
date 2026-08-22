-- Express Onboarding: fases de sesión + prospecto (si faltaba)
ALTER TYPE sesion_fase ADD VALUE IF NOT EXISTS 'express_cold';
ALTER TYPE sesion_fase ADD VALUE IF NOT EXISTS 'express_welcome';
ALTER TYPE sesion_fase ADD VALUE IF NOT EXISTS 'express_foto';
ALTER TYPE sesion_fase ADD VALUE IF NOT EXISTS 'express_linea';
ALTER TYPE sesion_fase ADD VALUE IF NOT EXISTS 'express_tyc';
ALTER TYPE sesion_fase ADD VALUE IF NOT EXISTS 'prospecto';
