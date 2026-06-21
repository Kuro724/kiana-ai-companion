"""
patch_js.py  —  Replace all bare 'three' module specifiers with absolute local paths.
Run once: python patch_js.py
"""
import os

STATIC = os.path.join(os.path.dirname(__file__), 'static')

PATCHES = [
    # (file path,  [(old string, new string), ...])
    (
        os.path.join(STATIC, 'js', 'libs', 'three-vrm.module.js'),
        [
            ("from 'three'",  "from '/static/js/libs/three.module.js'"),
            ('from "three"',  'from "/static/js/libs/three.module.js"'),
        ]
    ),
    (
        os.path.join(STATIC, 'js', 'libs', 'GLTFLoader.js'),
        [
            ("from 'three'",  "from '/static/js/libs/three.module.js'"),
            ('from "three"',  'from "/static/js/libs/three.module.js"'),
            ("from '../utils/BufferGeometryUtils.js'",
             "from '/static/js/utils/BufferGeometryUtils.js'"),
            ('from "../utils/BufferGeometryUtils.js"',
             'from "/static/js/utils/BufferGeometryUtils.js"'),
        ]
    ),
    (
        os.path.join(STATIC, 'js', 'utils', 'BufferGeometryUtils.js'),
        [
            ("from 'three'",  "from '/static/js/libs/three.module.js'"),
            ('from "three"',  'from "/static/js/libs/three.module.js"'),
        ]
    ),
]

for filepath, replacements in PATCHES:
    if not os.path.exists(filepath):
        print(f"SKIP (not found): {filepath}")
        continue
    with open(filepath, 'r', encoding='utf-8') as f:
        src = f.read()
    total = 0
    for old, new in replacements:
        count = src.count(old)
        if count:
            src = src.replace(old, new)
            total += count
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(src)
    print(f"  Patched {total:3d} occurrence(s)  ->  {os.path.basename(filepath)}")

print("\nAll bare module specifiers replaced with absolute /static/ paths.")
