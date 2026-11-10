<?php
/**
 * Shared functions for Image Server
 */

require_once __DIR__ . '/config.php';

/**
 * Log debug messages if debug mode is enabled
 */
function debugLog(string $message, $data = null): void {
    if (!defined('DEBUG_MODE') || !DEBUG_MODE) return;

    $logFile = __DIR__ . '/debug.log';
    $timestamp = date('Y-m-d H:i:s');
    $log = "[$timestamp] $message";
    if ($data !== null) {
        $log .= "\n" . (is_string($data) ? $data : json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES));
    }
    file_put_contents($logFile, $log . "\n\n", FILE_APPEND | LOCK_EX);
}

/**
 * Generate image using Gemini API
 */
function generateImage(string $prompt, string $aspectRatio = '1:1'): array {
    if (GEMINI_API_KEY === 'YOUR_GEMINI_API_KEY_HERE' || empty(GEMINI_API_KEY)) {
        return ['status' => 'error', 'error' => 'GEMINI_API_KEY is not configured'];
    }

    if (!isset(ASPECT_RATIOS[$aspectRatio])) {
        $aspectRatio = '1:1';
    }

    $payload = [
        'contents' => [['parts' => [['text' => $prompt]]]],
        'generationConfig' => [
            'responseModalities' => ['TEXT', 'IMAGE'],
            'imageConfig' => [
                'aspectRatio' => $aspectRatio
            ]
        ]
    ];

    $url = GEMINI_API_BASE . GEMINI_MODEL . ':generateContent?key=' . GEMINI_API_KEY;

    debugLog("Gemini API Request: $url", $payload);

    $ch = curl_init($url);
    curl_setopt_array($ch, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => json_encode($payload),
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => ['Content-Type: application/json'],
        CURLOPT_TIMEOUT => 120,
    ]);

    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error = curl_error($ch);
    curl_close($ch);

    debugLog("Gemini Response [$httpCode]", $response);

    if ($error) {
        return ['status' => 'error', 'error' => "Network error: $error"];
    }

    $data = json_decode($response, true);

    if ($httpCode !== 200) {
        return ['status' => 'error', 'error' => "API error ($httpCode): " . ($data['error']['message'] ?? 'Unknown')];
    }

    $parts = $data['candidates'][0]['content']['parts'] ?? [];

    foreach ($parts as $part) {
        if (isset($part['inlineData']['data'])) {
            return [
                'status' => 'completed',
                'prompt' => $prompt,
                'aspectRatio' => $aspectRatio,
                'imageBase64' => $part['inlineData']['data'],
                'mimeType' => $part['inlineData']['mimeType'] ?? 'image/png'
            ];
        }
    }

    // Get text response if no image
    $text = implode(' ', array_column(array_filter($parts, fn($p) => isset($p['text'])), 'text'));
    return ['status' => 'error', 'error' => $text ?: 'No image data in response'];
}
