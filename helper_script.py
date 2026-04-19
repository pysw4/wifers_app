import numpy as np
import matplotlib.pyplot as plt
import networkx as nx
import random
import geopandas as gpd
import folium
import osmnx as ox


RANDOM_SEED = 0
random.seed(a=RANDOM_SEED)

########################################
#---------------FUNCTIONS--------------#
########################################

#======Functional======#

def find_qualified_in_range(G, original_target, acceptable_range, verbose=0, weight_attr="length") -> list:
    """
    Recieves a graph, a target, and a "grace range" and calculates all the possible
    destinations within the "grace range" of the target.

    Calculates the shortest path between the target and all the nodes of the graph and 
    keeps the ones that are within the range.
    """
    distances, paths = nx.single_source_dijkstra(G, original_target, weight=weight_attr)
    qualified_destinations : list = []
    if verbose:
        print("Original target:", original_target)
    for n in paths:
        if distances[n] <= acceptable_range:
            qualified_destinations.append(n)
            if verbose:
                print(">============================<")
                print("-->Destination", n)
                print("-->Path:", paths[n])
                print("-->Costs", distances[n])
            
    return qualified_destinations

def find_paths_to_candidates(G, source:any, target_neighbours:list, weight_attr="length") -> list:
    """
    Recieves a graph, a source (current location) and a list of targets.

    Calculates the shortest weighed path with dijkstra to every target and puts them
    in a dictionary that stores the cost and the path itself.    
    """

    distances, paths = nx.single_source_dijkstra(G, source, weight=weight_attr)
    weighted_paths : dict = {}
    for n in target_neighbours:
        if n in paths: #To make sure there is a path to the target
            weighted_paths[n] = (distances[n], paths[n])
        else:
            print("No path exists from node", source, "to node", n, sep=" ")
            weighted_paths[n] = (float('inf'),   [])

    return weighted_paths

def pick_best_candidate(user_preferences:list, candidate_ap_properties:dict) -> any:
    """
    user_preferences: the user preferences, a list of how the user values each thin
    candidate_ap_properties: a dict where each key is a candidate (each with its label) 
        and the values are the propperties of the ap it is connected to

    Returns the label of the chosen node (could be an integer or a string)
    """
    best_score = -1000000
    best_candidate = None
    for (candidate, properties), preferences in zip(candidate_ap_properties.items(), user_preferences):
        weighted_score = sum([x*w for x,w in zip(properties, preferences)])
        if weighted_score > best_score:
            best_score = weighted_score
            best_candidate = candidate

    return best_candidate, best_score



def find_ap_near_candidates(G, candidates: list, aps: list, amount=1) -> list:
    """
    This function will compute the specified amount of APs closest to each candidate.

    Recieves:
    - G: the full graph
    - candidates: a list of the labels of candidates
    - aps: a list with the labels of all the aps of the university
    - amount: how many nearest aps to find

    Returns:
    a list with (candidate, [nearest1, nearest2, ... nearestamount])

    How?
    First to reduce the search limit to the APs that are on the same floor as the candidate since
        the signal doesn't penetrate floors/ceilings
    Then find the minimum in euclidean distance from the candidate to each AP and pick the minimum
    Pop this minimum from the list of possible APs and repeat
    """

    pairs = []
    for candidate in candidates:
        node = G.nodes[candidate]
        c_floor = node["height"]
        floor_compatible_aps = [ap for ap in aps if G.nodes[ap]["height"] == c_floor]

        x1, y1 = node["x"], node["y"]
        nearest = []
        nearest_ap = min(
            floor_compatible_aps,
            key=lambda ap: ((G.nodes[ap]["x"] - x1)**2 +(G.nodes[ap]["y"] - y1)**2)
        )
        nearest.append(nearest_ap)
        for _ in range(amount-1):
            floor_compatible_aps.remove(nearest_ap)
            nearest_ap = min(
                floor_compatible_aps,
                key=lambda ap: ((G.nodes[ap]["x"] - x1)**2 +(G.nodes[ap]["y"] - y1)**2)
            )
            nearest.append(nearest_ap)
        pairs.append((candidate, nearest))

    return pairs

    


#======Graph structure functions======#

def add_aps_to_graph(G, path, bbox) -> list:
    """
    This function recieves the Graph (graph), 
    the path (str) of the geojson with the APs coordinates & data and
    the bounding box (list) which tells which APs to add (only add them if inside bbox)
    
    It will return a (list) of all the APs it has added to be able to mantain reference to them
    """
    print("\nLoading geolocation data...")
    gdf_geo = gpd.read_file(path)
    print(f"  OK - {len(gdf_geo)} APs with geolocation")

    ap_nodes = []
    for _, row in gdf_geo.iterrows():
        point = row.geometry

        lon = point.x
        lat = point.y

        node_id = row["USER_NOM_A"]

        if (bbox[0] < lon < bbox[2]) and (bbox[-1] < lat < bbox[1]): #added this bc there are some very far away APs
            # Add the node with the attributes we want
            G.add_node(
                node_id,
                x = lon, y = lat,
                node_type="ap",
                height=row["Num_Planta"],
                building=row["USER_EDIFI"]
                #espacio=row["USER_Espai"]
            )
            ap_nodes.append(node_id)            


    print(f"  OK - Added {len(ap_nodes)} nodes to graph")
    return ap_nodes

