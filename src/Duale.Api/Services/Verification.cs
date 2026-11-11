using Duale.Api.Domain;
namespace Duale.Api.Services;

// Sends verification codes. It reuses the email / sms notification providers, so the day a provider is registered
// (INotificationProvider with Channel "email" or "sms") both notifications and verification codes start working.
// Until then the API says so instead of pretending a code was sent. In Development the code is written to the log.
public interface IVerificationDelivery
{
    bool CanSend(string channel);   // "email" | "sms"
    Task SendAsync(string channel, string target, string code, DateTime expiresAt, CancellationToken ct);
}

public class VerificationDelivery(IEnumerable<INotificationProvider> providers, IHostEnvironment env, ILogger<VerificationDelivery> log) : IVerificationDelivery
{
    public bool CanSend(string channel) => providers.Any(p => p.Channel == channel) || env.IsDevelopment();

    public async Task SendAsync(string channel, string target, string code, DateTime expiresAt, CancellationToken ct)
    {
        var provider = providers.FirstOrDefault(p => p.Channel == channel);
        if (provider is null)
        {
            if (env.IsDevelopment()) log.LogWarning("DEV ONLY {Channel} verification code for {Target}: {Code}", channel, target, code);
            return;
        }
        var result = await provider.SendAsync(new DeliveryMessage(channel, target, "Your Duale verification code", $"Your verification code is {code}. It expires at {expiresAt:HH:mm} UTC.", Guid.NewGuid().ToString()), ct);
        if (!result.Ok) throw new InvalidOperationException(result.Error ?? "Delivery failed.");
    }
}
