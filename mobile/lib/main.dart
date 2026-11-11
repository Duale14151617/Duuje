import 'package:flutter/material.dart';
import 'api.dart';
import 'screens/auth.dart';
import 'screens/home.dart';

const navy = Color(0xFF0B2545);
const orange = Color(0xFFF26A1B);

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Api.instance.load();
  runApp(const App());
}

class App extends StatefulWidget {
  const App({super.key});
  @override
  State<App> createState() => _AppState();
}

class _AppState extends State<App> {
  late bool signedIn = Api.instance.signedIn;
  @override
  void initState() {
    super.initState();
    Api.instance.onSignedOut = () => setState(() => signedIn = false);
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Duale BuildLink',
        theme: ThemeData(
          useMaterial3: true,
          colorScheme: ColorScheme.fromSeed(seedColor: navy, primary: navy, secondary: orange),
          appBarTheme: const AppBarTheme(backgroundColor: navy, foregroundColor: Colors.white),
        ),
        home: signedIn ? Home(onSignOut: () => setState(() => signedIn = false)) : LoginScreen(onDone: () => setState(() => signedIn = true)),
      );
}
