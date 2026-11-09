"""Offline migration inventory validation and dependency-aware draft wave assignment.

Input is an approved CSV export from a discovery tool. This does not discover a
vCenter account, install agents, replicate disks, or execute migrations.
"""
import argparse
import csv
from pathlib import Path

REQUIRED = {"vm_id", "application", "os", "owner", "business_criticality", "migration_strategy", "license_model"}
CRITICALITY = {"low": 1, "medium": 2, "high": 3}
STRATEGIES = {"rehost", "replatform", "refactor", "retire", "retain", "assess"}


def strongly_connected(graph):
    index = 0
    indices, low, stack, active, groups = {}, {}, [], set(), []

    def visit(node):
        nonlocal index
        indices[node] = low[node] = index
        index += 1
        stack.append(node)
        active.add(node)
        for dependency in sorted(graph[node]):
            if dependency not in indices:
                visit(dependency)
                low[node] = min(low[node], low[dependency])
            elif dependency in active:
                low[node] = min(low[node], indices[dependency])
        if low[node] == indices[node]:
            group = []
            while True:
                member = stack.pop()
                active.remove(member)
                group.append(member)
                if member == node:
                    break
            groups.append(sorted(group))

    for node in sorted(graph):
        if node not in indices:
            visit(node)
    return groups


def assign(inventory_path, dependencies_path):
    with inventory_path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if not REQUIRED <= set(reader.fieldnames or []):
            raise ValueError(f"Inventory requires columns: {', '.join(sorted(REQUIRED))}")
        rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
    if not rows:
        raise ValueError("Inventory is empty")
    seen = set()
    for row in rows:
        if any(not row[key] for key in REQUIRED):
            raise ValueError("Required inventory values cannot be blank")
        if row["vm_id"] in seen:
            raise ValueError(f"Duplicate VM: {row['vm_id']}")
        seen.add(row["vm_id"])
        if row["business_criticality"] not in CRITICALITY or row["migration_strategy"] not in STRATEGIES:
            raise ValueError(f"Unsupported criticality or strategy for {row['vm_id']}")
    graph = {row["application"]: set() for row in rows}
    with dependencies_path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if not {"application", "depends_on"} <= set(reader.fieldnames or []):
            raise ValueError("Dependencies require application,depends_on columns")
        for row in reader:
            app, dep = row["application"].strip(), row["depends_on"].strip()
            if app not in graph or dep not in graph:
                raise ValueError(f"Unknown application dependency: {app} -> {dep}")
            if app != dep:
                graph[app].add(dep)
    groups = strongly_connected(graph)
    group_for = {app: index for index, members in enumerate(groups) for app in members}
    group_deps = {index: {group_for[dep] for app in group for dep in graph[app] if group_for[dep] != index} for index, group in enumerate(groups)}
    waves = {}

    def wave(index):
        if index not in waves:
            base = max(CRITICALITY[row["business_criticality"]] for row in rows if row["application"] in groups[index])
            waves[index] = max(base, max((wave(dep) + 1 for dep in group_deps[index]), default=1))
        return waves[index]

    for row in rows:
        group = group_for[row["application"]]
        row.update(draft_wave=str(wave(group)), dependency_group=" + ".join(groups[group]),
                   review_required="YES", evidence="Operator-provided inventory; dependencies not independently verified")
    return sorted(rows, key=lambda row: (int(row["draft_wave"]), row["application"], row["vm_id"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--dependencies", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        rows = assign(args.inventory, args.dependencies)
    except ValueError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Drafted {len(rows)} VM records across {len({row['draft_wave'] for row in rows})} waves. Human dependency, licensing and cutover review REQUIRED. Output: {args.output}")


if __name__ == "__main__":
    main()
