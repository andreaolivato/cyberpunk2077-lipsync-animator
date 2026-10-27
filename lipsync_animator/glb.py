"""Read and write the .anims.glb files WolvenKit exports from a lipsync set.

An exported set is a glTF binary file. Each animation in it is one spoken
line, named f_<stringId in hex>. The face is in each animation's extras:
`trackKeys` (a list of {trackIndex, time, value}) and `constTrackKeys` (one
key per track that never moves). The 344 head bones are ordinary glTF
channels."""
import copy
import json
import struct

import numpy as np

FPS = 30
GLB_MAGIC, JSON_CHUNK, BIN_CHUNK = 0x46546C67, 0x4E4F534A, 0x004E4942
COMPONENTS = {'SCALAR': 1, 'VEC3': 3, 'VEC4': 4}
# A glTF node's transform when it states none.
REST = {'translation': [0.0, 0.0, 0.0], 'rotation': [0.0, 0.0, 0.0, 1.0], 'scale': [1.0, 1.0, 1.0]}


def read(path):
    """(gltf dict, binary chunk as a bytearray)."""
    d = open(path, 'rb').read()
    jlen = struct.unpack_from('<I', d, 12)[0]
    g = json.loads(d[20:20 + jlen])
    blen = struct.unpack_from('<I', d, 20 + jlen)[0]
    return g, bytearray(d[28 + jlen:28 + jlen + blen])


def write(path, g, binary):
    binary = bytes(binary) + b'\0' * (-len(binary) % 4)
    g['buffers'][0]['byteLength'] = len(binary)
    js = json.dumps(g, separators=(',', ':')).encode()
    js += b' ' * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    out = struct.pack('<III', GLB_MAGIC, 2, total)
    out += struct.pack('<II', len(js), JSON_CHUNK) + js
    out += struct.pack('<II', len(binary), BIN_CHUNK) + binary
    open(path, 'wb').write(out)


def animations(path):
    """{name: animation} without the binary data, for reading the face."""
    return {a['name']: a for a in read(path)[0]['animations']}


def read_accessor(g, binary, i):
    ac = g['accessors'][i]
    bv = g['bufferViews'][ac['bufferView']]
    n = COMPONENTS[ac['type']]
    off = bv.get('byteOffset', 0) + ac.get('byteOffset', 0)
    return np.frombuffer(bytes(binary[off:off + 4 * n * ac['count']]), '<f4').reshape(-1, n)


def add_accessor(g, binary, values, kind):
    """Append float rows as a new accessor and return its index."""
    values = np.asarray(values, '<f4').reshape(-1, COMPONENTS[kind])
    while len(binary) % 4:
        binary.append(0)
    g['bufferViews'].append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': values.nbytes})
    binary.extend(values.tobytes())
    ac = {'bufferView': len(g['bufferViews']) - 1, 'componentType': 5126,
          'count': len(values), 'type': kind}
    if kind == 'SCALAR':
        ac['min'], ac['max'] = [float(values.min())], [float(values.max())]
    g['accessors'].append(ac)
    return len(g['accessors']) - 1


def face_keys(anim, n_tracks=414):
    """Every face track as (times, values); a constant is one key at 0."""
    keys = [[] for _ in range(n_tracks)]
    for k in anim['extras']['trackKeys']:
        keys[k['trackIndex']].append((k['time'], k['value']))
    for k in anim['extras']['constTrackKeys']:
        if not keys[k['trackIndex']]:
            keys[k['trackIndex']].append((0.0, k['value']))
    out = []
    for ks in keys:
        ks.sort()
        out.append((np.array([t for t, _ in ks]), np.array([v for _, v in ks]))
                   if ks else (np.array([0.0]), np.array([0.0])))
    return out


def sample(curves, t):
    """All tracks at times t, filled in with straight lines between keys."""
    return np.stack([np.interp(t, ts, vs) for ts, vs in curves], axis=1)


