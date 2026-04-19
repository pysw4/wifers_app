import 'package:flutter/material.dart';
import 'package:wifers_app/service/api_service.dart';
void main() {
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({super.key});

  // This widget is the root of your application.
  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Flutter Demo',
      theme: ThemeData(
       // hot reload will only change the color scheme, not the entire theme. 
       // hot restart will change the entire theme.
        colorScheme: .fromSeed(seedColor: Colors.blue),
      ),
      home: const MyHomePage(title: 'Flutter Demo Home Page'),
    );
  }
}
class MyHomePage extends StatefulWidget {
  const MyHomePage({super.key, required this.title});

  // This widget is the home page of your application. 

  // This class is the configuration for the state. It holds the values (in this
  // case the title) provided by the parent (in this case the App widget) and
  // used by the build method of the State. Fields in a Widget subclass are
  // always marked "final".

  final String title;
  @override
  State<MyHomePage> createState() => _MyHomePageState();
}
class CandidatePage extends StatelessWidget {
  final ApiService _api = ApiService();

  @override
  Widget build(BuildContext context) {
   
    final future = _api.fetchCandidates(2.115, 41.5, 1000);

    return Scaffold(
      appBar: AppBar(title: Text('candidates')),
      body: Center(
        child: FutureBuilder<List<int>>(
          future: future,
          builder: (context, snapshot) {
            // 正在加载
            if (snapshot.connectionState == ConnectionState.waiting) {
              return CircularProgressIndicator();
            }
            // 发生错误
            if (snapshot.hasError) {
              return Text('Error: ${snapshot.error}');
            }
            // 数据为空
            if (!snapshot.hasData || snapshot.data!.isEmpty) {
              return Text('No matching candidates found');
            }
            // 展示列表
            final ids = snapshot.data!;
            return ListView.builder(
              itemCount: ids.length,
              itemBuilder: (ctx, index) => ListTile(
                title: Text('Node ID: ${ids[index]}'),
              ),
            );
          },
        ),
      ),
    );
  }
}
class _MyHomePageState extends State<MyHomePage> {
  int currentIndex = 0;

  final pages = [
    Center(child: Text("Home")),
    
    Column(
      children: [ 
        ElevatedButton(
          onPressed: () {},
          child: Text("Load Data"),
        ),

        Expanded(
          child: 
          ListView(
              children: [
            ListTile(title: Text("Item 1")),
            ListTile(title: Text("Item 2")),
            ListTile(title: Text("Item 3")),
              ],
          ),
        ),
      ]
    ),

  
    CandidatePage(),
  ];

  @override
  Widget build(BuildContext context) {
    // This method is rerun every time setState is called, for instance as done
    // by the _incrementCounter method above.
    //
    // The Flutter framework has been optimized to make rerunning build methods
    // fast, so that you can just rebuild anything that needs updating rather
    // than having to individually change instances of widgets.
    return Scaffold(
      appBar: AppBar(
        // TRY THIS: Try changing the color here to a specific color (to
        // Colors.amber, perhaps?) and trigger a hot reload to see the AppBar
        // change color while the other colors stay the same.
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
        // Here we take the value from the MyHomePage object that was created by
        // the App.build method, and use it to set our appbar title.
        title: Text(widget.title),
      ),
      body: pages[currentIndex],

       bottomNavigationBar: BottomNavigationBar(
        currentIndex: currentIndex,
        onTap: (index) {
          setState(() {
            currentIndex = index;
          });
        },
        items: [
          BottomNavigationBarItem(
            icon: Icon(Icons.home),
            label: "Home",
          ),
          BottomNavigationBarItem(
            icon: Icon(Icons.star),
            label: "Recommend",
          ),
          BottomNavigationBarItem(
            icon: Icon(Icons.settings),
            label: "Settings",
          ),
        ],
      ),
    );
  }
}
