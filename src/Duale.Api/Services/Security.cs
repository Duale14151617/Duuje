using System.IdentityModel.Tokens.Jwt;
using System.Security.Cryptography;
using System.Text;
using Duale.Api.Data;
using Duale.Api.Domain;
using Microsoft.AspNetCore.Identity;
using Microsoft.EntityFrameworkCore;
using Microsoft.IdentityModel.Tokens;
namespace Duale.Api.Services;

// ---- RFC 6238 TOTP (HMAC-SHA1, 30 s, 6 digits) ----
public static class Totp
{
    const string Alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
    public static string NewSecret() => Base32(RandomNumberGenerator.GetBytes(20));

    public static string Base32(byte[] data)
    {
        var sb = new StringBuilder(); int buffer = 0, bits = 0;
        foreach (var b in data)
        {
            buffer = (buffer << 8) | b; bits += 8;
            while (bits >= 5) { sb.Append(Alphabet[(buffer >> (bits - 5)) & 31]); bits -= 5; }
        }
        if (bits > 0) sb.Append(Alphabet[(buffer << (5 - bits)) & 31]);
        return sb.ToString();
    }

    public static byte[] FromBase32(string s)
    {
        var res = new List<byte>(); int buffer = 0, bits = 0;
        foreach (var ch in s.Trim().TrimEnd('=').ToUpperInvariant())
        {
            var v = Alphabet.IndexOf(ch);
            if (v < 0) throw new FormatException("Invalid base32.");
            buffer = (buffer << 5) | v; bits += 5;
            if (bits >= 8) { res.Add((byte)((buffer >> (bits - 8)) & 0xFF)); bits -= 8; }
        }
        return res.ToArray();
    }

    public static string Code(byte[] key, long step, int digits = 6)
    {
        var counter = BitConverter.GetBytes(step);
        if (BitConverter.IsLittleEndian) Array.Reverse(counter);
        var hash = HMACSHA1.HashData(key, counter);
        var off = hash[^1] & 0x0F;
        var bin = ((hash[off] & 0x7F) << 24) | (hash[off + 1] << 16) | (hash[off + 2] << 8) | hash[off + 3];
        return (bin % (int)Math.Pow(10, digits)).ToString().PadLeft(digits, '0');
    }

    public static long Step(DateTimeOffset t) => t.ToUnixTimeSeconds() / 30;

    // Accepts +-1 step of clock drift; a step at or below lastStep is rejected so a code cannot be replayed.
    public static long? Verify(byte[] key, string? code, DateTimeOffset now, long lastStep)
    {
        if (code is null || code.Length != 6 || !code.All(char.IsAsciiDigit)) return null;
        for (var d = -1; d <= 1; d++)
        {
            var s = Step(now) + d;
            if (s > lastStep && CryptographicOperations.FixedTimeEquals(Encoding.ASCII.GetBytes(Code(key, s)), Encoding.ASCII.GetBytes(code))) return s;
        }
        return null;
    }
}

// AES-256-GCM for the TOTP secret at rest. Key: Mfa:Key (base64, 32 bytes) from the secret store.
public class SecretBox(IConfiguration cfg)
{
    byte[] Key => Convert.FromBase64String(cfg["Mfa:Key"] ?? throw new InvalidOperationException("Mfa:Key is required."));
    public static void Validate(IConfiguration cfg)
    {
        byte[] k; try { k = Convert.FromBase64String(cfg["Mfa:Key"] ?? ""); } catch (FormatException) { k = []; }
        if (k.Length != 32) throw new InvalidOperationException("Mfa:Key must be base64 of exactly 32 bytes (e.g. `openssl rand -base64 32`).");
    }
    public string Seal(string plain)
    {
        var nonce = RandomNumberGenerator.GetBytes(12); var data = Encoding.UTF8.GetBytes(plain);
        var cipher = new byte[data.Length]; var tag = new byte[16];
        using var gcm = new AesGcm(Key, 16); gcm.Encrypt(nonce, data, cipher, tag);
        return Convert.ToBase64String(nonce.Concat(tag).Concat(cipher).ToArray());
    }
    public string Open(string sealedText)
    {
        var all = Convert.FromBase64String(sealedText);
        var plain = new byte[all.Length - 28];
        using var gcm = new AesGcm(Key, 16); gcm.Decrypt(all[..12], all[28..], all[12..28], plain);
        return Encoding.UTF8.GetString(plain);
    }
}

