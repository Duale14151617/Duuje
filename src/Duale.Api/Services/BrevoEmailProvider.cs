using System.Net.Http.Json;
namespace Duale.Api.Services;

// Email over HTTPS (port 443) using Brevo's transactional API. Use this on hosts that block outbound SMTP ports
// (Render free web services block 25/465/587). Registered only when Brevo:ApiKey is set; it takes priority over SMTP.
// Config: Brevo__ApiKey (an API key, "xkeysib-..."), Brevo__From (a sender address verified in Brevo), Brevo__FromName.
public class BrevoEmailProvider(IConfiguration cfg) : INotificationProvider
{
    static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(15) };
    public string Channel => "email";

    public async Task<SendResult> SendAsync(DeliveryMessage m, CancellationToken ct)
    {
        var key = cfg["Brevo:ApiKey"]; var from = cfg["Brevo:From"];
        if (string.IsNullOrEmpty(key) || string.IsNullOrEmpty(from)) return new SendResult(false, null, "Brevo is not configured.", true);
        try
        {
            using var req = new HttpRequestMessage(HttpMethod.Post, "https://api.brevo.com/v3/smtp/email");
            req.Headers.Add("api-key", key);
            req.Content = JsonContent.Create(new
            {
                sender = new { name = cfg["Brevo:FromName"] ?? "Duale", email = from },
                to = new[] { new { email = m.Address } },
                subject = m.Title,
                textContent = m.Body
            });
            using var res = await Http.SendAsync(req, ct);
            if (res.IsSuccessStatusCode) return new SendResult(true, m.DeliveryId);
            var body = await res.Content.ReadAsStringAsync(ct);
            return new SendResult(false, null, $"Brevo {(int)res.StatusCode}: {body}", (int)res.StatusCode is >= 400 and < 500 and not 429);
        }
        catch (HttpRequestException ex) { return new SendResult(false, null, "Brevo: " + ex.Message); }
        catch (TaskCanceledException ex) when (!ct.IsCancellationRequested) { return new SendResult(false, null, "Brevo timed out: " + ex.Message); }
    }
}