def new_animation(g, binary, template, name, face, n_frames):
    """A copy of template renamed, with the given face (one key per frame for
    a track that moves, a constant otherwise) and every head bone held at
    the rig's rest pose for the whole line. A lipsync animation is added on
    top of what the character already does, so a bone at rest adds nothing:
    the character keeps its own neck and head. (Holding a borrowed frame
    instead would add that frame's head turn to everyone.) The bones still
    span the whole line, because WolvenKit's importer drops face keys that
    come after the bones' last key."""
    anim = copy.deepcopy(template)
    anim['name'] = name
    times = add_accessor(g, binary, [0.0, (n_frames - 1) / FPS], 'SCALAR')
    samplers = []
    for ch in anim['channels']:
        s = template['samplers'][ch['sampler']]
        node = g['nodes'][ch['target']['node']]
        path = ch['target']['path']
        first = np.array([node.get(path, REST[path])], dtype='<f4')
        kind = g['accessors'][s['output']]['type']
        held = add_accessor(g, binary, np.repeat(first, 2, axis=0), kind)
        samplers.append({'input': times, 'output': held,
                         'interpolation': s.get('interpolation', 'LINEAR')})
        ch['sampler'] = len(samplers) - 1
    anim['samplers'] = samplers
    keys, const = [], []
    for ti in sorted(face):
        v = face[ti]
        if np.ptp(v) < 1e-6:
            const.append({'trackIndex': int(ti), 'time': 0.0, 'value': float(round(v[0], 6))})
        else:
            keys += [{'trackIndex': int(ti), 'time': round(f / FPS, 6),
                      'value': float(round(v[f], 6))} for f in range(n_frames)]
    anim['extras']['trackKeys'] = keys
    anim['extras']['constTrackKeys'] = const
    return anim


def copy_animation(g, binary, src_g, src_binary, anim):
    """anim, an animation of another export (src_g, src_binary), copied into
    g unchanged: its keys are copied into binary, and each bone channel
    follows its bone by name, since two rigs may order their bones
    differently. A bone g does not have is left out."""
    out = copy.deepcopy(anim)
    nodes = {n.get('name'): i for i, n in enumerate(g['nodes'])}
    out['samplers'], out['channels'] = [], []
    for ch in anim['channels']:
        bone = src_g['nodes'][ch['target']['node']].get('name')
        if bone not in nodes:
            continue
        s = anim['samplers'][ch['sampler']]
        keys = []
        for i in (s['input'], s['output']):
            if src_g['accessors'][i]['componentType'] != 5126:
                raise ValueError('only float animation keys can be copied')
            keys.append(add_accessor(g, binary, read_accessor(src_g, src_binary, i),
                                     src_g['accessors'][i]['type']))
        out['samplers'].append(dict(s, input=keys[0], output=keys[1]))
        out['channels'].append(dict(ch, sampler=len(out['samplers']) - 1,
                                    target=dict(ch['target'], node=nodes[bone])))
    return out


def put_lines(set_in, set_out, lines, template_name=None):
    """Write new animations into a copy of an exported set.

    lines: [(name, face, n_frames)]. A name already in the set is replaced
    in place (its old animation is the bone template); a new name is added,
    with template_name (or the set's first animation) as the bone template.
    Returns the names in the written set."""
    g, binary = read(set_in)
    if not g.get('animations'):
        raise SystemExit('%s holds no animation to borrow the bones from' % set_in)
    index = {a['name']: i for i, a in enumerate(g['animations'])}
    if template_name and template_name not in index:
        raise SystemExit('%s has no animation named %s; it has %s'
                         % (set_in, template_name, ', '.join(sorted(index))))
    for name, face, n_frames in lines:
        tname = name if name in index else (template_name or g['animations'][0]['name'])
        anim = new_animation(g, binary, g['animations'][index[tname]], name, face, n_frames)
        if name in index:
            g['animations'][index[name]] = anim
        else:
            g['animations'].append(anim)
            index[name] = len(g['animations']) - 1
    write(set_out, g, binary)
    return [a['name'] for a in g['animations']]
