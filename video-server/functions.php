<?php
/**
 * Shared functions for Video Server
 */

// Extend PHP timeout for long-running video generation (10 minutes)
set_time_limit(600);
ini_set('max_execution_time', 600);

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
 * Make API request with proper headers
 */
function apiRequest(string $url, ?array $payload = null, string $method = 'POST'): array {
    $ch = curl_init($url);

    $headers = [
        'Content-Type: application/json',
        'x-goog-api-key: ' . GEMINI_API_KEY
    ];

    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_TIMEOUT => 30,
        CURLOPT_FOLLOWLOCATION => true,
    ]);

    if ($method === 'POST' && $payload !== null) {
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($payload));
    }

    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error = curl_error($ch);
    curl_close($ch);

    return [
        'response' => $response,
        'httpCode' => $httpCode,
        'error' => $error
    ];
}

/**
 * Poll operation until complete
 */
function pollOperation(string $operationName, int $maxAttempts = 60, int $intervalSeconds = 10): array {
    $url = 'https://generativelanguage.googleapis.com/v1beta/' . $operationName . '?key=' . GEMINI_API_KEY;

    for ($i = 0; $i < $maxAttempts; $i++) {
        debugLog("Polling attempt " . ($i + 1) . " for operation: $operationName");

        $result = apiRequest($url, null, 'GET');

        if ($result['error']) {
            return ['error' => 'Polling error: ' . $result['error']];
        }

        $data = json_decode($result['response'], true);
        debugLog("Poll response", $data);

        if (isset($data['done']) && $data['done'] === true) {
            return ['success' => true, 'data' => $data];
        }

        if (isset($data['error'])) {
            return ['error' => 'Operation error: ' . ($data['error']['message'] ?? 'Unknown error')];
        }

        // Wait before next poll
        sleep($intervalSeconds);
    }

    return ['error' => 'Operation timed out after ' . ($maxAttempts * $intervalSeconds) . ' seconds'];
}

/**
 * Download video from URI
 */
function downloadVideo(string $videoUri): array {
    $ch = curl_init($videoUri);

    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_TIMEOUT => 120,
        CURLOPT_HTTPHEADER => [
            'x-goog-api-key: ' . GEMINI_API_KEY
        ]
    ]);

    $videoData = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $contentType = curl_getinfo($ch, CURLINFO_CONTENT_TYPE);
    $error = curl_error($ch);
    curl_close($ch);

    if ($error) {
        return ['error' => 'Download error: ' . $error];
    }

    if ($httpCode !== 200) {
        return ['error' => 'Download failed with HTTP ' . $httpCode];
    }

    return [
        'success' => true,
        'data' => base64_encode($videoData),
        'mimeType' => $contentType ?: 'video/mp4'
    ];
}

/**
 * Generate video using Veo API
 */