def create_and_link_engineering_faculty_graph(G) -> list:
    """
    This function will contain the manual work of creating the graph of the engineering faculty
    and of linking it to the whole graph G.
    It will first find the coordinates of the door using osmnx web. Then create the graph
    by hand. When that is done, it will be shifted using the SCALE constant, to convert
    from local coordinates in meters to (LAT, LON)

    It will return a list of lists of the nodes it has added to keep track of 
    which faculty is which and which nodes are transitions (stairs)
    It will also return the graph for debugging
    """
    #SCALE = 1 / 111000 # to convert the local coordinates of engineering to Lat Lon
    door_lat = 41.500182
    door_lon =  2.111848

    G_indoor = nx.MultiDiGraph()

    # Keep track of the nodes we add
    indoor_engineering_nodes = []
    transition_nodes = []
    qualified_nodes = []

    ##############################################
    #----1. DEFINE LOCAL COORDINATES (meters)----#
    ##############################################
    nodes = {
        #===DOOR (anchor)===#
        "door_main": (-6, 1, "door", "transition", 0),

        #========HYBRID NODES========#
        "reception_tables": (-20, -1, "tables", "hybrid", 0),
        "reception_sofas": (-12, -9, "hall", "hybrid", 0),
        "main_hall_q1_tables": (4, 13, "tables", "hybrid", 0),
        "main_hall_tables1": (4, 21, "tables", "hybrid", 0),
        "main_hall_q2_tables": (4, 36, "tables", "hybrid", 0),
        "main_hall_tables2": (4, 48, "tables", "hybrid", 0),
        "main_hall_q3_tables": (4, 58, "tables", "hybrid", 0),
        "main_hall_tables3": (4, 69, "tables", "hybrid", 0),
        "main_hall_q4_tables": (4, 80, "tables", "hybrid", 0),

        #========COMMON NODES========#
        #------------FLOOR 1------------------------
        "reception1": (-6, -2, "hall", "common", 0),
        "open_labs": (-45, -1, "hall", "common", 0),
        "main_hall_start": (4, -2, "hall", "common", 0),
        "main_hall_seminars": (4, -5, "hall", "common", 0),

        "door_q1_0003": (15, 13, "hall", "common", 0),
        "door_aula_informatica_A": (27, 13, "hall", "common", 0),
        "door_small_room": (35, 13, "hall", "common", 0),
        "door_aula_informatica_B": (44, 13, "hall", "common", 0),
        "end_q1": (50, 13, "hall", "common", 0),

        "door_q2_0003": (15, 36, "hall", "common", 0),
        "door_q2_0007": (24, 36, "hall", "common", 0),
        "door_q2_0009": (30, 36, "hall", "common", 0),
        "door_q2_0011": (35, 36, "hall", "common", 0),
        "door_q2_0013": (42, 36, "hall", "common", 0),
        "door_q2_0016": (44, 36, "hall", "common", 0),
        "end_q2": (51, 36, "hall", "common", 0),

        "door_q3_0003": (15, 58, "hall", "common", 0),
        "door_q3_0007": (27, 58, "hall", "common", 0),
        "door_q3_0011": (42, 58, "hall", "common", 0),
        "end_q3": (51, 58, "hall", "common", 0),

        "door_q4_0003": (15, 80, "hall", "common", 0),
        "door_q4_0007": (27, 80, "hall", "common", 0),
        "door_q4_0011": (42, 80, "hall", "common", 0),
        "end_q4": (51, 80, "hall", "common", 0),

        "entrance_q5": (63, 20, "hall", "common", 0),
        "hall_q5": (74, 20, "hall", "common", 0),
        "entrance_q6": (63, 50, "hall", "common", 0),
        "hall_q6": (74, 50, "hall", "common", 0),
        #------------END FLOOR 1------------------------

        #------------FLOOR 2------------------------
        "upper_hall_q1": (4, 12, "hall", "common", 1),
        "door_q1_1003": (14, 12, "hall", "common", 1),
        "door_q1_1007": (25, 12, "hall", "common", 1),
        "door_q1_1011": (42, 12, "hall", "common", 1),
        "end_upper_q1": (50, 12, "hall", "common", 1),

        "upper_hall_q2": (4, 34, "hall", "common", 1),
        "door_q2_1003": (12, 34, "hall", "common", 1),
        "door_q2_1005": (21, 34, "hall", "common", 1),
        "door_q2_1009": (32, 34, "hall", "common", 1),
        "door_q2_1013": (43, 34, "hall", "common", 1),
        "end_upper_q2": (50, 34, "hall", "common", 1),

        "upper_hall_q3": (4, 57, "hall", "common", 1),
        "door_q3_1003": (14, 57, "hall", "common", 1),
        "door_q3_1007": (28, 57, "hall", "common", 1),
        "door_q3_1011": (42, 57, "hall", "common", 1),
        "end_upper_q3": (50, 57, "hall", "common", 1),

        "upper_hall_q4": (4, 80, "hall", "common", 1),
        "door_q4_1003": (12, 80, "hall", "common", 1),
        "door_q4_1005": (21, 80, "hall", "common", 1),
        "door_q4_1009": (32, 80, "hall", "common", 1),
        "door_q4_1013": (43, 80, "hall", "common", 1),
        "end_upper_q4": (50, 80, "hall", "common", 1),

        "glass_q4": (55, 80, "hall", "common", 1),
        "glass_q3": (55, 57, "hall", "common", 1),
        "glass_q2": (55, 34, "hall", "common", 1),
        "glass_q1": (55, 12, "hall", "common", 1),

        "glass_q5": (55, 20, "hall", "common", 1),
        "entrance_upper_q5": (64, 20, "hall", "common", 1),
        "door_q5_1005": (72, 20, "hall", "common", 1),
        "door_q5_1009": (84, 20, "hall", "common", 1),
        "door_q5_1010": (91, 20, "hall", "common", 1),
        "door_q5_1011": (101, 20, "hall", "common", 1),
        "end_upper_q5": (108, 20, "hall", "common", 1),

        "glass_q6": (55, 50, "hall", "common", 1),
        "entrance_upper_q6": (63, 50, "hall", "common", 1),
        "door_q6_1006": (78, 50, "hall", "common", 1),
        "door_q6_1011": (91, 50, "hall", "common", 1),
        "door_q6_1012": (100, 50, "hall", "common", 1),
        "end_upper_q6": (108, 50, "hall", "common", 1),
        #------------END FLOOR 2------------------------

        #------------FLOOR 3------------------------
        "entrance_upper2_q5": (64, 20, "hall", "common", 2),
        "door_q5_2003": (76, 20, "hall", "common", 2),
        "door_q5_2006": (84, 20, "hall", "common", 2),
        "door_q5_2007": (91, 20, "hall", "common", 2),
        "door_q5_2008": (97, 20, "hall", "common", 2),
        "door_q5_2009": (103, 20, "hall", "common", 2),
        "end_upper2_q5": (108, 20, "hall", "common", 2),

        "entrance_upper2_q6": (64, 50, "hall", "common", 2),
        "door_q6_2004": (72, 50, "hall", "common", 2),
        "door_q6_2005": (82, 50, "hall", "common", 2),
        "door_q6_2007": (90, 50, "hall", "common", 2),
        "door_q6_2008": (97, 50, "hall", "common", 2),
        "door_q6_2009": (103, 50, "hall", "common", 2),
        "end_upper2_q6": (108, 50, "hall", "common", 2),
        #------------END FLOOR 3------------------------

        #------------FLOOR -1------------------------
        "parking_exit": (-7, -14, "hall", "common", -1),
        "entrance_cafeteria": (-14, -14, "hall", "common", -1),
        "middle_cafeteria": (-20, -14, "hall", "common", -1),
        #------------END FLOOR -1------------------------



        #========QUALIFIED========#
        #------------FLOOR 1------------------------
        "q1_0003": (15, 20, "classroom", "qualified", 0),
        "aula_informatica_A": (27, 20, "classroom", "qualified", 0),
        "small_room": (35, 20, "classroom", "qualified", 0),
        "aula_informatica_B": (44, 20, "classroom", "qualified", 0),

        "q2_0003": (15, 42, "classroom", "qualified", 0),
        "q2_0007": (24, 42, "classroom", "qualified", 0),
        "q2_0009": (30, 42, "classroom", "qualified", 0),
        "q2_0011": (35, 42, "classroom", "qualified", 0),
        "q2_0013": (42, 42, "classroom", "qualified", 0),
        "q2_0016": (44, 42, "classroom", "qualified", 0),

        "q3_0003": (15, 64, "classroom", "qualified", 0),
        "q3_0007": (27, 64, "classroom", "qualified", 0),
        "q3_0011": (42, 64, "classroom", "qualified", 0),

        "q4_0003": (15, 87, "classroom", "qualified", 0),
        "q4_0007": (27, 87, "classroom", "qualified", 0),
        "q4_0011": (42, 87, "classroom", "qualified", 0),

        "hall_end_tables": (4, 87, "tables", "qualified", 0),

        "q5_0003": (72, 27, "classroom", "qualified", 0),
        "q5_0004": (82, 20, "classroom", "qualified", 0),
        "q6_0005": (78, 56, "classroom", "qualified", 0),
        #------------END FLOOR 1------------------------

        #------------FLOOR 2------------------------
        "q1_1003": (14, 18, "classroom", "qualified", 1),
        "q1_1007": (25, 18, "classroom", "qualified", 1),
        "q1_1011": (42, 18, "classroom", "qualified", 1),

        "q2_1003": (12, 40, "classroom", "qualified", 1),
        "q2_1005": (21, 40, "classroom", "qualified", 1),
        "q2_1009": (32, 40, "classroom", "qualified", 1),
        "q2_1013": (43, 40, "classroom", "qualified", 1),

        "q3_1003": (14, 63, "classroom", "qualified", 1),
        "q3_1007": (28, 63, "classroom", "qualified", 1),
        "q3_1011": (42, 63, "classroom", "qualified", 1),
        
        "q4_1003": (12, 86, "classroom", "qualified", 1),
        "q4_1005": (21, 86, "classroom", "qualified", 1),
        "q4_1009": (32, 86, "classroom", "qualified", 1),
        "q4_1013": (43, 86, "classroom", "qualified", 1),

        "q5_1005": (72, 25, "classroom", "qualified", 1),
        "q5_1009": (84, 25, "classroom", "qualified", 1),
        "q5_1010": (91, 25, "classroom", "qualified", 1),
        "q5_1011": (101, 25, "classroom", "qualified", 1),

        "q6_1006": (78, 56, "classroom", "qualified", 1),
        "q6_1011": (91, 56, "classroom", "qualified", 1),
        "q6_1012": (100, 56, "classroom", "qualified", 1),
        #------------END FLOOR2------------------------

        #------------FLOOR 3------------------------
        "q5_2003": (76, 24, "classroom", "qualified", 2),
        "q5_2006": (85, 24, "classroom", "qualified", 2),
        "q5_2007": (91, 24, "classroom", "qualified", 2),
        "q5_2008": (97, 24, "classroom", "qualified", 2),
        "q5_2009": (103, 24, "classroom", "qualified", 2),

        "q6_2004": (72, 54, "classroom", "qualified", 2),
        "q6_2005": (82, 54, "classroom", "qualified", 2),
        "q6_2007": (90, 54, "classroom", "qualified", 2),
        "q6_2008": (97, 54, "classroom", "qualified", 2),
        "q6_2009": (103, 54, "classroom", "qualified", 2),
        #------------END FLOOR 3------------------------

        #------------FLOOR -1------------------------
        "terrace": (-11, -25, "tables", "qualified", -1),
        "bar": (-21, -25, "tables", "qualified", -1),
        #------------END FLOOR -1------------------------

        #========TRANSITIONS=======#
        "stairs_qC": (0, 0, "stairs", "transition", 0.5),
        "stairs_cafeteria": (0, -15, "stairs", "transition", -0.5),
        "stairs_end_q1": (52, 18, "stairs", "transition", 0.5),
        "stairs_q2": (-2, 32, "stairs", "transition", 0.5),

        "stairs_end_q2": (52, 40, "stairs", "transition", 0.5),
        "stairs_q3": (-2, 55, "stairs", "transition", 0.5),

        "stairs_end_q3": (52, 64, "stairs", "transition", 0.5),
        "stairs_q4": (-2, 77, "stairs", "transition", 0.5),

        "stairs_end_q4": (52, 85, "stairs", "transition", 0.5),

        "stairs_q5": (63, 25, "stairs", "transition", 0.5),
        "stairs_q6": (63, 55 , "stairs", "transition", 0.5),

        "stairs_q5_floor1": (63, 25, "stairs", "transition", 1.5), #Stairs for the transition from floor 1 to 2
        "stairs_q6_floor1": (63, 55 , "stairs", "transition", 1.5),
        "stairs_end_q5_floor1": (108, 25, "stairs", "transition", 1.5),
        "stairs_end_q6_floor1": (108, 55 , "stairs", "transition", 1.5),
    }


    for name, (x, y, e, t, h) in nodes.items():
        G_indoor.add_node(name, x=x, y=y, entity=e, type=t, height=h,
                           node_type="indoor", faculty="engineering", floor=0)
        indoor_engineering_nodes.append(name)
        if t == "qualified" or t == "hybrid":
            qualified_nodes.append(name)
        if t == "transition":
            transition_nodes.append(name)

    ################################################
    #----2. CONNECT EDGES (distances in meters)----#
    ################################################

    def connect(a, b):
        x1, y1 = G_indoor.nodes[a]['x'], G_indoor.nodes[a]['y']
        x2, y2 = G_indoor.nodes[b]['x'], G_indoor.nodes[b]['y']
        #We uuse euclidean distance to calculate the distance
        dist = ((x1 - x2)**2 + (y1 - y2)**2) ** 0.5
        G_indoor.add_edge(a, b, length=dist)
        G_indoor.add_edge(b, a, length=dist)

    # Connect the nodes
    #------------FLOOR 1------------------------
    connect("door_main", "reception1")
    connect("door_main", "reception_tables")
    connect("door_main", "stairs_qC")
    connect("door_main", "main_hall_start")
    connect("door_main", "main_hall_seminars")

    connect("reception1", "reception_sofas")
    connect("reception1", "stairs_qC")
    connect("reception1", "main_hall_start")
    connect("reception1", "main_hall_seminars")
    connect("reception1", "stairs_cafeteria")

    connect("reception_tables", "open_labs")

    connect("main_hall_start", "main_hall_seminars")
    connect("main_hall_start", "stairs_qC")
    connect("main_hall_start", "main_hall_q1_tables")

    connect("main_hall_q1_tables", "door_q1_0003")

    connect("door_q1_0003", "q1_0003")
    connect("door_q1_0003", "door_aula_informatica_A")
    
    connect("door_aula_informatica_A", "aula_informatica_A")
    connect("door_aula_informatica_A", "door_small_room")

    connect("door_small_room", "small_room")
    connect("door_small_room", "door_aula_informatica_B")

    connect("door_aula_informatica_B", "aula_informatica_B")
    connect("door_aula_informatica_B", "end_q1")

    connect("end_q1", "stairs_end_q1")

    connect("main_hall_tables1", "main_hall_q2_tables")

    connect("main_hall_q2_tables", "door_q2_0003")
    connect("main_hall_q2_tables", "main_hall_tables2")
    connect("main_hall_q2_tables", "stairs_q2")

    connect("door_q2_0003", "q2_0003")
    connect("door_q2_0003", "door_q2_0007")
    
    connect("door_q2_0007", "q2_0007")
    connect("door_q2_0007", "door_q2_0009")

    connect("door_q2_0009", "q2_0009")
    connect("door_q2_0009", "door_q2_0011")

    connect("door_q2_0011", "q2_0011")
    connect("door_q2_0011", "door_q2_0013")

    connect("door_q2_0013", "q2_0013")
    connect("door_q2_0013", "door_q2_0016")

    connect("door_q2_0016", "q2_0016")
    connect("door_q2_0016", "end_q2")

    connect("end_q2", "stairs_end_q2")

    connect("main_hall_tables2", "main_hall_q3_tables")

    connect("main_hall_q3_tables", "stairs_q3")
    connect("main_hall_q3_tables", "main_hall_tables3")
    connect("main_hall_q3_tables", "door_q3_0003")

    connect("door_q3_0003", "q3_0003")
    connect("door_q3_0003", "door_q3_0007")

    connect("door_q3_0007", "q3_0007")
    connect("door_q3_0007", "door_q3_0011")

    connect("door_q3_0011", "q3_0011")
    connect("door_q3_0011", "end_q3")

    connect("end_q3", "stairs_end_q3")
    
    connect("main_hall_tables3", "main_hall_q4_tables")

    connect("main_hall_q4_tables", "stairs_q4")
    connect("main_hall_q4_tables", "hall_end_tables")
    connect("main_hall_q4_tables", "door_q4_0003")

    connect("door_q4_0003", "q4_0003")
    connect("door_q4_0003", "door_q4_0007")

    connect("door_q4_0007", "q4_0007")
    connect("door_q4_0007", "door_q4_0011")

    connect("door_q4_0011", "q4_0011")
    connect("door_q4_0011", "end_q4")

    connect("end_q4", "stairs_end_q4")

    
    connect("stairs_q5", "entrance_q5")
    connect("entrance_q5", "hall_q5")
    connect("hall_q5", "q5_0003")
    connect("hall_q5", "q5_0004")


    connect("stairs_q6", "entrance_q6")
    connect("entrance_q6", "hall_q6")
    connect("hall_q6", "q6_0005")
    #------------END FLOOR 1------------------------
    #------------FLOOR 2------------------------
    connect("stairs_qC", "upper_hall_q1")
    connect("upper_hall_q1", "door_q1_1003")
    connect("upper_hall_q1", "upper_hall_q2")

    connect("door_q1_1003", "q1_1003")
    connect("door_q1_1003", "door_q1_1007")
    
    connect("door_q1_1007", "q1_1007")
    connect("door_q1_1007", "door_q1_1011")

    connect("door_q1_1011", "q1_1011")
    connect("door_q1_1011", "end_upper_q1")
    
    connect("end_upper_q1", "stairs_end_q1")
    connect("end_upper_q1", "glass_q1")


    connect("stairs_q2", "upper_hall_q2")
    connect("upper_hall_q2", "door_q2_1003")
    connect("upper_hall_q2", "upper_hall_q3")

    connect("door_q2_1003", "q2_1003")
    connect("door_q2_1003", "door_q2_1005")
    
    connect("door_q2_1005", "q2_1005")
    connect("door_q2_1005", "door_q2_1009")

    connect("door_q2_1009", "q2_1009")
    connect("door_q2_1009", "door_q2_1013")

    connect("door_q2_1013", "q2_1013")
    connect("door_q2_1013", "end_upper_q2")
    
    connect("end_upper_q2", "stairs_end_q2")
    connect("end_upper_q2", "glass_q2")


    connect("stairs_q3", "upper_hall_q3")
    connect("upper_hall_q3", "door_q3_1003")
    connect("upper_hall_q3", "upper_hall_q4")

    connect("door_q3_1003", "q3_1003")
    connect("door_q3_1003", "door_q3_1007")
    
    connect("door_q3_1007", "q3_1007")
    connect("door_q3_1007", "door_q3_1011")

    connect("door_q3_1011", "q3_1011")
    connect("door_q3_1011", "end_upper_q3")
    
    connect("end_upper_q3", "stairs_end_q3")
    connect("end_upper_q3", "glass_q3")


    connect("stairs_q4", "upper_hall_q4")
    connect("upper_hall_q4", "door_q4_1003")

    connect("door_q4_1003", "q4_1003")
    connect("door_q4_1003", "door_q4_1005")
    
    connect("door_q4_1005", "q4_1005")
    connect("door_q4_1005", "door_q4_1009")

    connect("door_q4_1009", "q4_1009")
    connect("door_q4_1009", "door_q4_1013")

    connect("door_q4_1013", "q4_1013")
    connect("door_q4_1013", "end_upper_q4")
    
    connect("end_upper_q4", "stairs_end_q4")
    connect("end_upper_q4", "glass_q4")


    connect("glass_q5", "glass_q1")
    connect("glass_q5", "glass_q2")
    connect("glass_q5", "entrance_upper_q5")
    connect("entrance_upper_q5", "stairs_q5_floor1")
    connect("entrance_upper_q5", "door_q5_1005")
    connect("door_q5_1005", "q5_1005")
    connect("door_q5_1005", "door_q5_1009")
    connect("door_q5_1009", "q5_1009")
    connect("door_q5_1009", "door_q5_1010")
    connect("door_q5_1010", "q5_1010")
    connect("door_q5_1010", "door_q5_1011")
    connect("door_q5_1011", "q5_1011")
    connect("door_q5_1011", "end_upper_q5")
    connect("end_upper_q5", "stairs_end_q5_floor1")

    connect("glass_q6", "glass_q2")
    connect("glass_q6", "glass_q3")
    connect("glass_q6", "entrance_upper_q6")
    connect("entrance_upper_q6", "stairs_q6_floor1")
    connect("entrance_upper_q6", "door_q6_1006")
    connect("door_q6_1006", "q6_1006")
    connect("door_q6_1006", "door_q6_1011")
    connect("door_q6_1011", "q6_1011")
    connect("door_q6_1011", "door_q6_1012")
    connect("door_q6_1012", "q6_1012")
    connect("door_q6_1012", "end_upper_q6")
    connect("end_upper_q6", "stairs_end_q6_floor1")
    #------------END FLOOR 2------------------------

    #------------FLOOR 3------------------------
    connect("entrance_upper2_q5", "stairs_q5_floor1")
    connect("entrance_upper2_q5", "door_q5_2003")
    connect("door_q5_2003", "q5_2003")
    connect("door_q5_2003", "door_q5_2006")

    connect("door_q5_2006", "q5_2006")
    connect("door_q5_2006", "door_q5_2007")

    connect("door_q5_2007", "q5_2007")
    connect("door_q5_2007", "door_q5_2008")

    connect("door_q5_2008", "q5_2008")
    connect("door_q5_2008", "door_q5_2009")

    connect("door_q5_2009", "q5_2009")
    connect("door_q5_2009", "end_upper2_q5")

    connect("end_upper2_q5", "stairs_end_q5_floor1")


    connect("entrance_upper2_q6", "stairs_q6_floor1")
    connect("entrance_upper2_q6", "door_q6_2004")
    connect("door_q6_2004", "q6_2004")
    connect("door_q6_2004", "door_q6_2005")

    connect("door_q6_2005", "q6_2005")
    connect("door_q6_2005", "door_q6_2007")

    connect("door_q6_2007", "q6_2007")
    connect("door_q6_2007", "door_q6_2008")

    connect("door_q6_2008", "q6_2008")
    connect("door_q6_2008", "door_q6_2009")

    connect("door_q6_2009", "q6_2009")
    connect("door_q6_2009", "end_upper2_q6")

    connect("end_upper2_q6", "stairs_end_q6_floor1")
    #------------END FLOOR 3------------------------

    #------------FLOOR -1------------------------
    connect("parking_exit", "stairs_cafeteria")
    connect("parking_exit", "entrance_cafeteria")
    connect("entrance_cafeteria", "middle_cafeteria")
    connect("entrance_cafeteria", "terrace")
    connect("middle_cafeteria", "bar")


    #############################
    #----3. SHIFT TO LAT/LON----#
    #############################

    local_points = [
        (-6, 1),
        
        #(108, 50),
        #(64, 20),
        #(4, 91),
        #(55, 20),
        #(0, 64),
        
        (44,86), #AP-ETSE60
        (42, 40), #AP-ETSE07
        (91,25), #AP-ETSE42
        (72, 27), #AP-ETSE46
        (100, 56), #AP-ETSE50
        (-46, -1), #OPEN LABS
        (-21, -21) #BAR AP-ETSE26
    ]

    geo_points = [
        (41.500182, 2.111848),
        
        #(41.499878296829856, 2.1132825847038106),
        #(41.499666776465425, 2.113050009334967),
        #(41.50075608776314, 2.1126228132312352),
        #(41.49996975674136,2.1125569986483717),
        #(41.50057996203391,2.112351431141315),
        
        (41.500495643640591, 2.112933344724248),
        (41.50025943984302, 2.112471942467615),
        (41.499804287672276, 2.112899788514895),
        (41.499919568050643, 2.112723998794907),
        (41.50001759218641, 2.113119988200082),
        (41.50045258826985, 2.1113923944001334),
        (41.500152951551996, 2.111544523664478)
    ]

    ############################################
    #----3. SHIFT TO LAT/LON (FIXED VERSION)----#
    ############################################

    import numpy as np

    # ---- Reference origin (first geo point) ----
    lat0, lon0 = geo_points[0]

    R = 111000  # meters per degree

    # ---- Convert lat/lon → local metric (meters) ----
    def latlon_to_xy(lat, lon):
        x = (lon - lon0) * np.cos(np.radians(lat0)) * R
        y = (lat - lat0) * R
        return x, y

    geo_points_xy = [latlon_to_xy(lat, lon) for lat, lon in geo_points]


    # ---- Compute similarity transform in METRIC space ----
    def compute_similarity(local_pts, geo_pts_xy):
        A = []
        B = []

        for (x, y), (X, Y) in zip(local_pts, geo_pts_xy):
            A.append([x, -y, 1, 0])
            A.append([y,  x, 0, 1])

            B.append(X)
            B.append(Y)

        A = np.array(A)
        B = np.array(B)

        params, *_ = np.linalg.lstsq(A, B, rcond=None)

        a, b, tx, ty = params
        return a, b, tx, ty


    def apply_similarity(x, y, params):
        a, b, tx, ty = params

        X = a*x - b*y + tx
        Y = b*x + a*y + ty

        return X, Y


    # ---- Convert back meters → lat/lon ----
    def xy_to_latlon(X, Y):
        lon = X / (np.cos(np.radians(lat0)) * R) + lon0
        lat = Y / R + lat0
        return lon, lat


    # ---- Compute transform parameters ----
    params = compute_similarity(local_points, geo_points_xy)


    # ---- Apply transformation to all nodes ----
    for n, data in G_indoor.nodes(data=True):
        x_local = data['x']
        y_local = data['y']

        # Apply similarity
        X, Y = apply_similarity(x_local, y_local, params)

        # ---- MANUAL OFFSET (meters) ----
        OFFSET_X = 0.0   # right (east)
        OFFSET_Y = 0.0   # up (north)

        X += OFFSET_X
        Y += OFFSET_Y

        # Convert back to lat/lon
        lon, lat = xy_to_latlon(X, Y)

        data['x'] = lon
        data['y'] = lat
        

    ##################################
    #----4. LINK TO OUTDOOR GRAPH----#
    ##################################

    # OSMnx nodes don't have the node_type, that's an attribute we added manually
    outdoors_nodes = [n for n, d in G.nodes(data=True) if d.get("node_type") is None]
    
    nearest_node = ox.distance.nearest_nodes(G.subgraph(outdoors_nodes), door_lon, door_lat)

    G = nx.compose(G, G_indoor)

    G.add_edge(nearest_node, "door_main", length=1)
    G.add_edge("door_main", nearest_node, length=1)
    

    ##################################
    #----5. RETURN TRACKING LISTS----#
    ##################################

    indoor_engineering_nodes = list(G_indoor.nodes())

    return G, G_indoor, indoor_engineering_nodes, transition_nodes, qualified_nodes


