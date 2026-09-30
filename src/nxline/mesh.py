"""The tessellation the 3D view draws, written beside the facts.

Runs inside the NX session, in NX's own Python, with the standard library
only: the kernel is alive there and nowhere else, so this is the one moment
the triangles can be had.  Everything else the interface shows comes out of
the store as RDF; a mesh is binary and large and belongs in a file.

The drawing unit is the PartModel face, the same identity the facts use
(``cg:ownsFace``), so a triangle the reader clicks answers with an id the
graph already knows.  Faces the seam normalisation merged are one face here
too: their CAD triangles are concatenated into the surviving id.

Two files per part::

    mesh.bin    positions | normals | indices | edge positions, back to back
    mesh.json   the header: buffer offsets, one record per face, the bounds

How fine to mesh is a display decision, not a kernel fact, so it is made
here and passed into ``KernelServices.tessellate``: chord height and edge
sagitta as a fraction of the part's bounding-box diagonal.  Tight on
purpose - the outline the viewer draws is built from these very vertices, so
a coarse mesh reads as a ragged part rather than a faceted one.
"""

import json
import os
import struct

# Relative to the bounding-box diagonal, so a 10 mm part and a 1 m part come
# out looking equally smooth.  The angular tolerance is in radians.
LINEAR_DEFLECTION_RATIO = 0.0006
EDGE_DEFLECTION_RATIO = 0.0006
ANGULAR_DEFLECTION = 0.16

SCHEMA_VERSION = "cncgaide.nx.mesh.v1"


def _diagonal(bbox):
    dx = float(bbox[3]) - float(bbox[0])
    dy = float(bbox[4]) - float(bbox[1])
    dz = float(bbox[5]) - float(bbox[2])
    return max(1.0e-6, (dx * dx + dy * dy + dz * dz) ** 0.5)


def _ordinal(face_id):
    tail = str(face_id).rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def owner_by_cad_id(model):
    """``{cad face index: PartModel face id}``.

    A face that survived the merge owns its own CAD face; a face that was
    merged away is listed in the survivor's ``merged_from``, and its
    triangles belong to the survivor.
    """
    owners = {}
    for face_id, face in (getattr(model, "faces", {}) or {}).items():
        owners[_ordinal(face_id)] = face_id
        for merged in getattr(face, "merged_from", None) or []:
            owners[_ordinal(merged)] = face_id
    return owners


def _moments(positions, indices):
    """Tessellated area, area-weighted centroid and mean normal of one face.

    The mean normal is what lets the viewer swing the camera to a side the
    face is visible from.  It cancels out to nothing on a closed bore wall,
    which is reported as ``None`` rather than as a direction.
    """
    total = 0.0
    cx = cy = cz = 0.0
    sx = sy = sz = 0.0
    for i in range(0, len(indices), 3):
        a, b, c = indices[i] * 3, indices[i + 1] * 3, indices[i + 2] * 3
        ax, ay, az = positions[a:a + 3]
        bx, by, bz = positions[b:b + 3]
        cx3, cy3, cz3 = positions[c:c + 3]
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx3 - ax, cy3 - ay, cz3 - az
        tx = uy * vz - uz * vy
        ty = uz * vx - ux * vz
        tz = ux * vy - uy * vx
        area = 0.5 * (tx * tx + ty * ty + tz * tz) ** 0.5
        if area <= 0.0:
            continue
        total += area
        cx += area * (ax + bx + cx3) / 3.0
        cy += area * (ay + by + cy3) / 3.0
        cz += area * (az + bz + cz3) / 3.0
        sx += 0.5 * tx
        sy += 0.5 * ty
        sz += 0.5 * tz
    if total <= 0.0:
        return 0.0, None, None
    length = (sx * sx + sy * sy + sz * sz) ** 0.5
    normal = [sx / length, sy / length, sz / length] if length > 1.0e-12 else None
    return total, [cx / total, cy / total, cz / total], normal