function generateVideo(string $prompt, string $aspectRatio = '16:9', string $resolution = '720p', string $duration = '8'): array {
    if (GEMINI_API_KEY === 'YOUR_GEMINI_API_KEY_HERE' || empty(GEMINI_API_KEY)) {
        return ['status' => 'error', 'error' => 'GEMINI_API_KEY is not configured'];
    }

    // Validate parameters
    if (!isset(ASPECT_RATIOS[$aspectRatio])) {
        $aspectRatio = '16:9';
    }
    if (!isset(RESOLUTIONS[$resolution])) {
        $resolution = '720p';
    }

    // Ensure duration is valid (Veo API only accepts 4, 6, or 8 seconds)
    $durationInt = (int)$duration;
    if (!in_array($durationInt, [4, 6, 8])) {
        $durationInt = 8;
    }

    // Build the request payload
    $payload = [
        'instances' => [
            ['prompt' => $prompt]
        ],
        'parameters' => [
            'aspectRatio' => $aspectRatio,
            'resolution' => $resolution,
            'durationSeconds' => $durationInt
        ]
    ];

    $url = GEMINI_API_BASE . VEO_MODEL . ':predictLongRunning?key=' . GEMINI_API_KEY;

    debugLog("Veo API Request: $url", $payload);

    // Start video generation
    $result = apiRequest($url, $payload);

    debugLog("Veo Initial Response [{$result['httpCode']}]", $result['response']);

    if ($result['error']) {
        return ['status' => 'error', 'error' => "Network error: {$result['error']}"];
    }

    $data = json_decode($result['response'], true);

    if ($result['httpCode'] !== 200) {
        return ['status' => 'error', 'error' => "API error ({$result['httpCode']}): " . ($data['error']['message'] ?? 'Unknown')];
    }

    // Get operation name for polling
    $operationName = $data['name'] ?? null;
    if (!$operationName) {
        return ['status' => 'error', 'error' => 'No operation name in response'];
    }

    debugLog("Operation started: $operationName");

    // Poll for completion
    $pollResult = pollOperation($operationName);

    if (isset($pollResult['error'])) {
        return ['status' => 'error', 'error' => $pollResult['error']];
    }

    // Extract video URI from response
    $responseData = $pollResult['data']['response'] ?? [];
    $generatedVideos = $responseData['generateVideoResponse']['generatedSamples']
        ?? $responseData['generatedVideos']
        ?? [];

    if (empty($generatedVideos)) {
        debugLog("Full poll response", $pollResult['data']);
        return ['status' => 'error', 'error' => 'No video was generated'];
    }

    $videoUri = $generatedVideos[0]['video']['uri'] ?? null;
    if (!$videoUri) {
        return ['status' => 'error', 'error' => 'No video URI in response'];
    }

    debugLog("Video URI: $videoUri");

    // Download the video
    $downloadResult = downloadVideo($videoUri);

    if (isset($downloadResult['error'])) {
        return ['status' => 'error', 'error' => $downloadResult['error']];
    }

    return [
        'status' => 'completed',
        'prompt' => $prompt,
        'aspectRatio' => $aspectRatio,
        'resolution' => $resolution,
        'duration' => (string)$durationInt,
        'provider' => 'gemini',
        'videoBase64' => $downloadResult['data'],
        'mimeType' => $downloadResult['mimeType']
    ];
}

/**
 * Make Grok API request with proper headers
 */
function grokApiRequest(string $url, ?array $payload = null, string $method = 'POST'): array {
    $ch = curl_init($url);

    $headers = [
        'Content-Type: application/json',
        'Authorization: Bearer ' . GROK_API_KEY
    ];

    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => $headers,
        CURLOPT_TIMEOUT => 30,
        CURLOPT_FOLLOWLOCATION => true,
    ]);

    if ($method === 'POST' && $payload !== null) {
        curl_setopt($ch, CURLOPT_POST, true);
        curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode($payload));
    }

    $response = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $error = curl_error($ch);
    curl_close($ch);

    return [
        'response' => $response,
        'httpCode' => $httpCode,
        'error' => $error
    ];
}

/**
 * Poll Grok video operation until complete
 */
