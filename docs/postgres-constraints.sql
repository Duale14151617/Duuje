-- Add to the first migration with migrationBuilder.Sql(...). PostgreSQL only.
-- Guarantees a technician can never hold two overlapping *confirmed* assignments, even under concurrent requests.
-- (The application also checks inside a serializable transaction; this is the database-level backstop.)
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE "Assignments"
  ADD CONSTRAINT "EX_Assignments_NoOverlapAccepted"
  EXCLUDE USING gist ("TechnicianId" WITH =, tstzrange("ScheduledStart", "ScheduledEnd") WITH &&)
  WHERE ("Status" = 'Accepted');

-- Phase 4/5 backstops: see src/Duale.Api/Data/PostgresConstraints.cs (applied by the PostgresConstraints migration).
-- Positive-amount CHECKs, one-sided ledger lines, append-only triggers on LedgerEntries/PaymentEvents/AuditEvents,
-- and a deferred constraint trigger that rejects any ledger posting whose debits and credits differ per currency.
