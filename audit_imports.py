import os, re

bare = re.compile(r"""from ['"]three['"]|from ['"]@pixiv""")
found = False
exts = ('.js', '.html')
skip_names = {'three.module.js', 'es-module-shims.js'}

for root, dirs, files in os.walk(r'D:\kiana\static'):
    for fn in files:
        if not any(fn.endswith(e) for e in exts):
            continue
        if fn in skip_names:
            continue
        path = os.path.join(root, fn)
        try:
            with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            for i, line in enumerate(lines, 1):
                if bare.search(line):
                    print(f'  BARE SPECIFIER  {path}:{i}  ->  {line.strip()[:80]}')
                    found = True
        except Exception as e:
            print(f'  SKIP {path}: {e}')

if not found:
    print('All clear - zero bare module specifiers remain in project.')
