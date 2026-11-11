using System.Net.Http.Json;
using System.Text.Json;
namespace Duale.Api.Tests;

// Finance scenario builders on top of Kit.
public class FinKit(ApiFactory f, Kit k)
{
    public Kit K => k;

    public async Task<HttpClient> FinanceUserAsync(Kit.Co co)
    {
        var (c, email) = await f.UserAsync();
        (await co.Owner.PostAsJsonAsync($"/companies/{co.Id}/members", new { email, roleCode = "company_finance" })).EnsureSuccessStatusCode();
        return c;
    }

    // The dispatcher proposes, the owner approves (two different people).
    public async Task<Guid> TermsAsync(Kit.Co co, Guid jobId, string payer = "company", decimal charge = 100m, decimal comp = 60m, decimal fee = 5m)
    {
        var t = Kit.Id(await Kit.Json(await co.Dispatcher.PostAsJsonAsync($"/companies/{co.Id}/jobs/{jobId}/financial-terms",
            new { currency = "USD", customerCharge = charge, technicianCompensation = comp, platformFee = fee, payerType = payer })));
        (await co.Owner.PostAsJsonAsync($"/companies/{co.Id}/jobs/{jobId}/financial-terms/{t}/approve", new { })).EnsureSuccessStatusCode();
        return t;
    }

    public Task<HttpResponseMessage> ReviewApproveAsync(Kit.Co co, Guid jobId) =>
        co.Supervisor.PostAsJsonAsync($"/companies/{co.Id}/jobs/{jobId}/review", new { decision = "approve" });

    public async Task<JsonElement> PayableForJobAsync(HttpClient c, Guid companyId, Guid jobId)
    {
        var all = await Kit.Json(await c.GetAsync($"/companies/{companyId}/payables"));
        return all.EnumerateArray().Single(x => x.GetProperty("jobId").GetGuid() == jobId);
    }

    public async Task<Guid> InitiateAsync(HttpClient c, Guid companyId, object body)
    {
        var r = await c.PostAsJsonAsync($"/companies/{companyId}/payments", body);
        return Kit.Id(await Kit.Json(r));
    }

    // Completed job + approved company-paid terms + approved payable. Returns everything a payout test needs.
    public async Task<(Kit.Field Fld, HttpClient Fin, Guid PayableId)> ApprovedPayableAsync(string payer = "company", decimal comp = 60m, decimal fee = 5m)
    {
        var fld = await k.SubmittedJobAsync();
        var fin = await FinanceUserAsync(fld.Co);
        await TermsAsync(fld.Co, fld.JobId, payer, 100m, comp, fee);
        (await ReviewApproveAsync(fld.Co, fld.JobId)).EnsureSuccessStatusCode();
        var pid = Kit.Id(await PayableForJobAsync(fin, fld.Co.Id, fld.JobId));
        if (payer == "company") (await fin.PostAsync($"/companies/{fld.Co.Id}/payables/{pid}/approve", null)).EnsureSuccessStatusCode();
        return (fld, fin, pid);
    }
}
