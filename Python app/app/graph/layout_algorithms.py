"""
layout_algorithms.py — Static graph layout algorithms.
Returns initial positions (x, y) for nodes.
"""
from __future__ import annotations

import math

def circular_layout(node_ids: list[str], radius: float = 300.0) -> dict[str, tuple[float, float]]:
    n = len(node_ids)
    if n == 0:
        return {}
    if n == 1:
        return {node_ids[0]: (0.0, 0.0)}
        
    positions = {}
    for i, nid in enumerate(node_ids):
        theta = 2.0 * math.pi * i / n
        x = radius * math.cos(theta)
        y = radius * math.sin(theta)
        positions[nid] = (x, y)
    return positions

def radial_layout(node_ids: list[str], edges: list[tuple[str, str, float]], center_node: str, radius_step: float = 150.0) -> dict[str, tuple[float, float]]:
    if not node_ids:
        return {}
        
    # Build adjacency list
    adj = {n: [] for n in node_ids}
    for u, v, _ in edges:
        if u in adj and v in adj:
            adj[u].append(v)
            adj[v].append(u)
            
    # BFS to assign rings
    distances = {n: -1 for n in node_ids}
    if center_node in distances:
        distances[center_node] = 0
        queue = [center_node]
    elif node_ids:
        distances[node_ids[0]] = 0
        queue = [node_ids[0]]
    else:
        return {}
        
    while queue:
        curr = queue.pop(0)
        d = distances[curr]
        for neighbor in adj[curr]:
            if distances[neighbor] == -1:
                distances[neighbor] = d + 1
                queue.append(neighbor)
                
    # Group by distance
    rings = {}
    for nid, d in distances.items():
        if d == -1:
            d = 999  # Disconnected
        rings.setdefault(d, []).append(nid)
        
    positions = {}
    for d, nodes in rings.items():
        if d == 0:
            for nid in nodes:
                positions[nid] = (0.0, 0.0)
            continue
            
        r = d * radius_step
        n = len(nodes)
        for i, nid in enumerate(nodes):
            theta = 2.0 * math.pi * i / n
            x = r * math.cos(theta)
            y = r * math.sin(theta)
            positions[nid] = (x, y)
            
    return positions

def timeline_layout(node_years: dict[str, int], spacing_x: float = 250.0, spacing_y: float = 150.0) -> dict[str, tuple[float, float]]:
    if not node_years:
        return {}
        
    # Group by year
    years_dict = {}
    for nid, year in node_years.items():
        years_dict.setdefault(year, []).append(nid)
        
    # Sort distinct years
    sorted_years = sorted(years_dict.keys())
    
    positions = {}
    max_row_index = len(sorted_years) - 1
    
    for row_index, year in enumerate(sorted_years):
        # Dal basso verso l'alto: l'anno più vecchio (row_index=0) ha la Y maggiore (sta in basso)
        y = (max_row_index - row_index) * spacing_y
        
        nodes = years_dict[year]
        n = len(nodes)
        start_x = -(n - 1) * spacing_x / 2.0
        
        for i, nid in enumerate(nodes):
            x = start_x + i * spacing_x
            positions[nid] = (x, y)
            
    return positions
