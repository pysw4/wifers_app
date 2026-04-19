import numpy as np
import matplotlib.pyplot as plt
import networkx as nx
import random

RANDOM_SEED = 0
random.seed(a=RANDOM_SEED)

########################################
#---------------FUNCTIONS--------------#
########################################
def draw_graph(G):
    pos = nx.spring_layout(G)
    nx.draw_networkx(G, pos=pos, with_labels=True)
    plt.show()

def find_neighbours_in_range(G, original_target, acceptable_range, verbose=0):
    """
    Recieves a graph, a target, and a "grace range" and calculates all the possible
    destinations within the "grace range" of the target.

    Calculates the shortest path between the target and all the nodes of the graph and 
    keeps the ones that are within the range.
    """
    distances, paths = nx.single_source_dijkstra(G, original_target, weight="length")
    neigbours : list = []
    if verbose:
        print("Original target:", original_target)
    for n in paths:
        if distances[n] <= acceptable_range:
            neigbours.append(n)
            if verbose:
                print(">============================<")
                print("-->Destination", n)
                print("-->Path:", paths[n])
                print("-->Costs", distances[n])
            
    return neigbours

def find_paths_to_neighbours(G, source:int, target_neighbours:list, weight_attr="length"):
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

    neighbours = find_neighbours_in_range(G=G, original_target=destinations[0][0], 
                                        acceptable_range=destinations[0][1])
    print(neighbours)

    paths_to_neigh = find_paths_to_neighbours(G, source=location,
                                            target_neighbours=neighbours)
    for k, v in paths_to_neigh.items():
        print("To reach node", k, ":", v[1], ". The cost is", v[0], sep="  ")




