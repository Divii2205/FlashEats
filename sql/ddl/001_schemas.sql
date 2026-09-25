-- Warehouse layering. Each schema is a trust boundary:
--   raw     : landed exactly as retrieved, no casting, no cleaning
--   staging : typed, normalised, quarantine siblings for rejected rows
--   marts   : workflow model (facts + dimensions) organised around the business process
--   metrics : published KPI outputs
--   meta    : pipeline's own record of what it did (run log, manifest, validation results)
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS marts;
CREATE SCHEMA IF NOT EXISTS metrics;
CREATE SCHEMA IF NOT EXISTS meta;