def build(kernel, model, nodes=None):
    """Pack the kernel's tessellation into the bytes and the header."""
    bbox = [float(v) for v in kernel.tessellation_bounds()]
    diagonal = _diagonal(bbox)
    linear = diagonal * LINEAR_DEFLECTION_RATIO
    edge = diagonal * EDGE_DEFLECTION_RATIO
    face_meshes = kernel.tessellate(linear, ANGULAR_DEFLECTION, edge)

    by_cad_id = {}
    for face_mesh in face_meshes:
        by_cad_id[int(face_mesh.cad_face_id)] = face_mesh
    owners = owner_by_cad_id(model)

    # One group per PartModel face, in face-id order, plus - should the
    # kernel ever hand back a CAD face no PartModel face claims - a group of
    # its own, so the part is never drawn with a hole in it.
    groups = {}
    order = []
    for face_id in sorted((getattr(model, "faces", {}) or {}), key=_ordinal):
        groups[face_id] = []
        order.append(face_id)
    unmapped = []
    for cad_id in sorted(by_cad_id):
        face_id = owners.get(cad_id)
        if face_id is None:
            face_id = "face_%d" % cad_id
            unmapped.append(cad_id)
            if face_id not in groups:
                groups[face_id] = []
                order.append(face_id)
        groups[face_id].append(cad_id)

    all_positions = []
    all_normals = []
    all_indices = []
    all_edges = []
    records = []
    empty = []

    for face_id in order:
        vertex_offset = len(all_positions) // 3
        index_offset = len(all_indices)
        edge_offset = len(all_edges) // 3
        positions = []
        normals = []
        indices = []
        segments = []
        cad_ids = groups.get(face_id) or []
        for cad_id in cad_ids:
            face_mesh = by_cad_id.get(cad_id)
            if face_mesh is None:
                continue
            base = len(positions) // 3
            positions.extend(float(v) for v in face_mesh.positions)
            normals.extend(float(v) for v in face_mesh.normals)
            indices.extend(int(v) + base for v in face_mesh.indices)
            segments.extend(float(v) for v in face_mesh.edge_segments)
        if not indices:
            empty.append(face_id)
        all_positions.extend(positions)
        all_normals.extend(normals)
        all_indices.extend(indices)
        all_edges.extend(segments)

        area, centroid, normal = _moments(positions, indices)
        records.append({
            "faceId": face_id,
            "cadFaceIds": list(cad_ids),
            "vertexOffset": vertex_offset,
            "vertexCount": len(positions) // 3,
            "indexOffset": index_offset,
            "indexCount": len(indices),
            "edgeVertexOffset": edge_offset,
            "edgeVertexCount": len(segments) // 3,
            "area": area,
            "centroid": centroid,
            "normal": normal,
        })

    position_bytes = struct.pack("<%df" % len(all_positions), *all_positions)
    normal_bytes = struct.pack("<%df" % len(all_normals), *all_normals)
    index_bytes = struct.pack("<%dI" % len(all_indices), *all_indices)
    edge_bytes = struct.pack("<%df" % len(all_edges), *all_edges)
    payload = position_bytes + normal_bytes + index_bytes + edge_bytes

    claimed = set()
    for node in nodes or []:
        for face_id in getattr(node, "partmodelFaceIds", None) or []:
            claimed.add(face_id)

    header = {
        "schemaVersion": SCHEMA_VERSION,
        "faceCount": len(records),
        "claimedFaceCount": len(claimed),
        "boundingBox": {"min": bbox[0:3], "max": bbox[3:6]},
        "tessellation": {
            "linearDeflection": linear,
            "angularDeflection": ANGULAR_DEFLECTION,
            "edgeDeflection": edge,
        },
        "buffers": {
            "positions": {
                "byteOffset": 0,
                "count": len(all_positions) // 3, "type": "Float32", "itemSize": 3,
            },
            "normals": {
                "byteOffset": len(position_bytes),
                "count": len(all_normals) // 3, "type": "Float32", "itemSize": 3,
            },
            "indices": {
                "byteOffset": len(position_bytes) + len(normal_bytes),
                "count": len(all_indices), "type": "Uint32", "itemSize": 1,
            },
            "edgePositions": {
                "byteOffset": len(position_bytes) + len(normal_bytes) + len(index_bytes),
                "count": len(all_edges) // 3, "type": "Float32", "itemSize": 3,
            },
        },
        "faces": records,
        "emptyFaceIds": empty,
        "unmappedCadFaceIds": unmapped,
    }
    return header, payload


def write_mesh(mesh_dir, part_id, kernel, model, nodes):
    """Write ``mesh.bin`` and ``mesh.json`` for one part; answer a summary."""
    header, payload = build(kernel, model, nodes)
    os.makedirs(mesh_dir, exist_ok=True)
    with open(os.path.join(mesh_dir, "mesh.bin"), "wb") as handle:
        handle.write(payload)
    with open(os.path.join(mesh_dir, "mesh.json"), "w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(header))
    triangles = header["buffers"]["indices"]["count"] // 3
    return {
        "partId": part_id,
        "bytes": len(payload),
        "faceCount": header["faceCount"],
        "claimedFaceCount": header["claimedFaceCount"],
        "triangleCount": triangles,
        "emptyFaceCount": len(header["emptyFaceIds"]),
    }
