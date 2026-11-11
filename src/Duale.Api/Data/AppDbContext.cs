using Duale.Api.Domain;
using Microsoft.EntityFrameworkCore;
namespace Duale.Api.Data;

public class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options)
{
    public DbSet<User> Users => Set<User>();
    public DbSet<Company> Companies => Set<Company>();
    public DbSet<Role> Roles => Set<Role>();
    public DbSet<Permission> Permissions => Set<Permission>();
    public DbSet<RolePermission> RolePermissions => Set<RolePermission>();
    public DbSet<CompanyMembership> Memberships => Set<CompanyMembership>();
    public DbSet<MembershipRole> MembershipRoles => Set<MembershipRole>();
    public DbSet<PlatformRoleAssignment> PlatformRoleAssignments => Set<PlatformRoleAssignment>();
    public DbSet<Trade> Trades => Set<Trade>();
    public DbSet<Skill> Skills => Set<Skill>();
    public DbSet<Technician> Technicians => Set<Technician>();
    public DbSet<TechnicianSkill> TechnicianSkills => Set<TechnicianSkill>();
    public DbSet<AuditEvent> AuditEvents => Set<AuditEvent>();
    public DbSet<TechnicianCompanyRelationship> Relationships => Set<TechnicianCompanyRelationship>();
    public DbSet<TechnicianAvailability> Availability => Set<TechnicianAvailability>();
    public DbSet<Customer> Customers => Set<Customer>();
    public DbSet<ServiceLocation> Locations => Set<ServiceLocation>();
    public DbSet<Job> Jobs => Set<Job>();
    public DbSet<JobRequiredSkill> JobRequiredSkills => Set<JobRequiredSkill>();
    public DbSet<JobAssignment> Assignments => Set<JobAssignment>();
    public DbSet<JobStatusHistory> JobStatusHistory => Set<JobStatusHistory>();
    public DbSet<Notification> Notifications => Set<Notification>();
    public DbSet<Branch> Branches => Set<Branch>();
    public DbSet<BranchMembership> BranchMemberships => Set<BranchMembership>();
    public DbSet<ServiceArea> ServiceAreas => Set<ServiceArea>();
    public DbSet<TechnicianServiceArea> TechnicianServiceAreas => Set<TechnicianServiceArea>();
    public DbSet<TechnicianDocument> TechnicianDocuments => Set<TechnicianDocument>();
    public DbSet<MfaRecoveryCode> MfaRecoveryCodes => Set<MfaRecoveryCode>();
    public DbSet<PasswordResetToken> PasswordResetTokens => Set<PasswordResetToken>();
    public DbSet<JobEvidence> JobEvidence => Set<JobEvidence>();
    public DbSet<JobWorkReport> JobWorkReports => Set<JobWorkReport>();
    public DbSet<JobScopeChange> JobScopeChanges => Set<JobScopeChange>();
    public DbSet<JobReview> JobReviews => Set<JobReview>();
    public DbSet<JobComplaint> JobComplaints => Set<JobComplaint>();
    public DbSet<JobRelationship> JobRelationships => Set<JobRelationship>();
    public DbSet<IdempotencyRecord> IdempotencyRecords => Set<IdempotencyRecord>();
    public DbSet<JobFinancialTerms> FinancialTerms => Set<JobFinancialTerms>();
    public DbSet<Invoice> Invoices => Set<Invoice>();
    public DbSet<InvoiceLine> InvoiceLines => Set<InvoiceLine>();
    public DbSet<TechnicianPayable> Payables => Set<TechnicianPayable>();
    public DbSet<PaymentRecord> Payments => Set<PaymentRecord>();
    public DbSet<PaymentEvent> PaymentEvents => Set<PaymentEvent>();
    public DbSet<Refund> Refunds => Set<Refund>();
    public DbSet<LedgerEntry> Ledger => Set<LedgerEntry>();
    public DbSet<PlatformFeeRecord> PlatformFees => Set<PlatformFeeRecord>();
    public DbSet<Dispute> Disputes => Set<Dispute>();
    public DbSet<NotificationPreference> NotificationPreferences => Set<NotificationPreference>();
    public DbSet<NotificationDelivery> Deliveries => Set<NotificationDelivery>();
    public DbSet<OutboxEvent> OutboxEvents => Set<OutboxEvent>();
    public DbSet<PlatformSubscription> Subscriptions => Set<PlatformSubscription>();
    public DbSet<IntegrationAccount> IntegrationAccounts => Set<IntegrationAccount>();
    public DbSet<JobRating> JobRatings => Set<JobRating>();
    public DbSet<VerificationCode> VerificationCodes => Set<VerificationCode>();

    protected override void ConfigureConventions(ModelConfigurationBuilder c)
    {
        c.Properties<AccountStatus>().HaveConversion<string>().HaveMaxLength(20);
        c.Properties<VerificationStatus>().HaveConversion<string>().HaveMaxLength(20);
        c.Properties<MembershipStatus>().HaveConversion<string>().HaveMaxLength(20);
        c.Properties<RelationshipType>().HaveConversion<string>().HaveMaxLength(20);
        c.Properties<RelationshipStatus>().HaveConversion<string>().HaveMaxLength(20);
        c.Properties<JobStatus>().HaveConversion<string>().HaveMaxLength(30);
        c.Properties<JobPriority>().HaveConversion<string>().HaveMaxLength(20);
        c.Properties<AssignmentStatus>().HaveConversion<string>().HaveMaxLength(20);
        c.Properties<ReviewStatus>().HaveConversion<string>().HaveMaxLength(20);
    }

