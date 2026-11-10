<?php
/**
 * MCP (Model Context Protocol) Endpoint for Video Server
 * Handles JSON-RPC 2.0 requests
 */

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, GET, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, Accept');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(200); exit; }

require_once __DIR__ . '/functions.php';

const SERVER_NAME = 'Video Generation Server';
const SERVER_VERSION = '1.0.0';
const RESOURCE_URI = 'ui://generate-video/mcp-app.html';
const RESOURCE_MIME = 'application/vnd.anthropic.resource+html';

// JSON-RPC helpers
function respond($id, $result): never {
    die(json_encode(['jsonrpc' => '2.0', 'id' => $id, 'result' => $result]));
}

function error($id, int $code, string $msg): never {
    die(json_encode(['jsonrpc' => '2.0', 'id' => $id, 'error' => ['code' => $code, 'message' => $msg]]));
}

// MCP Handlers
$handlers = [
    'initialize' => fn($p) => [
        'protocolVersion' => '2024-11-05',
        'capabilities' => ['tools' => ['listChanged' => false], 'resources' => ['listChanged' => false]],
        'serverInfo' => ['name' => SERVER_NAME, 'version' => SERVER_VERSION]
    ],

    'initialized' => fn($p) => [],
    'ping' => fn($p) => [],

    'tools/list' => fn($p) => ['tools' => [[
        'name' => 'generate-video',
        'description' => 'Open the video generation form for the user to create a video using AI (Gemini Veo or Grok Imagine). This tool displays a UI form where the user can review the prompt, select provider/aspect ratio/resolution/duration, and click Generate. DO NOT generate any other visual representation - the tool UI will handle all video display.',
        'inputSchema' => [
            'type' => 'object',
            'properties' => [
                'prompt' => ['type' => 'string', 'description' => 'The text prompt describing the video to generate'],
                'provider' => ['type' => 'string', 'enum' => array_keys(VIDEO_PROVIDERS), 'description' => 'AI provider to use: gemini (Veo 3.1) or grok (Imagine) - user can change in form'],
                'aspectRatio' => ['type' => 'string', 'enum' => array_keys(ASPECT_RATIOS), 'description' => 'The aspect ratio for the generated video - user can change in form'],
                'resolution' => ['type' => 'string', 'enum' => array_keys(RESOLUTIONS), 'description' => 'The resolution for the generated video - user can change in form'],
                'duration' => ['type' => 'string', 'enum' => ['4', '5', '6', '7', '8', '10'], 'description' => 'The duration of the video in seconds - user can change in form']
            ],
            'required' => ['prompt']
        ],
        '_meta' => ['ui' => ['resourceUri' => RESOURCE_URI]]
    ]]],

    'tools/call' => function($p) {
        if (($p['name'] ?? '') !== 'generate-video') {
            return ['content' => [['type' => 'text', 'text' => 'Unknown tool']], 'isError' => true];
        }

        $args = $p['arguments'] ?? [];
        $prompt = $args['prompt'] ?? '';
        $provider = $args['provider'] ?? 'gemini';
        $aspectRatio = $args['aspectRatio'] ?? '16:9';
        $resolution = $args['resolution'] ?? '720p';
        $duration = $args['duration'] ?? '8';
        $jobId = $args['jobId'] ?? null;

        if (!$prompt) {
            return ['content' => [['type' => 'text', 'text' => 'Prompt is required']], 'isError' => true];
        }

        if (empty($args['generate'])) {
            return [
                'content' => [['type' => 'text', 'text' => "Ready to generate video with $provider. Prompt: \"$prompt\""]],
                'structuredContent' => ['status' => 'ready', 'prompt' => $prompt, 'provider' => $provider, 'aspectRatio' => $aspectRatio, 'resolution' => $resolution, 'duration' => $duration]
            ];
        }

        $jobsDir = __DIR__ . '/jobs';

        // If jobId provided, check status
        if ($jobId) {
            $jobFile = $jobsDir . '/' . basename($jobId) . '.json';
            if (file_exists($jobFile)) {
                $result = json_decode(file_get_contents($jobFile), true);
                if ($result['status'] === 'completed' || $result['status'] === 'error') {
                    unlink($jobFile); // Clean up
                    $ok = $result['status'] === 'completed';
                    return [
                        'content' => [['type' => 'text', 'text' => $ok ? "Video generated ({$result['duration']}s, {$result['aspectRatio']}, {$result['resolution']})" : "Failed: {$result['error']}"]],
                        'structuredContent' => $result,
                        'isError' => !$ok
                    ];
                }
                return [
                    'content' => [['type' => 'text', 'text' => "Video generation in progress (Job: $jobId). The UI is automatically polling for completion. DO NOT call this tool again."]],
                    'structuredContent' => ['status' => 'generating', 'jobId' => $jobId, 'prompt' => $prompt],
                    '_meta' => ['noFollowUp' => true]
                ];
            }
            return [
                'content' => [['type' => 'text', 'text' => 'Job not found']],
                'structuredContent' => ['status' => 'error', 'error' => 'Job not found'],
                'isError' => true
            ];
        }

        // Start new async job
        $newJobId = uniqid('video_', true);
        $jobFile = $jobsDir . '/' . $newJobId . '.json';
        file_put_contents($jobFile, json_encode(['status' => 'generating', 'prompt' => $prompt, 'provider' => $provider]));

        // Start background process using system PHP
        $scriptPath = __DIR__ . '/generate-async.php';
        $cmd = sprintf(
            '/usr/local/bin/php %s %s %s %s %s %s %s > /dev/null 2>&1 &',
            escapeshellarg($scriptPath),
            escapeshellarg($newJobId),
            escapeshellarg($prompt),
            escapeshellarg($aspectRatio),
            escapeshellarg($resolution),
            escapeshellarg($duration),
            escapeshellarg($provider)
        );
        exec($cmd);

        $providerName = VIDEO_PROVIDERS[$provider] ?? $provider;
        return [
            'content' => [['type' => 'text', 'text' => "Video generation started with $providerName (Job: $newJobId). The UI component will automatically display progress and the final video. DO NOT call this tool again - wait for the UI to show the result."]],
            'structuredContent' => ['status' => 'generating', 'jobId' => $newJobId, 'prompt' => $prompt, 'provider' => $provider, 'aspectRatio' => $aspectRatio, 'resolution' => $resolution, 'duration' => $duration],
            '_meta' => ['noFollowUp' => true]
        ];
    },

    'resources/list' => fn($p) => ['resources' => [[
        'uri' => RESOURCE_URI,
        'name' => 'Video Generator UI',
        'mimeType' => RESOURCE_MIME
    ]]],

    'resources/read' => fn($p) => [
        'contents' => ($p['uri'] ?? '') === RESOURCE_URI
            ? [['uri' => RESOURCE_URI, 'mimeType' => RESOURCE_MIME, 'text' => file_get_contents(__DIR__ . '/mcp-app.html') ?: '']]
            : []
    ]
];

// Handle request
$raw = file_get_contents('php://input');

if ($_SERVER['REQUEST_METHOD'] === 'GET' && !$raw) {
    die(json_encode(['name' => SERVER_NAME, 'version' => SERVER_VERSION, 'status' => 'ok']));
}

$req = json_decode($raw, true);
if (!$req) error(null, -32700, 'Parse error');

$id = $req['id'] ?? null;
$method = $req['method'] ?? '';

debugLog("MCP [$method]", $req['params'] ?? null);

if (!isset($handlers[$method])) {
    error($id, -32601, "Method not found: $method");
}

respond($id, $handlers[$method]($req['params'] ?? []));
