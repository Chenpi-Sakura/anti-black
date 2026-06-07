-- Phase 3.2 retrain delta trigger.
-- Adds last_retrain_silver_total to antiblack.auto_evolution so
-- check_and_trigger can compute delta from last successful retrain
-- instead of firing only when absolute total exceeds threshold.
ALTER TABLE antiblack.auto_evolution
    ADD COLUMN IF NOT EXISTS last_retrain_silver_total INTEGER;
