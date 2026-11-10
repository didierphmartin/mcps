<?php
/**
 * Configuration file for Video Server
 */

// Load .env file if it exists
$envFile = __DIR__ . '/.env';
if (file_exists($envFile)) {
    foreach (file($envFile, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (strpos($line, '#') === 0) continue;
        if (strpos($line, '=') !== false) {
            list($key, $value) = explode('=', $line, 2);
            putenv(trim($key) . '=' . trim($value));
        }
    }
}

// Load from environment variable or set directly here
define('GEMINI_API_KEY', getenv('GEMINI_API_KEY') ?: 'YOUR_GEMINI_API_KEY_HERE');
define('GROK_API_KEY', getenv('GROK_API_KEY') ?: getenv('XAI_API_KEY') ?: 'YOUR_GROK_API_KEY_HERE');

// Gemini API base URL
define('GEMINI_API_BASE', 'https://generativelanguage.googleapis.com/v1beta/models/');

// Grok API base URL
define('GROK_API_BASE', 'https://api.x.ai/v1/');

// Model to use for video generation (3.1 supports audio - dialogue & sound effects)
define('VEO_MODEL', 'veo-3.1-generate-preview');
define('GROK_VIDEO_MODEL', 'grok-imagine-video');

// Enable debug mode for troubleshooting
define('DEBUG_MODE', true);

// Supported aspect ratios for Veo
define('ASPECT_RATIOS', [
    '16:9' => '16:9 (Widescreen)',
    '9:16' => '9:16 (Portrait)',
]);

// Supported resolutions
define('RESOLUTIONS', [
    '720p' => '720p (HD)',
    '1080p' => '1080p (Full HD)',
]);

// Supported durations for Gemini Veo (only supports 4, 6, or 8 seconds)
// Note: 1080p resolution requires 8-second duration
define('DURATIONS', [
    '4' => '4 seconds',
    '6' => '6 seconds',
    '8' => '8 seconds',
]);

// Supported durations for Grok Imagine (1-15 seconds)
define('GROK_DURATIONS', [
    '5' => '5 seconds',
    '6' => '6 seconds',
    '7' => '7 seconds',
    '8' => '8 seconds',
    '10' => '10 seconds',
]);

// Supported providers
define('VIDEO_PROVIDERS', [
    'gemini' => 'Gemini Veo 3.1',
    'grok' => 'Grok Imagine',
]);