    protected override void OnModelCreating(ModelBuilder b)
    {
        b.Entity<User>(e => { e.HasIndex(x => x.Email).IsUnique(); e.Property(x => x.Email).HasMaxLength(254); e.Property(x => x.DisplayName).HasMaxLength(120); e.Property(x => x.MfaSecretEnc).HasMaxLength(400); });
        b.Entity<Company>(e => { e.Property(x => x.DisplayName).HasMaxLength(160); e.Property(x => x.BusinessCategory).HasMaxLength(100); e.HasIndex(x => x.Verification); });

        b.Entity<Role>().HasKey(x => x.Code);
        b.Entity<Permission>().HasKey(x => x.Code);
        b.Entity<RolePermission>(e =>
        {
            e.HasKey(x => new { x.RoleCode, x.PermissionCode });
            e.HasOne<Role>().WithMany().HasForeignKey(x => x.RoleCode);
            e.HasOne<Permission>().WithMany().HasForeignKey(x => x.PermissionCode);
        });
        b.Entity<CompanyMembership>(e =>
        {
            e.HasIndex(x => new { x.UserId, x.CompanyId }).IsUnique();
            e.HasOne<User>().WithMany().HasForeignKey(x => x.UserId);
            e.HasOne<Company>().WithMany().HasForeignKey(x => x.CompanyId);
        });
        b.Entity<MembershipRole>(e =>
        {
            e.HasKey(x => new { x.MembershipId, x.RoleCode });
            e.HasOne<CompanyMembership>().WithMany().HasForeignKey(x => x.MembershipId);
            e.HasOne<Role>().WithMany().HasForeignKey(x => x.RoleCode);
        });
        b.Entity<PlatformRoleAssignment>(e =>
        {
            e.HasKey(x => new { x.UserId, x.RoleCode });
            e.HasOne<User>().WithMany().HasForeignKey(x => x.UserId);
            e.HasOne<Role>().WithMany().HasForeignKey(x => x.RoleCode);
        });
        b.Entity<Trade>(e => { e.HasIndex(x => x.Name).IsUnique(); e.Property(x => x.Name).HasMaxLength(100); });
        b.Entity<Skill>(e =>
        {
            e.HasIndex(x => new { x.TradeId, x.Name }).IsUnique();
            e.Property(x => x.Name).HasMaxLength(100);
            e.HasOne<Trade>().WithMany().HasForeignKey(x => x.TradeId);
        });
        b.Entity<Technician>(e =>
        {
            e.HasIndex(x => x.UserId).IsUnique();
            e.HasOne<User>().WithMany().HasForeignKey(x => x.UserId);
        });
        b.Entity<TechnicianSkill>(e =>
        {
            e.HasKey(x => new { x.TechnicianId, x.SkillId });
            e.HasOne<Technician>().WithMany().HasForeignKey(x => x.TechnicianId);
            e.HasOne<Skill>().WithMany().HasForeignKey(x => x.SkillId);
        });
        b.Entity<AuditEvent>(e => { e.HasIndex(x => new { x.CompanyId, x.OccurredAt }); e.Property(x => x.Action).HasMaxLength(80); });

        ModelPhase2.Configure(b);
        ModelFoundation2.Configure(b);
        ModelPhase3.Configure(b);
        ModelPhase4.Configure(b);
        ModelPhase7.Configure(b);
        ModelPhase8.Configure(b);

        b.Entity<Role>().HasData(Seed.Roles.Select(r => new Role { Code = r.Key, Scope = r.Value.Scope }));
        b.Entity<Permission>().HasData(Seed.Permissions.Select(p => new Permission { Code = p }));
        b.Entity<RolePermission>().HasData(Seed.Roles.SelectMany(r => r.Value.Perms.Select(p => new RolePermission { RoleCode = r.Key, PermissionCode = p })));
        b.Entity<Trade>().HasData(Seed.Trades());

        // No cascade deletes anywhere: history (audit now, finance later) must never vanish with a parent row.
        foreach (var fk in b.Model.GetEntityTypes().SelectMany(t => t.GetForeignKeys()))
            fk.DeleteBehavior = DeleteBehavior.Restrict;
    }

    // The audit trail is append-only.
    void GuardAudit()
    {
        if (ChangeTracker.Entries<AuditEvent>().Any(e => e.State is EntityState.Modified or EntityState.Deleted))
            throw new InvalidOperationException("Audit events are append-only.");
        if (ChangeTracker.Entries<LedgerEntry>().Any(e => e.State is EntityState.Modified or EntityState.Deleted))
            throw new InvalidOperationException("Ledger entries are immutable; post a reversal instead.");
        if (ChangeTracker.Entries<PaymentEvent>().Any(e => e.State is EntityState.Modified or EntityState.Deleted))
            throw new InvalidOperationException("Payment history is append-only.");
        if (ChangeTracker.Entries<JobFinancialTerms>().Any(e => e.State == EntityState.Deleted))
            throw new InvalidOperationException("Financial terms are never deleted.");
    }
    public override int SaveChanges(bool acceptAllChangesOnSuccess) { GuardAudit(); return base.SaveChanges(acceptAllChangesOnSuccess); }
    public override Task<int> SaveChangesAsync(bool acceptAllChangesOnSuccess, CancellationToken ct = default) { GuardAudit(); return base.SaveChangesAsync(acceptAllChangesOnSuccess, ct); }
}