// Short-lived token proving the password step succeeded. Different audience, so it can never act as an access token.
public class MfaTokens(IConfiguration cfg)
{
    const string Aud = "duale-mfa";
    string Issuer => cfg["Jwt:Issuer"] ?? "duale-buildlink";
    public string Issue(User u) => new JwtSecurityTokenHandler().WriteToken(new JwtSecurityToken(Issuer, Aud,
        [new System.Security.Claims.Claim("sub", u.Id.ToString())], expires: DateTime.UtcNow.AddMinutes(5),
        signingCredentials: new SigningCredentials(Auth.TokenService.Key(cfg), SecurityAlgorithms.HmacSha256)));
    public Guid? Read(string? token)
    {
        if (string.IsNullOrWhiteSpace(token)) return null;
        try
        {
            var h = new JwtSecurityTokenHandler { MapInboundClaims = false };
            var p = h.ValidateToken(token, new TokenValidationParameters
            {
                ValidIssuer = Issuer, ValidAudience = Aud, IssuerSigningKey = Auth.TokenService.Key(cfg), ClockSkew = TimeSpan.FromSeconds(15)
            }, out _);
            return Guid.Parse(p.FindFirst("sub")!.Value);
        }
        catch { return null; }
    }
}

public class MfaService(AppDbContext db, SecretBox box)
{
    public const int MaxFailures = 5;
    static string Hash(string s) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(s))).ToLowerInvariant();
    static string Norm(string s) => s.Trim().Replace("-", "").Replace(" ", "").ToLowerInvariant();

    public (string Plain, string Hash)[] NewRecoveryCodes(int n = 10) => Enumerable.Range(0, n).Select(_ =>
    {
        var raw = Convert.ToHexString(RandomNumberGenerator.GetBytes(5)).ToLowerInvariant();   // 40 bits, single use
        return ($"{raw[..5]}-{raw[5..]}", Hash(raw));
    }).ToArray();

    // Checks an authenticator code, falling back to a single-use recovery code. Locks the factor after repeated failures.
    public async Task<(bool Ok, string? Error)> CheckAsync(User u, string? code, CancellationToken ct)
    {
        if (u.MfaLockedUntil is { } until && until > DateTime.UtcNow) return (false, "Too many attempts. Try again later.");
        var ok = false;
        if (!string.IsNullOrWhiteSpace(code) && u.MfaSecretEnc is not null)
        {
            var step = Totp.Verify(Totp.FromBase32(box.Open(u.MfaSecretEnc)), code.Trim(), DateTimeOffset.UtcNow, u.MfaLastStep);
            if (step is { } s) { u.MfaLastStep = s; ok = true; }
            else
            {
                var h = Hash(Norm(code));
                var rc = await db.MfaRecoveryCodes.FirstOrDefaultAsync(x => x.UserId == u.Id && x.CodeHash == h && x.UsedAt == null, ct);
                if (rc is not null) { rc.UsedAt = DateTime.UtcNow; ok = true; }
            }
        }
        if (ok) { u.MfaFailures = 0; u.MfaLockedUntil = null; }
        else
        {
            u.MfaFailures++;
            if (u.MfaFailures >= MaxFailures) { u.MfaLockedUntil = DateTime.UtcNow.AddMinutes(15); u.MfaFailures = 0; }
        }
        await db.SaveChangesAsync(ct);
        return ok ? (true, null) : (false, "Invalid code.");
    }
}

// ---- Password recovery delivery. No mail/SMS provider is chosen yet, so nothing is ever sent in production. ----
public interface IRecoveryDelivery { Task SendAsync(string email, string token, DateTime expiresAt, CancellationToken ct); }

