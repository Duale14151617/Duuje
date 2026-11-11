using Duale.Api.Domain;
namespace Duale.Api.Data;

public static class Seed
{
    public static readonly string[] Permissions =
    [
        "company.read", "company.manage", "staff.manage", "company.verify", "technician.verify", "catalog.manage", "audit.read",
        "relationship.read", "relationship.manage", "customer.manage", "job.read", "job.manage", "job.dispatch",
        "branch.manage", "user.support", "job.review",
        "finance.read", "finance.terms", "finance.terms.approve", "finance.invoice", "finance.payment", "finance.reconcile",
        "finance.refund.request", "finance.refund.approve", "finance.adjust", "report.read", "platform.finance", "platform.oversight", "integration.manage"
    ];

    // Role code -> (scope, permissions). A starting point; confirm assignments with the business.
    public static readonly Dictionary<string, (string Scope, string[] Perms)> Roles = new()
    {
        ["platform_admin"] = ("platform", ["company.verify", "technician.verify", "catalog.manage", "user.support", "platform.oversight", "integration.manage"]),
        ["platform_finance"] = ("platform", ["platform.finance", "platform.oversight"]),
        ["verification_officer"] = ("platform", ["company.verify", "technician.verify"]),
        ["company_owner"] = ("company", ["company.read", "company.manage", "staff.manage", "audit.read", "relationship.read", "relationship.manage", "customer.manage", "job.read", "job.manage", "job.dispatch", "branch.manage", "job.review",
            "finance.read", "finance.terms", "finance.terms.approve", "finance.invoice", "finance.payment", "finance.reconcile", "finance.refund.request", "finance.refund.approve", "finance.adjust", "report.read"]),
        ["dispatcher"] = ("company", ["company.read", "relationship.read", "customer.manage", "job.read", "job.manage", "job.dispatch", "finance.terms", "report.read"]),
        ["supervisor"] = ("company", ["company.read", "relationship.read", "job.read", "job.review", "report.read"]),
        ["company_finance"] = ("company", ["company.read", "job.read", "finance.read", "finance.invoice", "finance.payment", "finance.reconcile", "finance.refund.request", "report.read"]),
        ["auditor"] = ("company", ["company.read", "audit.read", "relationship.read", "job.read", "finance.read", "report.read"]),
    };

    public static string[] CompanyRoles => Roles.Where(r => r.Value.Scope == "company").Select(r => r.Key).ToArray();

    // Trade names come from the spec; qualifications per trade are a business decision and are NOT seeded.
    static readonly string[] TradeNames =
        ["Furniture assembly", "Plumbing", "Electrical work", "Masonry", "Painting", "Tiling", "Carpentry", "Fittings", "Maintenance"];

    public static IEnumerable<Trade> Trades() =>
        TradeNames.Select((n, i) => new Trade { Id = new Guid(i + 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0), Name = n });

    // Starter skills so technicians have something to tick on a fresh install. Inserted once, only when the Skills table is empty;
    // platform admins can add or hide skills afterwards (Platform admin > Catalog).
    static readonly Dictionary<string, string[]> StarterSkillNames = new()
    {
        ["Furniture assembly"] = ["Flat-pack furniture assembly", "Wardrobe and cabinet installation", "Office furniture setup"],
        ["Plumbing"] = ["Pipe installation and repair", "Leak detection and repair", "Water tank and pump installation", "Bathroom and toilet fittings", "Drain unblocking"],
        ["Electrical work"] = ["House wiring", "Socket, switch and light installation", "Distribution board and breaker work", "Solar panel and inverter installation", "Fault finding and repair"],
        ["Masonry"] = ["Block and brick laying", "Plastering and rendering", "Concrete and foundation work", "Fencing and boundary walls"],
        ["Painting"] = ["Interior painting", "Exterior painting", "Wall preparation and putty", "Decorative finishes"],
        ["Tiling"] = ["Floor tiling", "Wall tiling", "Grouting and tile repair"],
        ["Carpentry"] = ["Door and window frames", "Roof timber work", "Built-in cabinets and shelving", "Furniture repair"],
        ["Fittings"] = ["Door and lock fitting", "Window and glass fitting", "Curtain rail and blind fitting", "Gate and grille fitting"],
        ["Maintenance"] = ["General building repairs", "Preventive maintenance rounds", "Generator servicing", "Air conditioner servicing"],
    };

    public static IEnumerable<Skill> StarterSkills() =>
        Trades().SelectMany(t => StarterSkillNames.TryGetValue(t.Name, out var names) ? names.Select(n => new Skill { TradeId = t.Id, Name = n }) : []);
}
