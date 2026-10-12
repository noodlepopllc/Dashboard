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
import threading
import time
from pathlib import Path
from huggingface_hub import sync_bucket
import os

def run_cmd(cmd):
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


def update_catalog(project, catalog_path, scene_name, scene_files, shared_assets=None):
    """Update catalog.json, keeping shared assets at the root level."""
    catalog = {}
    if catalog_path.exists():
        with open(catalog_path) as f:
            catalog = json.load(f)

    catalog.setdefault("scenes", {})
    catalog["scenes"].setdefault(scene_name, {"files": []})

    # 1. Update scene-specific files
    scene_file_data = []
    for f in scene_files:
        rel = f.relative_to(project)
        scene_file_data.append({
            "path": str(rel).replace("\\", "/"),
            "name": f.name,
            "size": f.stat().st_size,
            "ext": f.suffix.lstrip(".")
        })
    catalog["scenes"][scene_name]["files"] = scene_file_data

    # 2. Add shared assets ONCE at the root level
    if shared_assets:
        catalog.setdefault("shared_assets", [])
        existing_names = {item["name"] for item in catalog["shared_assets"]}
        for f in shared_assets:
            if f.name not in existing_names:
                rel = f.relative_to(project)
                catalog["shared_assets"].append({
                    "path": str(rel).replace("\\", "/"),
                    "name": f.name,
                    "size": f.stat().st_size,
                    "ext": f.suffix.lstrip(".")
                })

    with open(catalog_path, "w") as f:
        json.dump(catalog, f, indent=2)

    return len(scene_file_data)


def save_to_local_output(scene_files, shared_assets, catalog_path, output_dir, scene_name, dry_run=False):
    """Copy shared assets once, and scene files to their specific folder."""
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    
    # 1. Copy shared assets ONCE to output_dir/assets
    shared_out = out_path / "assets"
    shared_out.mkdir(parents=True, exist_ok=True)
    for f in shared_assets:
        dest = shared_out / f.name
        if not dest.exists():  # Only copy if not already there
            if dry_run:
                print(f"  📋 Would copy (shared): {f.name} -> {dest}")
            else:
                print(f"  📁 Copying (shared): {f.name} -> {dest}")
                shutil.copy2(f, dest)

    # 2. Copy scene-specific files to output_dir/scene_name
    scene_out = out_path / scene_name
    scene_out.mkdir(parents=True, exist_ok=True)
    for f in scene_files:
        dest = scene_out / f.name
        if dry_run:
            print(f"  📋 Would copy (scene): {f.name} -> {dest}")
        else:
            print(f"  📁 Copying (scene): {f.name} -> {dest}")
            shutil.copy2(f, dest)

    # 3. Copy catalog to output root
    shutil.copy2(catalog_path, out_path / "catalog.json")

def hf_sync(output_dir, hf_bucket):
    sync_bucket(str(output_dir), hf_bucket)