public class ConsoleRecoveryDelivery(ILogger<ConsoleRecoveryDelivery> log) : IRecoveryDelivery
{
    public Task SendAsync(string email, string token, DateTime expiresAt, CancellationToken ct)
    { log.LogWarning("DEV ONLY recovery token for {Email}: {Token}", email, token); return Task.CompletedTask; }
}
public class NotConfiguredRecoveryDelivery(ILogger<NotConfiguredRecoveryDelivery> log) : IRecoveryDelivery
{
    public Task SendAsync(string email, string token, DateTime expiresAt, CancellationToken ct)
    { log.LogError("Password recovery requested but no delivery provider is configured; nothing was sent."); return Task.CompletedTask; }
}

// ---- Private file storage and signed links ----
public interface IFileStore { Task SaveAsync(string key, byte[] data, CancellationToken ct); Task<Stream?> OpenAsync(string key, CancellationToken ct); }

public class LocalFileStore(IConfiguration cfg) : IFileStore
{
    string Root => Path.GetFullPath(cfg["Files:Root"] ?? "/data/files");
    string PathFor(string key)
    {
        if (key.Length != 32 || !key.All(Uri.IsHexDigit)) throw new ArgumentException("Bad storage key.");
        return Path.Combine(Root, key[..2], key);
    }
    public async Task SaveAsync(string key, byte[] data, CancellationToken ct)
    { var p = PathFor(key); Directory.CreateDirectory(Path.GetDirectoryName(p)!); await File.WriteAllBytesAsync(p, data, ct); }
    public Task<Stream?> OpenAsync(string key, CancellationToken ct)
    { var p = PathFor(key); return Task.FromResult<Stream?>(File.Exists(p) ? File.OpenRead(p) : null); }
}

// Plug a real scanner (e.g. ClamAV) in here. The default accepts everything, which is NOT production-ready.
public interface IUploadScanner { Task<bool> IsCleanAsync(byte[] data, CancellationToken ct); }
public class NoopUploadScanner : IUploadScanner { public Task<bool> IsCleanAsync(byte[] data, CancellationToken ct) => Task.FromResult(true); }

public class SignedLinks(IConfiguration cfg)
{
    byte[] Key => SHA256.HashData(Encoding.UTF8.GetBytes("file-links:" + cfg["Jwt:Key"]));
    public int TtlSeconds => int.TryParse(cfg["Files:LinkSeconds"], out var v) ? v : 120;
    static string B64(byte[] b) => Convert.ToBase64String(b).TrimEnd('=').Replace('+', '-').Replace('/', '_');
    static byte[] FromB64(string s) { s = s.Replace('-', '+').Replace('_', '/'); return Convert.FromBase64String(s.PadRight(s.Length + (4 - s.Length % 4) % 4, '=')); }

    // Bound to the document AND the user it was issued to.
    public string Create(Guid docId, Guid userId, DateTimeOffset now)
    {
        var payload = $"{docId:N}|{userId:N}|{now.AddSeconds(TtlSeconds).ToUnixTimeSeconds()}";
        var body = B64(Encoding.UTF8.GetBytes(payload));
        return body + "." + B64(HMACSHA256.HashData(Key, Encoding.ASCII.GetBytes(body)));
    }
    public (Guid DocId, Guid UserId)? Validate(string token, DateTimeOffset now)
    {
        try
        {
            var parts = token.Split('.'); if (parts.Length != 2) return null;
            var expected = HMACSHA256.HashData(Key, Encoding.ASCII.GetBytes(parts[0]));
            if (!CryptographicOperations.FixedTimeEquals(expected, FromB64(parts[1]))) return null;
            var f = Encoding.UTF8.GetString(FromB64(parts[0])).Split('|');
            if (long.Parse(f[2]) < now.ToUnixTimeSeconds()) return null;
            return (Guid.ParseExact(f[0], "N"), Guid.ParseExact(f[1], "N"));
        }
        catch { return null; }
    }
}