function pollGrokOperation(string $requestId, int $maxAttempts = 120, int $intervalSeconds = 5): array {
    $url = GROK_API_BASE . 'videos/' . $requestId;
    debugLog("Starting Grok polling at URL: $url");

    for ($i = 0; $i < $maxAttempts; $i++) {
        $attemptNum = $i + 1;
        $elapsedTime = $i * $intervalSeconds;
        debugLog("Grok polling attempt $attemptNum/$maxAttempts (elapsed: {$elapsedTime}s) for request: $requestId");

        $result = grokApiRequest($url, null, 'GET');

        debugLog("Grok poll raw response", [
            'httpCode' => $result['httpCode'],
            'error' => $result['error'],
            'responseLength' => strlen($result['response']),
            'response' => substr($result['response'], 0, 1000)
        ]);

        if ($result['error']) {
            debugLog("ERROR: Network error during polling: " . $result['error']);
            return ['error' => 'Polling error: ' . $result['error']];
        }

        if ($result['httpCode'] === 404) {
            debugLog("ERROR: Request ID not found (404)");
            return ['error' => 'Request ID not found - video generation may have failed or expired'];
        }

        // 200 = done, 202 = still processing (both are valid)
        if ($result['httpCode'] !== 200 && $result['httpCode'] !== 202) {
            debugLog("ERROR: Unexpected HTTP code during polling: " . $result['httpCode']);
            return ['error' => "Polling failed with HTTP {$result['httpCode']}: " . substr($result['response'], 0, 200)];
        }

        $data = json_decode($result['response'], true);

        if (json_last_error() !== JSON_ERROR_NONE) {
            debugLog("ERROR: JSON parse error: " . json_last_error_msg());
            return ['error' => 'Invalid JSON response: ' . json_last_error_msg()];
        }

        debugLog("Grok poll parsed response (attempt $attemptNum)", $data);

        // Check if video is ready (Grok returns video object when done, no status field)
        if (isset($data['video']['url'])) {
            debugLog("SUCCESS: Video is ready with URL: " . $data['video']['url']);
            return ['success' => true, 'data' => $data];
        }

        // Check for completion status (try multiple field names)
        $status = $data['status'] ?? $data['state'] ?? null;
        debugLog("Current status: " . ($status ?? 'null'));

        if ($status) {
            if (in_array($status, ['done', 'completed', 'succeeded', 'success'])) {
                debugLog("SUCCESS: Video generation completed with status: $status");
                return ['success' => true, 'data' => $data];
            }
            if (in_array($status, ['expired', 'failed', 'error', 'cancelled'])) {
                $errorMsg = $data['error'] ?? $data['message'] ?? "Video generation $status";
                debugLog("ERROR: Video generation failed with status: $status - $errorMsg");
                return ['error' => is_array($errorMsg) ? json_encode($errorMsg) : $errorMsg];
            }
            // Status is pending/processing/in_progress - continue polling
            debugLog("Status is '$status' - continuing to poll...");
        }

        if (isset($data['error'])) {
            $errorMsg = $data['error']['message'] ?? (is_string($data['error']) ? $data['error'] : json_encode($data['error']));
            debugLog("ERROR: Operation error: $errorMsg");
            return ['error' => 'Operation error: ' . $errorMsg];
        }

        // Wait before next poll
        sleep($intervalSeconds);
    }

    debugLog("ERROR: Polling timed out after " . ($maxAttempts * $intervalSeconds) . " seconds");
    return ['error' => 'Operation timed out after ' . ($maxAttempts * $intervalSeconds) . ' seconds'];
}

/**
 * Download video from Grok URL
 */
function downloadGrokVideo(string $videoUrl): array {
    $ch = curl_init($videoUrl);

    curl_setopt_array($ch, [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_FOLLOWLOCATION => true,
        CURLOPT_TIMEOUT => 120,
    ]);

    $videoData = curl_exec($ch);
    $httpCode = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $contentType = curl_getinfo($ch, CURLINFO_CONTENT_TYPE);
    $error = curl_error($ch);
    curl_close($ch);

    if ($error) {
        return ['error' => 'Download error: ' . $error];
    }

    if ($httpCode !== 200) {
        return ['error' => 'Download failed with HTTP ' . $httpCode];
    }

    return [
        'success' => true,
        'data' => base64_encode($videoData),
        'mimeType' => $contentType ?: 'video/mp4'
    ];
}

/**
 * Generate video using Grok Imagine API
 */