#======Visualization======#

def show_graph(G, source=[], targets=[], paths=[], ap_nodes=[]):
    """
    DEPRECATED!!!!!
    Too many things to handle for matplotlib, for more complex debugging use the folium map
    """
    # node positions
    pos = {n: (data['x'], data['y']) for n, data in G.nodes(data=True)}

    plt.figure(figsize=(14,14))

    # ---Base graph---
    nx.draw_networkx_edges(
        G,
        pos,
        edge_color="lightblue",
        width=0.6,
        alpha=0.4
    )

    nx.draw_networkx_nodes(
        G,
        pos,
        node_size=6,
        node_color="red",
        alpha=0.7
    )

    # ---Draw paths---
    for path in paths:

        if len(path) < 2:
            continue

        path_edges = list(zip(path[:-1], path[1:]))

        nx.draw_networkx_edges(
            G,
            pos,
            edgelist=path_edges,
            edge_color="limegreen",
            width=4,
            alpha=0.9
        )

        nx.draw_networkx_nodes(
            G,
            pos,
            nodelist=path,
            node_size=35,
            node_color="limegreen",
            edgecolors="black",
            linewidths=0.5
        )

    # ---Highlight special nodes---
    if targets:

        valid_nodes = [n for n in targets if n in G]

        nx.draw_networkx_nodes(
            G,
            pos,
            nodelist=valid_nodes,
            node_color="gold",
            node_size=120,
            edgecolors="black",
            linewidths=1.5
        )
    nx.draw_networkx_nodes(
            G,
            pos,
            nodelist=source,
            node_color="orange",
            node_size=130,
            edgecolors="black",
            linewidths=1.5
        )

    # ---Draw AP nodes---
    if ap_nodes:
        valid_ap_nodes = [n for n in ap_nodes if n in G]

        nx.draw_networkx_nodes(
            G,
            pos,
            nodelist=valid_ap_nodes,
            node_color="blue",
            node_size=20,
            edgecolors="black",
            linewidths=0.5
        )

    plt.xlabel("Longitude")
    plt.ylabel("Latitude")
    plt.title("UAB Campus Graph")

    plt.tight_layout()
    plt.show()

