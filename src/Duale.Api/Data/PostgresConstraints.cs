using Microsoft.EntityFrameworkCore.Migrations;
namespace Duale.Api.Data;

// Database-level backstops EF cannot express. Called from the PostgresConstraints migration (see scripts/).
public static class PostgresConstraints
{
    public static void Up(MigrationBuilder m)
    {
        m.Sql("CREATE EXTENSION IF NOT EXISTS btree_gist;");
        m.Sql("""
            ALTER TABLE "Assignments"
              ADD CONSTRAINT "EX_Assignments_NoOverlapAccepted"
              EXCLUDE USING gist ("TechnicianId" WITH =, tstzrange("ScheduledStart", "ScheduledEnd") WITH &&)
              WHERE ("Status" = 'Accepted');
            """);

        // ---- Phase 4/5 backstops: the database refuses what the application should never attempt ----
        m.Sql("""
            ALTER TABLE "LedgerEntries" ADD CONSTRAINT "CK_Ledger_OneSide" CHECK ("Debit" >= 0 AND "Credit" >= 0 AND ("Debit" = 0) <> ("Credit" = 0));
            ALTER TABLE "PaymentRecords" ADD CONSTRAINT "CK_Payments_Positive" CHECK ("Amount" > 0);
            ALTER TABLE "TechnicianPayables" ADD CONSTRAINT "CK_Payables_Positive" CHECK ("Amount" > 0);
            ALTER TABLE "Invoices" ADD CONSTRAINT "CK_Invoices_Positive" CHECK ("Total" > 0);
            ALTER TABLE "Refunds" ADD CONSTRAINT "CK_Refunds_Positive" CHECK ("Amount" > 0);
            ALTER TABLE "JobFinancialTerms" ADD CONSTRAINT "CK_Terms_Amounts" CHECK ("TechnicianCompensation" > 0 AND "CustomerCharge" >= 0 AND "PlatformFee" >= 0);
            ALTER TABLE "PlatformSubscriptions" ADD CONSTRAINT "CK_Subscriptions_Valid" CHECK ("Amount" >= 0 AND "PeriodEnd" >= "PeriodStart");
            ALTER TABLE "PlatformSubscriptions" ADD CONSTRAINT "EX_Subscriptions_NoOverlapActive"
              EXCLUDE USING gist ("CompanyId" WITH =, daterange("PeriodStart", "PeriodEnd", '[]') WITH &&) WHERE ("Status" = 'Active');
            """);
        m.Sql("""
            CREATE OR REPLACE FUNCTION duale_block_mutation() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION '% is append-only', TG_TABLE_NAME; END;
            $$ LANGUAGE plpgsql;
            CREATE TRIGGER "TR_Ledger_AppendOnly" BEFORE UPDATE OR DELETE ON "LedgerEntries" FOR EACH ROW EXECUTE FUNCTION duale_block_mutation();
            CREATE TRIGGER "TR_PaymentEvents_AppendOnly" BEFORE UPDATE OR DELETE ON "PaymentEvents" FOR EACH ROW EXECUTE FUNCTION duale_block_mutation();
            CREATE TRIGGER "TR_Audit_AppendOnly" BEFORE UPDATE OR DELETE ON "AuditEvents" FOR EACH ROW EXECUTE FUNCTION duale_block_mutation();
            """);
        m.Sql("""
            CREATE OR REPLACE FUNCTION duale_check_balance() RETURNS trigger AS $$
            BEGIN
              IF EXISTS (SELECT 1 FROM "LedgerEntries" WHERE "CompanyId" = NEW."CompanyId" AND "TxnKey" = NEW."TxnKey"
                         GROUP BY "Currency" HAVING SUM("Debit") <> SUM("Credit")) THEN
                RAISE EXCEPTION 'Unbalanced ledger posting %', NEW."TxnKey";
              END IF;
              RETURN NULL;
            END; $$ LANGUAGE plpgsql;
            CREATE CONSTRAINT TRIGGER "TR_Ledger_Balanced" AFTER INSERT ON "LedgerEntries" DEFERRABLE INITIALLY DEFERRED
              FOR EACH ROW EXECUTE FUNCTION duale_check_balance();
            """);
    }
    public static void Down(MigrationBuilder m)
    {
        m.Sql("""
            DROP TRIGGER IF EXISTS "TR_Ledger_Balanced" ON "LedgerEntries"; DROP TRIGGER IF EXISTS "TR_Ledger_AppendOnly" ON "LedgerEntries";
            DROP TRIGGER IF EXISTS "TR_PaymentEvents_AppendOnly" ON "PaymentEvents"; DROP TRIGGER IF EXISTS "TR_Audit_AppendOnly" ON "AuditEvents";
            DROP FUNCTION IF EXISTS duale_check_balance(); DROP FUNCTION IF EXISTS duale_block_mutation();
            """);
        m.Sql("""ALTER TABLE "Assignments" DROP CONSTRAINT IF EXISTS "EX_Assignments_NoOverlapAccepted";""");
    }
}
