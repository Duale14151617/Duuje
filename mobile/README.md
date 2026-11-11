# Duale BuildLink technician app (Flutter, Android first)

Offers (accept/decline), availability windows, ID and qualification document upload with review status, skills, service areas,
company invitations, notifications, sign-in with authenticator code, password recovery, MFA setup.

```
flutter create . --platforms=android --org com.duale --project-name duale_technician   # generates android/ (keeps lib/ and pubspec.yaml)
flutter pub get
flutter run --dart-define=API_BASE=http://10.0.2.2:8080     # 10.0.2.2 = your computer from the Android emulator
```
Add `<uses-permission android:name="android.permission.INTERNET"/>` to `android/app/src/main/AndroidManifest.xml` for release builds
(the generated debug manifest has it, the main one may not). Use HTTPS for any real deployment.

Not in this drop (Phase 3): en-route/arrived/in-progress updates, work reports, photo evidence, offline queue. Network errors are
shown as plain messages and the user retries; there is no offline sync yet. **Not compiled here** (no Flutter SDK available), so
expect small fixes on the first `flutter analyze`.