def show_graph_folium(G, ap_nodes=[], paths=[], source=None, targets=[]):
    # Center map
    xs = [data['x'] for _, data in G.nodes(data=True)]
    ys = [data['y'] for _, data in G.nodes(data=True)]

    center_lat = sum(ys) / len(ys)
    center_lon = sum(xs) / len(xs)

    m = folium.Map(location=[center_lat, center_lon], zoom_start=16)

    # --- Draw edges (roads) ---
    for u, v, data in G.edges(data=True):
        x1, y1 = G.nodes[u]['x'], G.nodes[u]['y']
        x2, y2 = G.nodes[v]['x'], G.nodes[v]['y']

        folium.PolyLine(
            locations=[(y1, x1), (y2, x2)],
            color="lightblue",
            weight=2,
            opacity=0.5
        ).add_to(m)

    # --- Draw AP nodes ---
    for n in ap_nodes:
        if n in G:
            x, y = G.nodes[n]['x'], G.nodes[n]['y']

            folium.CircleMarker(
                location=(y, x),
                radius=4,
                color="blue",
                fill=True,
                fill_opacity=0.8,
                popup=f"AP: {n}"
            ).add_to(m)

    # --- Draw paths ---
    for path in paths:
        coords = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in path]

        folium.PolyLine(
            locations=coords,
            color="green",
            weight=5,
            opacity=0.9
        ).add_to(m)

    # --- Source ---
    if source:
        for n in source:
            if n in G:
                x, y = G.nodes[n]['x'], G.nodes[n]['y']
                folium.Marker(
                    location=(y, x),
                    icon=folium.Icon(color="orange"),
                    popup="Source"
                ).add_to(m)

    # --- Targets ---
    for n in targets:
        if n in G:
            x, y = G.nodes[n]['x'], G.nodes[n]['y']
            folium.Marker(
                location=(y, x),
                icon=folium.Icon(color="red"),
                popup="Target"
            ).add_to(m)

    return m









