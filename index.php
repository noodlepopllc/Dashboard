<?php
declare(strict_types=1);
/**
 * HF Pipeline Review Dashboard (Tree API Mode)
 * No catalog.json needed for rendering. 
 * Project Index dynamically finds projects by locating catalog.json files.
 */

const DEFAULT_BUCKET = 'noodlepop/preview';
const HUB = 'https://huggingface.co';

$bucket = $_GET['bucket'] ?? DEFAULT_BUCKET;
$parts = explode('/', trim($bucket, '/'));
if (count($parts) !== 2) {
    die("Invalid bucket format. Use: namespace/bucket");
}
[$ns, $repo] = $parts;

$project = $_GET['project'] ?? null;

// ──────────────────────────────────────────────────────────────
// MODE 1: PROJECT DASHBOARD (when ?project=savage is provided)
// ──────────────────────────────────────────────────────────────
if ($project) {
    // Fetch the entire tree recursively
    $apiUrl = HUB . "/api/buckets/" . rawurlencode($ns) . "/" . rawurlencode($repo) . "/tree?recursive=true";
    $apiJson = @file_get_contents($apiUrl);

    if (!$apiJson) {
        die("Could not fetch file tree from: <br><a href='$apiUrl' style='color:#58a6ff'>$apiUrl</a><br><br><a href='?bucket=" . urlencode($bucket) . "' style='color:#58a6ff'>← Back to Projects Index</a>");
    }

    $tree = json_decode($apiJson, true);
    $allFiles = [];

    if (is_array($tree)) {
        foreach ($tree as $item) {
            // We only care about actual files, not directories
            if (($item['type'] ?? '') === 'file') {
                $path = $item['path'] ?? '';
                
                // 🌟 FILTER: Only include files that belong to this project
                if (str_starts_with($path, $project . '/')) {
                    $filename = basename($path);
                    $ext = strtolower(pathinfo($filename, PATHINFO_EXTENSION));
                    $size = $item['size'] ?? 0;
                    
                    // Categorize based on extension and filename
                    if (in_array($ext, ['png', 'jpg', 'jpeg', 'webp'])) {
                        $cat = 'assets';
                    } elseif (in_array($ext, ['wav', 'mp3', 'ogg'])) {
                        $cat = 'audio';
                    } elseif (in_array($ext, ['mp4', 'webm'])) {
                        $cat = 'video';
                    } elseif ($ext === 'txt' || $ext === 'story' || $ext === 'mmh3') {
                        $cat = (strpos($filename, 'beat_') !== false || $filename === 'script.txt') ? 'prompts' : 'story';
                    } else {
                        $cat = 'other';
                    }

                    // Extract scene name from path (e.g., "savage/scene1/output.mp4" -> "scene1")
                    $relativePath = substr($path, strlen($project) + 1);
                    $scene = explode('/', $relativePath)[0] ?? 'unknown';

                    $allFiles[] = [
                        'path' => $path,
                        'name' => $filename,
                        'ext' => $ext,
                        'size' => $size,
                        'category' => $cat,
                        'scene' => $scene
                    ];
                }
            }
        }
    }

    // Group files by category
    $groups = [
        'video'   => ['label' => '🎬 Final Shots (Video)', 'items' => []],
        'audio'   => ['label' => '🔊 Audio (Voices/Soundscapes)', 'items' => []],
        'assets'  => ['label' => '🖼️ Reference Assets (Chars/BGs)', 'items' => []],
        'prompts' => ['label' => '📝 Shot Prompts & Scripts', 'items' => []],
        'story'   => ['label' => '📚 Story & Metadata', 'items' => []],
    ];

    foreach ($allFiles as $f) {
        $cat = $f['category'];
        if (isset($groups[$cat])) {
            $groups[$cat]['items'][] = $f;
        }
    }

    // Helper functions
    function asset_url(string $ns, string $repo, string $path): string {
        $seg = implode('/', array_map('rawurlencode', explode('/', $path)));
        return HUB . '/buckets/' . rawurlencode($ns) . '/' . rawurlencode($repo) . '/resolve/' . $seg;
    }

    function human_size(int $b): string {
        $u = ['B', 'KB', 'MB', 'GB']; 
        $i = 0; 
        $v = (float)$b;
        while ($v >= 1024 && $i < 3) { $v /= 1024; $i++; }
        return round($v, 1) . ' ' . $u[$i];
    }
    ?>
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Pipeline Review: <?= htmlspecialchars($project) ?></title>
        <style>
            body { font-family: system-ui, -apple-system, sans-serif; background: #0d1117; color: #c9d1d9; margin: 0; padding: 20px; }
            h1 { font-size: 1.5rem; margin-bottom: 5px; color: #f0f6fc; }
            .meta { color: #8b949e; font-size: 0.9rem; margin-bottom: 30px; }
            .meta a { color: #58a6ff; text-decoration: none; }
            .meta a:hover { text-decoration: underline; }
            h2 { border-bottom: 1px solid #30363d; padding-bottom: 8px; margin-top: 40px; color: #f0f6fc; font-size: 1.2rem; }
            .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
            .card { background: #161b22; border: 1px solid #30363d; border-radius: 6px; overflow: hidden; transition: border-color 0.2s; }
            .card:hover { border-color: #58a6ff; }
            .card-header { padding: 8px 12px; font-size: 0.8rem; color: #8b949e; background: #0d1117; border-bottom: 1px solid #30363d; display: flex; flex-direction: column; gap: 4px; }
            .card-header-top { display: flex; justify-content: space-between; align-items: center; }
            .scene-tag { background: #1f6feb; color: #fff; padding: 2px 6px; border-radius: 4px; font-size: 0.7rem; font-weight: 600; }
            .debug-path { font-size: 0.65rem; color: #58a6ff; font-family: monospace; word-break: break-all; }
            .card-body { padding: 12px; text-align: center; }
            .card-body img { max-width: 100%; height: auto; border-radius: 4px; border: 1px solid #30363d; }
            .card-body video, .card-body audio { width: 100%; border-radius: 4px; background: #000; }
            .card-body pre { text-align: left; background: #0d1117; padding: 12px; font-size: 0.75rem; overflow-x: auto; color: #a5d6ff; white-space: pre-wrap; word-wrap: break-word; max-height: 400px; border: 1px solid #30363d; border-radius: 4px; }
            .empty-state { color: #8b949e; font-style: italic; padding: 20px; text-align: center; }
            .back-link { display: inline-block; margin-bottom: 20px; padding: 8px 16px; background: #21262d; border: 1px solid #30363d; border-radius: 6px; color: #c9d1d9; text-decoration: none; }
            .back-link:hover { background: #30363d; }
        </style>
    </head>
    <body>
        <a href="?bucket=<?= urlencode($bucket) ?>" class="back-link">← Back to Projects Index</a>
        <h1>🎬 Pipeline Review: <?= htmlspecialchars($project) ?></h1>
        <div class="meta">
            Bucket: <a href="https://huggingface.co/buckets/<?= htmlspecialchars($bucket) ?>" target="_blank"><?= htmlspecialchars($bucket) ?></a>
            &nbsp;|&nbsp; Total Files: <?= count($allFiles) ?>
        </div>

        <?php foreach ($groups as $cat => $data): ?>
            <?php if (empty($data['items'])) continue; ?>
            <h2><?= htmlspecialchars($data['label']) ?> (<?= count($data['items']) ?>)</h2>
            <div class="grid">
                <?php foreach ($data['items'] as $f): ?>
                    <?php 
                    $url = asset_url($ns, $repo, $f['path']) . '?v=' . ($f['size'] ?? time());
                    $ext = strtolower($f['ext']);
                    $scene = $f['scene'] ?? 'unknown';
                    ?>
                    <div class="card">
                        <div class="card-header">
                            <div class="card-header-top">
                                <span title="<?= htmlspecialchars($f['path']) ?>"><?= htmlspecialchars($f['name']) ?></span>
                                <div>
                                    <span class="scene-tag"><?= htmlspecialchars($scene) ?></span>
                                    <span style="color:#8b949e; margin-left: 8px;"><?= human_size($f['size']) ?></span>
                                </div>
                            </div>
                            <div class="debug-path">Path: <?= htmlspecialchars($f['path']) ?></div>
                        </div>
                        <div class="card-body">
                            <?php if (in_array($ext, ['png', 'jpg', 'jpeg', 'webp'])): ?>
                                <img src="<?= htmlspecialchars($url) ?>" alt="<?= htmlspecialchars($f['name']) ?>" loading="lazy">
                            <?php elseif (in_array($ext, ['mp4', 'webm'])): ?>
                                <video controls preload="metadata"><source src="<?= htmlspecialchars($url) ?>"></video>
                            <?php elseif (in_array($ext, ['wav', 'mp3', 'ogg'])): ?>
                                <audio controls preload="metadata"><source src="<?= htmlspecialchars($url) ?>"></audio>
                            <?php elseif (in_array($ext, ['txt', 'json', 'story', 'mmh3'])): ?>
                                <?php 
                                $textContent = @file_get_contents($url);
                                if ($textContent !== false) {
                                    $displayText = strlen($textContent) > 4000 ? substr($textContent, 0, 4000) . "\n\n... [truncated]" : $textContent;
                                    echo '<pre>' . htmlspecialchars($displayText) . '</pre>';
                                } else {
                                    echo '<div class="empty-state">Preview unavailable. <a href="' . htmlspecialchars($url) . '" target="_blank" style="color:#58a6ff">Open file</a></div>';
                                }
                                ?>
                            <?php else: ?>
                                <div class="empty-state">
                                    <a href="<?= htmlspecialchars($url) ?>" target="_blank" style="color:#58a6ff">Download / Open File</a>
                                </div>
                            <?php endif; ?>
                        </div>
                    </div>
                <?php endforeach; ?>
            </div>
        <?php endforeach; ?>
    </body>
    </html>
    <?php
    exit;
}

// ──────────────────────────────────────────────────────────────
// MODE 2: PROJECT INDEX (when ?project is NOT provided)
// ──────────────────────────────────────────────────────────────

// Fetch the recursive tree to find where catalog.json files live
$apiUrl = HUB . "/api/buckets/" . rawurlencode($ns) . "/" . rawurlencode($repo) . "/tree?recursive=true";
$apiJson = @file_get_contents($apiUrl);

if (!$apiJson) {
    die("Could not fetch project list from API: <a href='$apiUrl' style='color:#58a6ff'>$apiUrl</a>");
}

$tree = json_decode($apiJson, true);
$projects = [];

if (is_array($tree)) {
    foreach ($tree as $item) {
        // We only care about files named catalog.json (or context.json if your pipeline uses that)
        if (($item['type'] ?? '') === 'file') {
            $path = $item['path'] ?? '';
            $filename = basename($path);
            
            if ($filename === 'catalog.json' || $filename === 'context.json') {
                $projectDir = dirname($path);
                
                // Ignore if it's at the root level ('.'), we want subdirectories like 'savage'
                if ($projectDir !== '.' && !in_array($projectDir, $projects)) {
                    $projects[] = $projectDir;
                }
            }
        }
    }
}

sort($projects);
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Projects Index: <?= htmlspecialchars($bucket) ?></title>
    <style>
        body { font-family: system-ui, -apple-system, sans-serif; background: #0d1117; color: #c9d1d9; margin: 0; padding: 40px 20px; }
        h1 { font-size: 1.8rem; margin-bottom: 10px; color: #f0f6fc; }
        .meta { color: #8b949e; font-size: 0.9rem; margin-bottom: 40px; }
        .meta a { color: #58a6ff; text-decoration: none; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 20px; }
        .project-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 24px; text-align: center; transition: all 0.2s; text-decoration: none; color: #c9d1d9; display: block; }
        .project-card:hover { border-color: #58a6ff; transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
        .project-icon { font-size: 2.5rem; margin-bottom: 12px; }
        .project-name { font-size: 1.2rem; font-weight: 600; color: #f0f6fc; margin-bottom: 8px; }
        .project-hint { font-size: 0.85rem; color: #8b949e; }
        .empty-state { color: #8b949e; font-style: italic; padding: 40px; text-align: center; background: #161b22; border-radius: 8px; border: 1px solid #30363d; }
    </style>
</head>
<body>
    <h1>📂 Rendered Projects</h1>
    <div class="meta">
        Bucket: <a href="https://huggingface.co/buckets/<?= htmlspecialchars($bucket) ?>" target="_blank"><?= htmlspecialchars($bucket) ?></a>
    </div>

    <?php if (empty($projects)): ?>
        <div class="empty-state">
            No projects found.<br>
            Make sure the Python pipeline has run and synced at least one project containing a <code>catalog.json</code> file.<br>
            <br>
            Or manually visit: <a href="?bucket=<?= urlencode($bucket) ?>&project=savage" style="color:#58a6ff">?project=savage</a>
        </div>
    <?php else: ?>
        <div class="grid">
            <?php foreach ($projects as $proj): ?>
                <a href="?bucket=<?= urlencode($bucket) ?>&project=<?= urlencode($proj) ?>" class="project-card">
                    <div class="project-icon">🎬</div>
                    <div class="project-name"><?= htmlspecialchars($proj) ?></div>
                    <div class="project-hint">Click to view dashboard</div>
                </a>
            <?php endforeach; ?>
        </div>
    <?php endif; ?>
</body>
</html>