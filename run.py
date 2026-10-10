#!/usr/bin/env python3
"""
Pipeline runner: builds refs, runs shots, collects assets, saves locally.
Usage: python run.py pipeline.ini [--scene scene2] [--dry-run]
"""

import sys
import json
import shutil
import subprocess
import argparse
import configparser
from pathlib import Path


def run_cmd(cmd):
    # Always use bash for .sh scripts for cross-platform consistency
    if cmd[0].endswith('.sh'):
        cmd = ['bash', cmd[0]] + cmd[1:]
    
    print(f"  ▶ {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"  ❌ Command failed: exit code {result.returncode}")
        sys.exit(1)


def run_scene(project, scene_name, input_file, config):
    """Run buildref.sh and runall.sh for this scene."""
    buildref = config["scripts"]["buildref"]
    runall = config["scripts"]["runall"]
    
    scene_num = scene_name.replace("scene", "")
    scene_dir = f"{project}/{scene_name}"
    
    print(f"\n{'='*60}")
    print(f"  Building refs for {scene_name}")
    print(f"{'='*60}")
    
    run_cmd([buildref, input_file, project, scene_num])
    
    print(f"\n{'='*60}")
    print(f"  Running shots for {scene_name}")
    print(f"{'='*60}")
    
    run_cmd([runall, scene_dir])
    
    print(f"  ✅ {scene_name} complete")


def collect_assets(scene_dir, patterns):
    """Collect files matching patterns from scene directory."""
    collected = []
    for pattern in patterns:
        pattern = pattern.strip()
        for match in Path(scene_dir).rglob(pattern):
            if match.is_file():
                collected.append(match)
    return sorted(set(collected))


def update_catalog(project, catalog_path, scene_name, files):
    """Update catalog.json with this scene's assets."""
    catalog = {}
    if catalog_path.exists():
        with open(catalog_path) as f:
            catalog = json.load(f)

    catalog.setdefault("scenes", {})
    catalog["scenes"].setdefault(scene_name, {"files": []})

    scene_files = []
    for f in files:
        rel = f.relative_to(project)
        scene_files.append({
            "path": str(rel).replace("\\", "/"),
            "name": f.name,
            "size": f.stat().st_size,
            "ext": f.suffix.lstrip(".")
        })

    catalog["scenes"][scene_name]["files"] = scene_files

    with open(catalog_path, "w") as f:
        json.dump(catalog, f, indent=2)

    return len(scene_files)


def save_to_local_output(files, catalog_path, output_dir, dry_run=False):
    """Copy files and catalog to local output directory."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    
    all_files = list(files) 
    
    shutil.copy2(catalog_path, Path(output_dir).parent)

    for f in all_files:
        dest = out_path / f.name
        if dry_run:
            print(f"  📋 Would copy: {f.name} -> {dest}")
            continue
            
        print(f"  📁 Copying: {f.name} -> {dest}")
        shutil.copy2(f, dest)

    print(f"  ✅ Copied {len(all_files)} file(s) to {output_dir}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ini", help="Pipeline config INI file")
    parser.add_argument("--scene", help="Run only this scene")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read(args.ini)

    project = config["pipeline"]["project"]
    input_file = config["pipeline"]["input_file"]
    output_dir = config["pipeline"]["output_dir"]  # Changed from hf_bucket
    scenes = [s.strip() for s in config["pipeline"]["scenes"].split(",")]
    patterns = [p.strip() for p in config["collect"]["patterns"].split(",")]
 
    force = False
    if args.scene:
        scenes = [f'scene{args.scene}']
        force = True

    catalog_path = Path(project) / "catalog.json"

    for scene_name in scenes:
        scene_dir = Path(project) / scene_name

        if not force and Path(scene_dir).exists():
            continue

        first = scene_name == scenes[0]
        
        # Check if the LLM has generated content for this scene
        # (The .story file is created by the LLM script before run.py runs)
        story_file = Path(project) / "story" / f"{scene_name}.story"
        
        if not first and not story_file.exists():
            print(f"\n  ⏹️  Scene '{scene_name}' not yet generated.")
            print(f"  [INFO] Stopping pipeline gracefully (end of generated scenes).")
            break
        
        # 1. Run the scripts (this creates the scene directory and assets)
        if not args.dry_run:
            run_scene(project, scene_name, input_file, config)
        else:
            print(f"\n  📋 [DRY RUN] Would run: {scene_name}")
        
        # 2. Collect assets (now the directory exists)
        if scene_dir.exists():
            files = collect_assets(scene_dir, patterns)
            files.append(story_file)
            files.append(project / 'assets.txt')
            files += collect_assets(Path(project) / 'assets')
            print(f"\n  📦 Collected {len(files)} asset(s) from {scene_name}")
            
            # 3. Update catalog
            count = update_catalog(project, catalog_path, scene_name, files)
            print(f"  📝 Updated catalog.json ({count} files for {scene_name})")
            
            # 4. Save to local output
            save_to_local_output(files, catalog_path, output_dir / scene_name, args.dry_run)
        else:
            print(f"  ⚠️  Scene directory {scene_dir} was not created by scripts")

    print(f"\n{'='*60}")
    print(f"  ✅ Pipeline run complete")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()