using System.Net;
using System.Net.Mail;
namespace Duale.Api.Services;

// Email over SMTP (works with Gmail + an app password, or any SMTP server). Registered only when Smtp:Host is set.
// Gmail: Smtp__Host=smtp.gmail.com, Smtp__Port=587, Smtp__User=<gmail address>, Smtp__Password=<16-char app password>.
public class SmtpEmailProvider(IConfiguration cfg) : INotificationProvider
{
    public string Channel => "email";

    public async Task<SendResult> SendAsync(DeliveryMessage m, CancellationToken ct)
    {
        var host = cfg["Smtp:Host"]; var user = cfg["Smtp:User"]; var pass = cfg["Smtp:Password"];
        var port = int.TryParse(cfg["Smtp:Port"], out var p) ? p : 587;
        var from = cfg["Smtp:From"] is { Length: > 0 } f ? f : user;
        if (string.IsNullOrEmpty(host) || string.IsNullOrEmpty(from)) return new SendResult(false, null, "SMTP is not configured.", true);
        try
        {
            using var client = new SmtpClient(host, port) { EnableSsl = cfg["Smtp:EnableSsl"] != "false", Timeout = 20000 };
            if (!string.IsNullOrEmpty(user)) client.Credentials = new NetworkCredential(user, pass);
            using var msg = new MailMessage(new MailAddress(from, cfg["Smtp:FromName"] ?? "Duale"), new MailAddress(m.Address))
            { Subject = m.Title, Body = m.Body };
            msg.Headers.Add("X-Duale-Delivery-Id", m.DeliveryId);
            await client.SendMailAsync(msg, ct);
            return new SendResult(true, m.DeliveryId);
        }
        catch (FormatException ex) { return new SendResult(false, null, "Invalid email address: " + ex.Message, true); }
        catch (SmtpException ex) { return new SendResult(false, null, "SMTP: " + ex.Message); }
    }
}
