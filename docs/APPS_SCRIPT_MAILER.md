# Sending email through Google Apps Script (Gmail, no domain)

1. Sign in to the Gmail account that will send the mail and open https://script.google.com -> New project.
2. Replace the code with:

```js
function doPost(e) {
  var out = function (t) { return ContentService.createTextOutput(t); };
  try {
    var data = JSON.parse(e.postData.contents);
    var secret = PropertiesService.getScriptProperties().getProperty("SECRET");
    if (!secret || data.token !== secret) return out("forbidden");
    if (!data.to || !data.subject || !data.body) return out("bad request");
    MailApp.sendEmail({ to: data.to, subject: data.subject, body: data.body, name: "ARMY HQ" });
    return out("ok");
  } catch (err) { return out("error"); }
}
```
3. Project Settings (gear) -> Script properties -> add `SECRET` = a long random string (at least 32 characters).
4. Deploy -> New deployment -> type "Web app". Execute as: **Me**. Who has access: **Anyone**. Authorize when asked.
5. Copy the Web app URL (ends in /exec).
6. On Render set `APPS_SCRIPT_URL` = that URL and `APPS_SCRIPT_TOKEN` = the same SECRET. Remove `BREVO_API_KEY`.
7. Set `ARMYHQ_SITE_URL` = https://armyhq-demo.onrender.com so reset emails contain a link.

Limits: a consumer Gmail account can send about 100 recipients per day through Apps Script, far above this app's volume.
Anyone with the URL AND the secret can send as the account, so keep both private and rotate the secret if either leaks.