###################################
#---------------MAIN--------------#
###################################

if __name__ == "__main__":
    ########################################
    #---------GRAPH INITIALIZATION---------#
    ########################################
    G = nx.connected_watts_strogatz_graph(n=100, k=6, p=0.33, tries=1000, seed=RANDOM_SEED)

    # Add weights to the graph
    for (u, v) in G.edges():
        G.edges[u,v]['weight'] = random.randint(0,10)
    # To access the weight of an edge do >> G.edges[u,v]['weight']

    list_nodes = list(G.nodes())
    list_edges = list(G.edges())

    ########################################
    #--------------USER INPUT--------------#
    ########################################

    location : int = int(input("Enter the current location: "))

    destinations : list = []
    for _ in range(1):
        destination = int(input("Enter the wanted destination: "))
        acceptable_range = int(input("Enter the acceptable range from the destination: "))
        destinations.append((destination, acceptable_range))

    neighbours = find_qualified_in_range(G=G, original_target=destinations[0][0], 
                                        acceptable_range=destinations[0][1])
    print(neighbours)

    paths_to_neigh = find_paths_to_candidates(G, source=location,
                                            target_neighbours=neighbours)
    for k, v in paths_to_neigh.items():
        print("To reach node", k, ":", v[1], ". The cost is", v[0], sep="  ")

    add_aps_to_graph(G=G)