# ═══════════════════════════════════════════════════════════════
# BACKGROUND SYNC THREAD
# ═══════════════════════════════════════════════════════════════
def background_sync_loop(project, output_dir, hf_bucket, scenes, patterns, catalog_path, stop_event, interval=30):
    """
    Periodically scans for new/changed files and syncs to bucket.
    Runs in a background thread while the main thread generates scenes.
    """
    known_files = {}  # path -> mtime (tracks what we've already synced)
    
    while not stop_event.is_set():
        try:
            new_files_found = False
            
            for scene_name in scenes:
                scene_dir = Path(project) / scene_name
                if not scene_dir.exists():
                    continue
                
                # 1. Scene-specific files
                scene_files = collect_assets(scene_dir, patterns)
                story_file = Path(project) / "story" / f"{scene_name}.story"
                if story_file.exists():
                    scene_files.append(story_file)
                assets_txt = Path(project) / 'assets.txt'
                if assets_txt.exists():
                    scene_files.append(assets_txt)
                
                # 2. Shared assets
                shared_assets = collect_assets(Path(project) / 'assets', patterns)
                
                # Check for new or modified files in BOTH lists
                all_files = scene_files + shared_assets
                for f in all_files:
                    fpath = str(f)
                    mtime = f.stat().st_mtime
                    if fpath not in known_files or known_files[fpath] < mtime:
                        known_files[fpath] = mtime
                        new_files_found = True
                
                if new_files_found:
                    # Update catalog and copy to output using CORRECT signatures
                    update_catalog(project, catalog_path, scene_name, scene_files, shared_assets)
                    save_to_local_output(scene_files, shared_assets, catalog_path, output_dir, scene_name, dry_run=False)
            
            if new_files_found:
                print(f"\n  🔄 [SYNC] New files detected, syncing to bucket...")
                if hf_bucket.upper() != 'FALSE':
                    hf_sync(str(Path(output_dir).parent), hf_bucket)
                print(f"  ✅ [SYNC] Bucket updated")
                
        except Exception as e:
            print(f"  ⚠️  [SYNC] Error during background sync: {e}")
        
        # Wait for interval or stop signal (whichever comes first)
        stop_event.wait(interval)
    
    # Final sync on shutdown
    print(f"\n  🔄 [SYNC] Final sync on shutdown...")
    for scene_name in scenes:
        scene_dir = Path(project) / scene_name
        if scene_dir.exists():
            scene_files = collect_assets(scene_dir, patterns)
            story_file = Path(project) / "story" / f"{scene_name}.story"
            if story_file.exists():
                scene_files.append(story_file)
            assets_txt = Path(project) / 'assets.txt'
            if assets_txt.exists():
                scene_files.append(assets_txt)
            
            shared_assets = collect_assets(Path(project) / 'assets', patterns)
            
            print(f"\n  📦 Collected {len(scene_files)} scene asset(s) + {len(shared_assets)} shared asset(s) for {scene_name}")
            
            update_catalog(project, catalog_path, scene_name, scene_files, shared_assets)
            save_to_local_output(scene_files, shared_assets, catalog_path, output_dir, scene_name, dry_run=False)
            
    print(f"  🔄 [SYNC] Syncing to bucket (Final)...")
    if hf_bucket.upper() != 'FALSE':
        hf_sync(str(Path(output_dir).parent), hf_bucket)
    print(f"  ✅ [SYNC] Final sync complete")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ini", help="Pipeline config INI file")
    parser.add_argument("--scene", help="Run only this scene")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sync-interval", type=int, default=30,
                        help="Background sync interval in seconds (default: 30)")
    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read(args.ini)

    project = config["pipeline"]["project"]
    input_file = config["pipeline"]["input_file"]
    output_dir = Path(config["pipeline"]["output_dir"]) / project 
    scenes = [s.strip() for s in config["pipeline"]["scenes"].split(",")]
    patterns = [p.strip() for p in config["collect"]["patterns"].split(",")]
    hf_bucket = config["pipeline"]["hf_bucket"]
 
    force = False
    if args.scene:
        scenes = [f'scene{args.scene}']
        force = True

    catalog_path = Path(project) / "catalog.json"

    # Start background sync thread
    stop_event = threading.Event()
    sync_thread = threading.Thread(
        target=background_sync_loop,
        args=(project, output_dir, hf_bucket, scenes, patterns, catalog_path, stop_event, args.sync_interval),
        daemon=True
    )
    sync_thread.start()
    print(f"  🔄 Background sync started (interval: {args.sync_interval}s)")

    try:
        for scene_name in scenes:
            scene_dir = Path(project) / scene_name

            if not force and Path(scene_dir).exists():
                continue

            first = scene_name == scenes[0]
            story_file = Path(project) / "story" / f"{scene_name}.story"
            
            if not first and not story_file.exists():
                print(f"\n  ⏹️  Scene '{scene_name}' not yet generated.")
                print(f"  [INFO] Stopping pipeline gracefully (end of generated scenes).")
                break
            
            if not args.dry_run:
                run_scene(project, scene_name, input_file, config)
            else:
                print(f"\n  📋 [DRY RUN] Would run: {scene_name}")

        print(f"\n{'='*60}")
        print(f"  ✅ Pipeline run complete")
        print(f"{'='*60}")
        
    finally:
        # Signal the sync thread to stop and wait for final sync
        stop_event.set()
        sync_thread.join(timeout=120)
        print(f"  ✅ Background sync stopped")


if __name__ == "__main__":
    main()