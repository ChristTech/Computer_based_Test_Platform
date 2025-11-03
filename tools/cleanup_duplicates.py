import ast
import argparse
import shutil
from pathlib import Path

def find_funcs(path):
    src = path.read_text(encoding='utf-8')
    tree = ast.parse(src)
    funcs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # ensure top-level (parent is Module)
            # we approximate top-level by checking node.col_offset == 0
            funcs.append({
                'name': node.name,
                'lineno': node.lineno,
                'end_lineno': getattr(node, 'end_lineno', None)
            })
    # sort by lineno
    funcs.sort(key=lambda x: x['lineno'])
    return funcs, src.splitlines(keepends=True)

def plan_removals(funcs):
    byname = {}
    removals = []
    for f in funcs:
        if f['name'] not in byname:
            byname[f['name']] = f
        else:
            removals.append(f)
    return removals, byname

def apply_removals(path, src_lines, removals, backup=True):
    if not removals:
        print("No duplicates to remove.")
        return
    to_remove_ranges = []
    for r in removals:
        if r['end_lineno'] is None:
            raise RuntimeError(f"Function {r['name']} at {r['lineno']} missing end_lineno; cannot safely remove.")
        # convert to 0-based indices; end_lineno is inclusive, slice end is exclusive
        start = r['lineno'] - 1
        end = r['end_lineno']
        to_remove_ranges.append((start, end))
    # merge ranges descending so deletions don't shift earlier indices
    to_remove_ranges.sort(reverse=True)
    out_lines = list(src_lines)
    for start, end in to_remove_ranges:
        print(f"Removing lines {start+1}-{end} (inclusive)")
        del out_lines[start:end]
    # backup
    if backup:
        bak = path.with_suffix(path.suffix + '.bak')
        shutil.copy2(path, bak)
        print(f"Original backed up to: {bak}")
    path.write_text(''.join(out_lines), encoding='utf-8')
    print(f"Wrote cleaned file: {path}")

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--file', '-f', required=True, help='Path to app.py')
    p.add_argument('--apply', action='store_true', help='Apply removals (writes file). Dry-run otherwise.')
    args = p.parse_args()

    path = Path(args.file)
    if not path.exists():
        print("File not found:", path)
        return

    funcs, src_lines = find_funcs(path)
    removals, kept = plan_removals(funcs)
    if not removals:
        print("No duplicate top-level function definitions found.")
        return

    print("Duplicate functions detected (keeps first occurrence):")
    # group by name for full printout
    names = {}
    for f in funcs:
        names.setdefault(f['name'], []).append(f)
    for name, items in names.items():
        if len(items) > 1:
            print(f"\n{name}:")
            for it in items:
                print(f"  - lines {it['lineno']} to {it.get('end_lineno','?')}")
    print("\nPlanned removals (will remove later duplicates):")
    for r in removals:
        print(f"  - {r['name']} @ lines {r['lineno']}-{r['end_lineno']}")
    if not args.apply:
        print("\nDry run complete. Re-run with --apply to remove duplicates (a .bak will be created).")
    else:
        apply_removals(path, src_lines, removals, backup=True)

if __name__ == '__main__':
    main()