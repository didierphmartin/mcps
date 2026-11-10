<?php
/**
 * Async video generation script
 * Called from mcp.php to generate videos in the background
 * Supports both Gemini Veo and Grok Imagine providers
 */

// Early logging before anything else
$earlyLogFile = __DIR__ . '/debug.log';
$earlyLog = function($msg) use ($earlyLogFile) {
    $timestamp = date('Y-m-d H:i:s');
    file_put_contents($earlyLogFile, "[$timestamp] [ASYNC] $msg\n", FILE_APPEND | LOCK_EX);
};

$earlyLog("=== ASYNC SCRIPT STARTED ===");
$earlyLog("Arguments received: " . json_encode($argv));

if (php_sapi_name() !== 'cli') {
    die('This script must be run from the command line');
}

if ($argc < 6) {
    $earlyLog("ERROR: Not enough arguments (got $argc, need 6)");
    die('Usage: php generate-async.php <jobId> <prompt> <aspectRatio> <resolution> <duration> [provider]');
}

require_once __DIR__ . '/functions.php';

$jobId = $argv[1];
$prompt = $argv[2];
$aspectRatio = $argv[3];
$resolution = $argv[4];
$duration = $argv[5];
$provider = $argv[6] ?? 'gemini';

$earlyLog("Parsed params - jobId: $jobId, provider: $provider, aspectRatio: $aspectRatio, resolution: $resolution, duration: $duration");
$earlyLog("Prompt: $prompt");

$jobFile = __DIR__ . '/jobs/' . basename($jobId) . '.json';

// Update status to generating
file_put_contents($jobFile, json_encode([
    'status' => 'generating',
    'prompt' => $prompt,
    'provider' => $provider,
    'aspectRatio' => $aspectRatio,
    'resolution' => $resolution,
    'duration' => $duration
]));

// Generate the video based on provider
$earlyLog("Starting video generation with provider: $provider");

try {
    if ($provider === 'grok') {
        $earlyLog("Calling generateVideoGrok()...");
        $result = generateVideoGrok($prompt, $aspectRatio, $resolution, $duration);
    } else {
        $earlyLog("Calling generateVideo() (Gemini)...");
        $result = generateVideo($prompt, $aspectRatio, $resolution, $duration);
    }
    $earlyLog("Generation completed with status: " . ($result['status'] ?? 'unknown'));
} catch (Throwable $e) {
    $earlyLog("EXCEPTION: " . $e->getMessage() . " in " . $e->getFile() . ":" . $e->getLine());
    $result = ['status' => 'error', 'error' => 'Exception: ' . $e->getMessage()];
}

// Save the result
$earlyLog("Saving result to job file: $jobFile");
file_put_contents($jobFile, json_encode($result));
$earlyLog("=== ASYNC SCRIPT FINISHED ===");
