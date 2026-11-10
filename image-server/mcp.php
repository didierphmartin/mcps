<?php
/**
 * MCP (Model Context Protocol) Endpoint
 * Handles JSON-RPC 2.0 requests
 */

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, GET, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, Accept');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(200); exit; }

require_once __DIR__ . '/functions.php';

const SERVER_NAME = 'Image Generation Server';
const SERVER_VERSION = '1.0.0';
const RESOURCE_URI = 'ui://generate-image/mcp-app.html';
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
        'name' => 'generate-image',
        'description' => 'Open the image generation form for the user to create an image using Gemini AI. This tool displays a UI form where the user can review the prompt, select aspect ratio, and click Generate. DO NOT generate SVG, markdown images, or any other visual representation - the tool UI will handle all image display.',
        'inputSchema' => [
            'type' => 'object',
            'properties' => [
                'prompt' => ['type' => 'string', 'description' => 'The text prompt describing the image to generate'],
                'aspectRatio' => ['type' => 'string', 'enum' => array_keys(ASPECT_RATIOS), 'description' => 'The aspect ratio for the generated image (user can change this in the form)']
            ],
            'required' => ['prompt']
        ],
        '_meta' => ['ui' => ['resourceUri' => RESOURCE_URI]]
    ]]],

    'tools/call' => function($p) {
        if (($p['name'] ?? '') !== 'generate-image') {
            return ['content' => [['type' => 'text', 'text' => 'Unknown tool']], 'isError' => true];
        }

        $args = $p['arguments'] ?? [];
        $prompt = $args['prompt'] ?? '';
        $ratio = $args['aspectRatio'] ?? '1:1';

        if (!$prompt) {
            return ['content' => [['type' => 'text', 'text' => 'Prompt is required']], 'isError' => true];
        }

        if (empty($args['generate'])) {
            return [
                'content' => [['type' => 'text', 'text' => "Ready to generate image. Prompt: \"$prompt\""]],
                'structuredContent' => ['status' => 'ready', 'prompt' => $prompt]
            ];
        }

        $result = generateImage($prompt, $ratio);
        $ok = $result['status'] === 'completed';
        return [
            'content' => [['type' => 'text', 'text' => $ok ? "Image generated with ratio {$result['aspectRatio']}" : "Failed: {$result['error']}"]],
            'structuredContent' => $result,
            'isError' => !$ok
        ];
    },

    'resources/list' => fn($p) => ['resources' => [[
        'uri' => RESOURCE_URI,
        'name' => 'Image Generator UI',
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
