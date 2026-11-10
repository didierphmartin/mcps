<?php
/**
 * TradingView Chart MCP Server
 * Handles JSON-RPC 2.0 requests for displaying interactive TradingView charts
 */

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, GET, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, Accept');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(200); exit; }

const SERVER_NAME = 'TradingView Chart Server';
const SERVER_VERSION = '1.0.0';
const RESOURCE_URI = 'ui://tradingview-chart/mcp-app.html';
const RESOURCE_MIME = 'application/vnd.anthropic.resource+html';

const INTERVALS = ['1', '5', '15', '30', '60', '240', 'D', 'W', 'M'];

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
        'name' => 'show-financial-chart',
        'description' => 'DISPLAYS a real-time interactive TradingView chart widget in the UI. When you call this tool, a live chart automatically appears - DO NOT draw or generate any SVG, ASCII, or visual representation yourself. '
            . 'This tool handles ALL chart visualization. Just call it with the symbol and the user will see the real TradingView chart. '
            . 'Symbols: XAUUSD (gold), BTCUSD (Bitcoin), ETHUSD (Ethereum), AAPL (Apple), EURUSD (forex), NASDAQ:TSLA, BINANCE:ETHUSDT.',
        'inputSchema' => [
            'type' => 'object',
            'properties' => [
                'symbol' => [
                    'type' => 'string',
                    'default' => 'AAPL',
                    'description' => 'Trading symbol to display. Can include exchange prefix (e.g., NASDAQ:AAPL, BINANCE:BTCUSDT). Common symbols: AAPL, GOOGL, MSFT (stocks), BTCUSD, ETHUSD (crypto), EURUSD (forex), US10Y (bonds).'
                ],
                'interval' => [
                    'type' => 'string',
                    'enum' => INTERVALS,
                    'default' => 'D',
                    'description' => 'Chart timeframe: 1/5/15/30/60/240 (minutes), D (daily), W (weekly), M (monthly)'
                ]
            ],
            'required' => ['symbol']
        ],
        '_meta' => ['ui' => [
            'resourceUri' => RESOURCE_URI,
            'csp' => [
                // Per MCP Apps spec: resourceDomains for scripts/styles/images/fonts
                'resourceDomains' => ['https://*.tradingview.com', 'https://s3.tradingview.com'],
                // connectDomains for fetch/XHR/WebSocket
                'connectDomains' => ['https://*.tradingview.com', 'wss://*.tradingview.com']
            ]
        ]]
    ]]],

    'tools/call' => function($p) {
        if (($p['name'] ?? '') !== 'show-financial-chart') {
            return ['content' => [['type' => 'text', 'text' => 'Unknown tool']], 'isError' => true];
        }

        $args = $p['arguments'] ?? [];
        $symbol = $args['symbol'] ?? 'AAPL';
        $interval = $args['interval'] ?? 'D';

        if (!in_array($interval, INTERVALS)) {
            $interval = 'D';
        }

        return [
            'content' => [['type' => 'text', 'text' => "Displaying $symbol chart with $interval interval."]]
        ];
    },

    'resources/list' => fn($p) => ['resources' => [[
        'uri' => RESOURCE_URI,
        'name' => 'TradingView Chart UI',
        'mimeType' => RESOURCE_MIME
    ]]],

    'resources/read' => fn($p) => [
        'contents' => ($p['uri'] ?? '') === RESOURCE_URI
            ? [[
                'uri' => RESOURCE_URI,
                'mimeType' => RESOURCE_MIME,
                'text' => file_get_contents(__DIR__ . '/mcp-app.html') ?: '',
                '_meta' => ['ui' => [
                    'csp' => [
                        'resourceDomains' => ['https://*.tradingview.com', 'https://s3.tradingview.com'],
                        'connectDomains' => ['https://*.tradingview.com', 'wss://*.tradingview.com']
                    ]
                ]]
            ]]
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

if (!isset($handlers[$method])) {
    error($id, -32601, "Method not found: $method");
}

respond($id, $handlers[$method]($req['params'] ?? []));
