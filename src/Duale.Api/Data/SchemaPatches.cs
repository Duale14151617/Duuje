using Microsoft.EntityFrameworkCore;
namespace Duale.Api.Data;

// Idempotent schema changes applied at startup on PostgreSQL, right after the EF migrations. They let a database that already
// ran the old "Initial" migration pick up newer tables and columns WITHOUT generating a new migration (useful when you can only
// work from GitHub on a phone). Every statement is safe to run again, and on a brand-new database they do nothing because the
// migrations already created everything. Add a statement here for each later model change until real migrations are committed.
public static class SchemaPatches
{
    static readonly string[] Statements =
    [
        // Email / phone verification
        "ALTER TABLE \"Users\" ADD COLUMN IF NOT EXISTS \"EmailVerifiedAt\" timestamp with time zone NULL",
        "ALTER TABLE \"Technicians\" ADD COLUMN IF NOT EXISTS \"PhoneVerifiedAt\" timestamp with time zone NULL",
        """
        CREATE TABLE IF NOT EXISTS "VerificationCodes" (
            "Id" uuid NOT NULL PRIMARY KEY,
            "UserId" uuid NOT NULL REFERENCES "Users" ("Id"),
            "Channel" character varying(10) NOT NULL,
            "Target" character varying(254) NOT NULL,
            "CodeHash" character varying(64) NOT NULL,
            "Attempts" integer NOT NULL,
            "ExpiresAt" timestamp with time zone NOT NULL,
            "UsedAt" timestamp with time zone NULL,
            "CreatedAt" timestamp with time zone NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS \"IX_VerificationCodes_UserId_Channel\" ON \"VerificationCodes\" (\"UserId\", \"Channel\")",

        // Technician ratings
        """
        CREATE TABLE IF NOT EXISTS "JobRatings" (
            "Id" uuid NOT NULL PRIMARY KEY,
            "JobId" uuid NOT NULL REFERENCES "Jobs" ("Id"),
            "CompanyId" uuid NOT NULL REFERENCES "Companies" ("Id"),
            "TechnicianId" uuid NOT NULL REFERENCES "Technicians" ("Id"),
            "Stars" integer NOT NULL,
            "Comment" character varying(1000) NULL,
            "RatedBy" uuid NOT NULL,
            "CreatedAt" timestamp with time zone NOT NULL
        )
        """,
        "CREATE UNIQUE INDEX IF NOT EXISTS \"IX_JobRatings_JobId\" ON \"JobRatings\" (\"JobId\")",
        "CREATE INDEX IF NOT EXISTS \"IX_JobRatings_TechnicianId\" ON \"JobRatings\" (\"TechnicianId\")",
    ];

    public static async Task ApplyAsync(AppDbContext db, CancellationToken ct = default)
    {
        foreach (var sql in Statements) await db.Database.ExecuteSqlRawAsync(sql, ct);
    }
}
