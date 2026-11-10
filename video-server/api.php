<?php
/**
 * Video Generation REST API Endpoint
 */

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(200); exit; }

require_once __DIR__ . '/functions.php';

function respond(array $data, int $code = 200): never {
    http_response_code($code);
    die(json_encode($data, JSON_UNESCAPED_UNICODE));
}

if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    respond(['status' => 'error', 'error' => 'Method not allowed'], 405);
}

$input = json_decode(file_get_contents('php://input'), true);

if (!$input) {
    respond(['status' => 'error', 'error' => 'Invalid JSON input'], 400);
}

$prompt = trim($input['prompt'] ?? '');
$aspectRatio = $input['aspectRatio'] ?? '16:9';
$resolution = $input['resolution'] ?? '720p';
$duration = $input['duration'] ?? '8';
$generate = $input['generate'] ?? false;

if (!$prompt) {
    respond(['status' => 'error', 'error' => 'Prompt is required'], 400);
}

if (!$generate) {
    respond(['status' => 'ready', 'prompt' => $prompt, 'aspectRatio' => $aspectRatio, 'resolution' => $resolution, 'duration' => $duration]);
}

$result = generateVideo($prompt, $aspectRatio, $resolution, $duration);
respond($result, $result['status'] === 'error' ? 500 : 200);