function generateVideoGrok(string $prompt, string $aspectRatio = '16:9', string $resolution = '720p', string $duration = '8'): array {
    debugLog("=== GROK VIDEO GENERATION STARTED ===");
    debugLog("Input params", [
        'prompt' => $prompt,
        'aspectRatio' => $aspectRatio,
        'resolution' => $resolution,
        'duration' => $duration
    ]);

    if (GROK_API_KEY === 'YOUR_GROK_API_KEY_HERE' || empty(GROK_API_KEY)) {
        debugLog("ERROR: GROK_API_KEY not configured");
        return ['status' => 'error', 'error' => 'GROK_API_KEY is not configured'];
    }

    debugLog("GROK_API_KEY present (length: " . strlen(GROK_API_KEY) . ")");

    // Validate parameters - Grok supports more aspect ratios
    $validAspectRatios = ['1:1', '16:9', '9:16', '4:3', '3:4', '3:2', '2:3'];
    if (!in_array($aspectRatio, $validAspectRatios)) {
        $aspectRatio = '16:9';
    }

    // Grok only supports 720p and 480p
    if (!in_array($resolution, ['720p', '480p'])) {
        $resolution = '720p';
    }

    // Ensure duration is valid (Grok supports 1-15 seconds)
    $durationInt = (int)$duration;
    if ($durationInt < 1 || $durationInt > 15) {
        $durationInt = 8;
    }

    // Build the request payload
    $payload = [
        'model' => GROK_VIDEO_MODEL,
        'prompt' => $prompt,
        'duration' => $durationInt,
        'aspect_ratio' => $aspectRatio,
        'resolution' => $resolution
    ];

    $url = GROK_API_BASE . 'videos/generations';

    debugLog("Grok API Request URL: $url");
    debugLog("Grok API Request Payload", $payload);

    // Start video generation
    $result = grokApiRequest($url, $payload);

    debugLog("Grok API Response", [
        'httpCode' => $result['httpCode'],
        'error' => $result['error'],
        'response' => $result['response']
    ]);

    if ($result['error']) {
        $errorMsg = "Network error: {$result['error']}";
        debugLog("ERROR: $errorMsg");
        return ['status' => 'error', 'error' => $errorMsg];
    }

    $data = json_decode($result['response'], true);

    if (json_last_error() !== JSON_ERROR_NONE) {
        $errorMsg = "JSON parse error: " . json_last_error_msg() . " - Raw response: " . substr($result['response'], 0, 500);
        debugLog("ERROR: $errorMsg");
        return ['status' => 'error', 'error' => $errorMsg];
    }

    debugLog("Grok API Parsed Response", $data);

    if ($result['httpCode'] !== 200 && $result['httpCode'] !== 202) {
        $errorDetail = $data['error']['message'] ?? $data['error'] ?? $data['message'] ?? json_encode($data);
        $errorMsg = "API error ({$result['httpCode']}): $errorDetail";
        debugLog("ERROR: $errorMsg");
        return ['status' => 'error', 'error' => $errorMsg];
    }

    // Get request_id for polling (try multiple field names)
    $requestId = $data['request_id'] ?? $data['id'] ?? $data['requestId'] ?? null;
    if (!$requestId) {
        $errorMsg = 'No request_id in response. Full response: ' . json_encode($data);
        debugLog("ERROR: $errorMsg");
        return ['status' => 'error', 'error' => $errorMsg];
    }

    debugLog("Grok operation started with request_id: $requestId");

    // Poll for completion
    $pollResult = pollGrokOperation($requestId);

    if (isset($pollResult['error'])) {
        debugLog("ERROR during polling: " . $pollResult['error']);
        return ['status' => 'error', 'error' => $pollResult['error']];
    }

    debugLog("Grok polling completed successfully", $pollResult['data']);

    // Extract video URL from response (try multiple field paths)
    $videoUrl = $pollResult['data']['video']['url']
        ?? $pollResult['data']['output']['url']
        ?? $pollResult['data']['url']
        ?? $pollResult['data']['result']['url']
        ?? null;

    if (!$videoUrl) {
        debugLog("ERROR: No video URL found in response", $pollResult['data']);
        return ['status' => 'error', 'error' => 'No video URL in response. Keys: ' . implode(', ', array_keys($pollResult['data']))];
    }

    debugLog("Grok Video URL: $videoUrl");

    // Download the video
    $downloadResult = downloadGrokVideo($videoUrl);

    if (isset($downloadResult['error'])) {
        debugLog("ERROR downloading video: " . $downloadResult['error']);
        return ['status' => 'error', 'error' => $downloadResult['error']];
    }

    debugLog("=== GROK VIDEO GENERATION COMPLETED ===");

    return [
        'status' => 'completed',
        'prompt' => $prompt,
        'aspectRatio' => $aspectRatio,
        'resolution' => $resolution,
        'duration' => (string)$durationInt,
        'provider' => 'grok',
        'videoBase64' => $downloadResult['data'],
        'mimeType' => $downloadResult['mimeType']
    ];
}
