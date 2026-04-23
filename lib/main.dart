import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:wifers_app/services/api_service.dart';
import 'package:wifers_app/services/location_service.dart';
import 'package:url_launcher/url_launcher.dart';
import 'package:wifers_app/models/ap_info.dart';
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
      home: const MyHomePage(title: 'Wifers Flutter Demo'),
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
class CandidatePage extends StatefulWidget {
  const CandidatePage({super.key});
  @override
  State<CandidatePage> createState() => _CandidatePageState();
}

class _CandidatePageState extends State<CandidatePage> {
  final ApiService _api = ApiService();
  
  double? _currentLng;
  double? _currentLat;
  Future<List<APInfo>>? _candidatesFuture = null;
  List<List<double>> favoriteAps = [];

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
        SnackBar(content: Text('Error at access the local location: $e')),
      );
    }
  }
  
  void _onMarkerTapped(double lat, double lng) {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (BuildContext bottomSheetContext) {
        return SafeArea(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const SizedBox(height: 8),
              // 顶部拖动指示条
              Container(
                width: 40,
                height: 4,
                decoration: BoxDecoration(
                  color: Colors.grey[400],
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
              const SizedBox(height: 16),

              // 标题：坐标信息
              ListTile(
                leading: const Icon(Icons.location_on, color: Colors.red),
                title: Text('选中位置'),
                subtitle: Text('纬度: ${lat.toStringAsFixed(6)}\n经度: ${lng.toStringAsFixed(6)}'),
              ),
              const Divider(),

              // 导航按钮
              ListTile(
                leading: const Icon(Icons.directions_walk, color: Colors.blue),
                title: const Text('步行导航至此'),
                onTap: () {
                  Navigator.pop(bottomSheetContext); // 关闭底部菜单
                  _navigateToExternal(lat, lng);             // 调用导航方法
                },
              ),
              
              ListTile(
                leading: Icon(Icons.bookmark_border),
                title: Text('保存此位置'),
                onTap: () { 
                  Navigator.pop(bottomSheetContext); 
                  _saveToFavorite(lat, lng);
                },
              ),
            ],
          ),
        );
      },
    );
  }
  void _saveToFavorite(lat, lng){
    favoriteAps.add([lat,lng]);
  }
  void _navigateToExternal(double destLat, double destLng) async {
    // 如果有当前位置，设置为起点；否则仅指定终点
    final startLat = _currentLat;
    final startLng = _currentLng;

    String url;
    if (startLat != null && startLng != null) {
      // 同时指定起点和终点，步行模式
      url = 'https://www.google.com/maps/dir/?api=1&origin=$startLat,$startLng&destination=$destLat,$destLng&travelmode=walking';
    } else {
      // 仅指定终点
      url = 'https://www.google.com/maps/search/?api=1&query=$destLat,$destLng';
    }

    final uri = Uri.parse(url);
    try {
      if (await canLaunchUrl(uri)) {
        await launchUrl(uri, mode: LaunchMode.externalApplication);
      } else {
        // 尝试 Apple Maps (iOS)
        final appleUrl = Uri.parse('http://maps.apple.com/?daddr=$destLat,$destLng&dirflg=w');
        if (await canLaunchUrl(appleUrl)) {
          await launchUrl(appleUrl, mode: LaunchMode.externalApplication);
        } else {
          throw '无法打开地图应用';
        }
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('导航失败: $e')),
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
                final centerLat = _currentLat ?? coordinates[0][0];
                final centerLng = _currentLng ?? coordinates[0][1];
              
                // final centerLat =  coordinates[0][0];
                // final centerLng =  coordinates[0][1];


                return FlutterMap(
                  options: MapOptions(
                    initialCenter: LatLng(centerLat, centerLng),
                    initialZoom: 17,
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
    List<Marker> markers = coordinates.map((coord) {
      return Marker(
        point: LatLng(coord[0], coord[1]),   // 纬度, 经度
        width: 20,
        height: 20,
        child: GestureDetector(
          onTap: () {
            _onMarkerTapped(coord[0],coord[1]);
          },
          child: const Icon(
            Icons.location_pin,
            color: Colors.red,
            size: 20,
          ),
        ),
      );
    }).toList();

    if (_currentLat != null && _currentLng != null) {
    markers.add(
      Marker(
        point: LatLng(_currentLat!, _currentLng!),
        width: 30,
        height: 30,
        child: const Icon(Icons.person_pin_circle, color: Colors.blue, size: 30),
      ),
    );
  }
    return markers;
  }
  Widget _buildInitialView() {
    return Center(
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const Icon(Icons.map, size: 64, color: Colors.grey),
          const SizedBox(height: 16),
          const Text('Press the button to show the aps map'),
          if (_currentLat != null && _currentLng != null)
            Text('Current Location: $_currentLat, $_currentLng'),
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
