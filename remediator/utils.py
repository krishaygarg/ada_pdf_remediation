def merge_bboxes(boxes):
    """
    Consolidates overlapping or intersecting bounding boxes into disjoint regions.
    Uses padding to group nearby elements (e.g., table cells/lines or formula curves).
    """
    if not boxes:
        return []
    
    n = len(boxes)
    parent = list(range(n))
    
    def find(i):
        if parent[i] == i:
            return i
        parent[i] = find(parent[i])
        return parent[i]
    
    def union(i, j):
        root_i = find(i)
        root_j = find(j)
        if root_i != root_j:
            parent[root_i] = root_j
            
    def boxes_overlap(box1, box2):
        x0_1, top_1, x1_1, bottom_1 = box1
        x0_2, top_2, x1_2, bottom_2 = box2
        padding = 2.0  # Points padding to merge adjacent shapes
        return not (
            x1_1 + padding < x0_2 or 
            x0_1 - padding > x1_2 or 
            bottom_1 + padding < top_2 or 
            top_1 - padding > bottom_2
        )

    for i in range(n):
        for j in range(i + 1, n):
            if boxes_overlap(boxes[i], boxes[j]):
                union(i, j)
                
    groups = {}
    for i in range(n):
        root = find(i)
        if root not in groups:
            groups[root] = []
        groups[root].append(boxes[i])
        
    merged = []
    for g_boxes in groups.values():
        x0 = min(b[0] for b in g_boxes)
        top = min(b[1] for b in g_boxes)
        x1 = max(b[2] for b in g_boxes)
        bottom = max(b[3] for b in g_boxes)
        merged.append([x0, top, x1, bottom])
        
    return merged

def multiply_matrices(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return [
        a1 * a2 + b1 * c2,
        a1 * b2 + b1 * d2,
        c1 * a2 + d1 * c2,
        c1 * b2 + d1 * d2,
        e1 * a2 + f1 * c2 + e2,
        e1 * b2 + f1 * d2 + f2
    ]

def transform_point(x, y, m):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)

def get_operator_coords(op_name, operands):
    coords = []
    if op_name in ('m', 'l'):
        if len(operands) >= 2:
            coords.append((float(operands[0]), float(operands[1])))
    elif op_name == 're':
        if len(operands) >= 4:
            x, y, w, h = float(operands[0]), float(operands[1]), float(operands[2]), float(operands[3])
            coords.append((x, y))
            coords.append((x + w, y + h))
    elif op_name == 'c':
        if len(operands) >= 6:
            coords.append((float(operands[0]), float(operands[1])))
            coords.append((float(operands[2]), float(operands[3])))
            coords.append((float(operands[4]), float(operands[5])))
    elif op_name in ('v', 'y'):
        if len(operands) >= 4:
            coords.append((float(operands[0]), float(operands[1])))
            coords.append((float(operands[2]), float(operands[3])))
    return coords
