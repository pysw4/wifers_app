import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:wifers_app/service/api_service.dart';
import 'package:wifers_app/service/location_service.dart';
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
      home: const MyHomePage(title: 'Flutter Demo'),
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
// class CandidatePage extends StatefulWidget {
//   const CandidatePage({super.key});

//   @override
//   State<CandidatePage> createState() => _CandidatePageState();
// }
// class _CandidatePageState extends State<CandidatePage> {
//   final ApiService _api = ApiService();
  
//   // 用于存放获取到的坐标
//   double? _currentLng;
//   double? _currentLat;
  
//   // 用于控制 FutureBuilder 的刷新
//   Future<List<List<double>>>? _candidatesFuture;

//   // 获取位置并触发查询
//   Future<void> _fetchLocationAndCandidates() async {
//     try {
//       // 1. 获取当前位置
//       final position = await LocationService.getCurrentPosition();
//       setState(() {
//         _currentLng = position.longitude;
//         _currentLat = position.latitude;
//       });

//       // 2. 用真实坐标发起 API 请求
//       final future = _api.fetchCandidates(
//         _currentLng!,
//         _currentLat!,
//         1000, // 搜索半径，可根据需要调整或设为变量
//       );
//       setState(() {
//         _candidatesFuture = future;
//       });
//     } catch (e) {
//       // 显示错误提示
//       ScaffoldMessenger.of(context).showSnackBar(
//         SnackBar(content: Text('获取位置失败: $e')),
//       );
//     }
//   }

//   @override
//   Widget build(BuildContext context) {
//     return Scaffold(
//       appBar: AppBar(title: const Text('APs nearby:')),
//       body: Center(
//         child: _candidatesFuture == null
//             ? _buildInitialView()
//             : FutureBuilder<List<List<double>>>(
//                 future: _candidatesFuture,
//                 builder: (context, snapshot) {
//                   if (snapshot.connectionState == ConnectionState.waiting) {
//                     return const CircularProgressIndicator();
//                   }
//                   if (snapshot.hasError) {
//                     return Text('Error: ${snapshot.error}');
//                   }
//                   if (!snapshot.hasData || snapshot.data!.isEmpty) {
//                     return const Text('no aps nearby');
//                   }
//                   final coordinates = snapshot.data!;
//                   return ListView.builder(
//                     itemCount: coordinates.length,
//                     itemBuilder: (ctx, index) {
//                       final lat = coordinates[index][0];
//                       final lng = coordinates[index][1];
//                       return ListTile(
//                         title: Text('lat: $lat, lng: $lng'),
//                       );
//                     },
//                   );
//                 },
//               ),
//       ),
//       floatingActionButton: FloatingActionButton(
//         onPressed: _fetchLocationAndCandidates,
//         child: const Icon(Icons.my_location),
//       ),
//     );
//   }

//   Widget _buildInitialView() {
//     return Column(
//       mainAxisAlignment: MainAxisAlignment.center,
//       children: [
//         const Icon(Icons.location_searching, size: 64, color: Colors.grey),
//         const SizedBox(height: 16),
//         const Text('点击右下角按钮获取位置并搜索'),
//         if (_currentLat != null && _currentLng != null)
//           Text('当前位置: $_currentLat, $_currentLng'),
//       ],
//     );
//   }
// }
class CandidatePage extends StatefulWidget {
  const CandidatePage({super.key});
  @override
  State<CandidatePage> createState() => _CandidatePageState();
}

class _CandidatePageState extends State<CandidatePage> {
  final ApiService _api = ApiService();
  
  double? _currentLng;
  double? _currentLat;
  Future<List<List<double>>>? _candidatesFuture;

  Future<void> _fetchLocationAndCandidates() async {
    try {
      final position = await LocationService.getCurrentPosition();
      setState(() {
        _currentLng = position.longitude;
        _currentLat = position.latitude;
      });
      final future = _api.fetchCandidates(_currentLng!, _currentLat!, 1000);
      setState(() {
        _candidatesFuture = future;
      });
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('获取位置失败: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('附近候选点')),
      body: _candidatesFuture == null
          ? _buildInitialView()
          : FutureBuilder<List<List<double>>>(
              future: _candidatesFuture,
              builder: (context, snapshot) {
                if (snapshot.connectionState == ConnectionState.waiting) {
                  return const Center(child: CircularProgressIndicator());
                }
                if (snapshot.hasError) {
                  return Center(child: Text('错误: ${snapshot.error}'));
                }
                if (!snapshot.hasData || snapshot.data!.isEmpty) {
                  return const Center(child: Text('附近没有找到符合条件的点'));
                }

                final coordinates = snapshot.data!;
                
                // 准备地图中心：优先使用当前位置，否则用第一个候选点
                // final centerLat = _currentLat ?? coordinates[0][0];
                // final centerLng = _currentLng ?? coordinates[0][1];
                final centerLat =  coordinates[0][0];
                final centerLng =  coordinates[0][1];


                return FlutterMap(
                  options: MapOptions(
                    initialCenter: LatLng(centerLat, centerLng),
                    initialZoom: 10,
                  ),
                  children: [
                    TileLayer(
                      urlTemplate: 'https://a.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png',
                      userAgentPackageName: 'com.uab.wifers',
                    ),
                    MarkerLayer(
                      markers: _buildMarkers(coordinates),
                    ),
                  ],
                );
              },
            ),
      floatingActionButton: FloatingActionButton(
        onPressed: _fetchLocationAndCandidates,
        child: const Icon(Icons.my_location),
      ),
    );
  }

  List<Marker> _buildMarkers(List<List<double>> coordinates) {
    return coordinates.map((coord) {
      return Marker(
        point: LatLng(coord[0], coord[1]),   // 纬度, 经度
        width: 40,
        height: 40,
        child: Container(
          // Icons.location_pin,
          // color: Colors.red,
          // size: 40,
         color: Colors.red,
         width: 20,
         height: 20,
        ),
      );
    }).toList();
  }

  Widget _buildInitialView() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.map, size: 64, color: Colors.grey),
          const SizedBox(height: 16),
          const Text('点击右下角按钮定位并显示地图'),
          if (_currentLat != null && _currentLng != null)
            Text('当前位置: $_currentLat, $_currentLng'),
        ],
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
