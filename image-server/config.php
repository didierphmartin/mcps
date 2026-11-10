<?php
/**
 * Configuration file for Image Server
 *
 * Set your Gemini API key here or via environment variable
 */

// Load .env file if it exists
$envFile = __DIR__ . '/.env';
if (file_exists($envFile)) {
    foreach (file($envFile, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        if (strpos($line, '#') === 0) continue; // Skip comments
        if (strpos($line, '=') !== false) {
            list($key, $value) = explode('=', $line, 2);
            putenv(trim($key) . '=' . trim($value));
        }
    }
}

// Load from environment variable or set directly here
define('GEMINI_API_KEY', getenv('GEMINI_API_KEY') ?: 'YOUR_GEMINI_API_KEY_HERE');

// Gemini API base URL
define('GEMINI_API_BASE', 'https://generativelanguage.googleapis.com/v1beta/models/');

// Model to use for image generation
// Options: 'gemini-2.5-flash-image', 'gemini-3-pro-image-preview'
define('GEMINI_MODEL', 'gemini-2.5-flash-image');

// Enable debug mode for troubleshooting (set to false in production)
define('DEBUG_MODE', true);

// Supported aspect ratios for Gemini 2.5 Flash Image
define('ASPECT_RATIOS', [
    '1:1' => '1:1 (Square)',
    '16:9' => '16:9 (Widescreen)',
    '9:16' => '9:16 (Portrait)',
    '4:3' => '4:3 (Standard)',
    '3:4' => '3:4 (Portrait)',
    '3:2' => '3:2 (Photo)',
    '2:3' => '2:3 (Portrait Photo)',
    '21:9' => '21:9 (Ultrawide)',
    '5:4' => '5:4',
    '4:5' => '4:5',
]);
