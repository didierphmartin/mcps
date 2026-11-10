<?php
/**
 * Google Maps MCP Server
 * JSON-RPC 2.0 server exposing an interactive Google Maps UI resource.
 *
 * Set your Google Maps JavaScript API key via env var GOOGLE_MAPS_API_KEY
 * or edit the fallback constant below.
 */

header('Content-Type: application/json');
header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: POST, GET, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type, Accept');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') { http_response_code(200); exit; }

const SERVER_NAME = 'Google Maps MCP Server';
const SERVER_VERSION = '1.0.0';
const RESOURCE_URI = 'ui://google-maps/mcp-app.html';
const RESOURCE_MIME = 'application/vnd.anthropic.resource+html';
const LOG_FILE = __DIR__ . '/mcp.log';
const LOG_MAX_BYTES = 2_000_000; // ~2MB then truncate

const MAP_TYPES = ['roadmap', 'satellite', 'hybrid', 'terrain'];
const TRAVEL_MODES = ['DRIVING', 'WALKING', 'BICYCLING', 'TRANSIT'];

// Append a structured line to mcp.log. Disable with MCP_DEBUG=0 in .env.
function log_debug(string $tag, $data = null): void {
    if (getenv('MCP_DEBUG') === '0') return;
    if (is_file(LOG_FILE) && filesize(LOG_FILE) > LOG_MAX_BYTES) {
        @file_put_contents(LOG_FILE, ''); // truncate instead of growing forever
    }
    $line = '[' . date('Y-m-d H:i:s') . '] ' . $tag;
    if ($data !== null) {
        $json = is_string($data) ? $data : json_encode($data, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $line .= ' ' . $json;
    }
    @file_put_contents(LOG_FILE, $line . "\n", FILE_APPEND);
}

// Minimal .env loader (KEY=VALUE per line, # comments, optional quotes)
function load_env(string $path): void {
    if (!is_file($path)) return;
    foreach (file($path, FILE_IGNORE_NEW_LINES | FILE_SKIP_EMPTY_LINES) as $line) {
        $line = trim($line);
        if ($line === '' || $line[0] === '#') continue;
        if (!str_contains($line, '=')) continue;
        [$k, $v] = array_map('trim', explode('=', $line, 2));
        if ($k === '') continue;
        if (strlen($v) >= 2 && ($v[0] === '"' || $v[0] === "'") && $v[0] === substr($v, -1)) {
            $v = substr($v, 1, -1);
        }
        if (getenv($k) === false) {
            putenv("$k=$v");
            $_ENV[$k] = $v;
        }
    }
}
load_env(__DIR__ . '/.env');
load_env(__DIR__ . '/.env.example');

// Read API key (env / .env first, then legacy .api_key file, then empty)
function api_key(): string {
    $k = getenv('GOOGLE_MAPS_API_KEY');
    if ($k) return $k;
    $f = __DIR__ . '/.api_key';
    if (is_file($f)) return trim(file_get_contents($f));
    return '';
}

// JSON-RPC helpers
function respond($id, $result): never {
    die(json_encode(['jsonrpc' => '2.0', 'id' => $id, 'result' => $result]));
}
function rpc_error($id, int $code, string $msg): never {
    die(json_encode(['jsonrpc' => '2.0', 'id' => $id, 'error' => ['code' => $code, 'message' => $msg]]));
}

// ---- HTTP helpers (cURL-based) ----
// Returns [httpCode, decodedJson|null, errorMessage|null]
function http_json(string $method, string $url, ?array $body = null, array $headers = []): array {
    $ch = curl_init($url);
    $opts = [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 15,
        CURLOPT_CONNECTTIMEOUT => 5,
        CURLOPT_HTTPHEADER => array_merge(['Accept: application/json'], $headers),
    ];
    if ($method === 'POST') {
        $opts[CURLOPT_POST] = true;
        $opts[CURLOPT_POSTFIELDS] = $body !== null ? json_encode($body) : '';
        $opts[CURLOPT_HTTPHEADER][] = 'Content-Type: application/json';
    }
    curl_setopt_array($ch, $opts);
    $raw = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $err = curl_errno($ch) ? curl_error($ch) : null;
    curl_close($ch);
    $decoded = $raw !== false ? json_decode($raw, true) : null;
    log_debug('http ' . $method, ['url' => $url, 'code' => $code, 'err' => $err, 'bytes' => $raw === false ? 0 : strlen($raw)]);
    return [$code, $decoded, $err];
}

// ---- Google Maps API calls ----
function google_places_text_search(string $query, ?string $near, int $radius): array {
    $key = api_key();
    if ($key === '') return ['error' => 'API key not configured'];
    $q = $near ? "$query near $near" : $query;
    $body = [
        'textQuery' => $q,
        'pageSize' => 15,
    ];
    if ($radius > 0) {
        // Places v1 accepts locationBias with circle — but we need a center.
        // Simplest: let textQuery carry the "near" hint; skip bias unless we geocode first.
    }
    $headers = [
        'X-Goog-Api-Key: ' . $key,
        'X-Goog-FieldMask: places.displayName,places.formattedAddress,places.location,places.rating,places.userRatingCount,places.id,places.googleMapsUri,places.primaryType',
    ];
    [$code, $json, $err] = http_json('POST', 'https://places.googleapis.com/v1/places:searchText', $body, $headers);
    if ($err) return ['error' => "Network error: $err"];
    if ($code !== 200) return ['error' => "Places API HTTP $code", 'body' => $json];
    $places = $json['places'] ?? [];
    $results = [];
    foreach ($places as $p) {
        $results[] = [
            'name' => $p['displayName']['text'] ?? '',
            'address' => $p['formattedAddress'] ?? '',
            'rating' => $p['rating'] ?? null,
            'userRatingCount' => $p['userRatingCount'] ?? null,
            'lat' => $p['location']['latitude'] ?? null,
            'lng' => $p['location']['longitude'] ?? null,
            'placeId' => $p['id'] ?? null,
            'type' => $p['primaryType'] ?? null,
            'mapsUri' => $p['googleMapsUri'] ?? null,
        ];
    }
    return ['results' => $results];
}

function google_geocode(string $address): array {
    $key = api_key();
    if ($key === '') return ['error' => 'API key not configured'];
    $url = 'https://maps.googleapis.com/maps/api/geocode/json?address=' . rawurlencode($address) . '&key=' . rawurlencode($key);
    [$code, $json, $err] = http_json('GET', $url);
    if ($err) return ['error' => "Network error: $err"];
    if ($code !== 200 || !is_array($json)) return ['error' => "Geocoding HTTP $code"];
    if (($json['status'] ?? '') !== 'OK' || empty($json['results'])) {
        return ['error' => 'Geocode status: ' . ($json['status'] ?? 'UNKNOWN'), 'message' => $json['error_message'] ?? null];
    }
    $top = $json['results'][0];
    return [
        'formattedAddress' => $top['formatted_address'] ?? '',
        'lat' => $top['geometry']['location']['lat'] ?? null,
        'lng' => $top['geometry']['location']['lng'] ?? null,
        'placeId' => $top['place_id'] ?? null,
    ];
}

function google_directions(string $origin, string $destination, string $mode): array {
    $key = api_key();
    if ($key === '') return ['error' => 'API key not configured'];
    $url = 'https://maps.googleapis.com/maps/api/directions/json'
         . '?origin=' . rawurlencode($origin)
         . '&destination=' . rawurlencode($destination)
         . '&mode=' . rawurlencode(strtolower($mode))
         . '&key=' . rawurlencode($key);
    [$code, $json, $err] = http_json('GET', $url);
    if ($err) return ['error' => "Network error: $err"];
    if ($code !== 200 || !is_array($json)) return ['error' => "Directions HTTP $code"];
    if (($json['status'] ?? '') !== 'OK' || empty($json['routes'])) {
        return ['error' => 'Directions status: ' . ($json['status'] ?? 'UNKNOWN'), 'message' => $json['error_message'] ?? null];
    }
    $leg = $json['routes'][0]['legs'][0] ?? [];
    return [
        'startAddress' => $leg['start_address'] ?? '',
        'endAddress' => $leg['end_address'] ?? '',
        'distance' => $leg['distance']['text'] ?? '',
        'duration' => $leg['duration']['text'] ?? '',
        'stepCount' => isset($leg['steps']) ? count($leg['steps']) : 0,
        'summary' => $json['routes'][0]['summary'] ?? '',
    ];
}

// Best-effort reconstruction of this server's public URL so the iframe
// can POST client logs back to mcp.log.
function server_url(): string {
    $scheme = (!empty($_SERVER['HTTPS']) && $_SERVER['HTTPS'] !== 'off') ? 'https' : 'http';
    $host = $_SERVER['HTTP_HOST'] ?? 'localhost';
    $script = $_SERVER['SCRIPT_NAME'] ?? '/mcp.php';
    return $scheme . '://' . $host . $script;
}

// Inject the API key and server URL placeholders into the HTML resource
function render_html(): string {
    $html = file_get_contents(__DIR__ . '/mcp-app.html') ?: '';
    $html = str_replace('__GOOGLE_MAPS_API_KEY__', api_key(), $html);
    $html = str_replace('__MCP_SERVER_URL__', server_url(), $html);
    return $html;
}

$csp = [
    'resourceDomains' => [
        'https://maps.googleapis.com',
        'https://maps.gstatic.com',
        'https://fonts.googleapis.com',
        'https://fonts.gstatic.com',
        'https://*.googleapis.com',
        'https://*.gstatic.com',
        'https://*.google.com'
    ],
    'connectDomains' => [
        'https://maps.googleapis.com',
        'https://*.googleapis.com',
        'https://*.google.com'
    ]
];

// MCP Handlers
$handlers = [
    'initialize' => fn($p) => [
        'protocolVersion' => '2024-11-05',
        'capabilities' => ['tools' => ['listChanged' => false], 'resources' => ['listChanged' => false]],
        'serverInfo' => ['name' => SERVER_NAME, 'version' => SERVER_VERSION]
    ],

    'initialized' => fn($p) => [],
    'ping' => fn($p) => [],

    'tools/list' => fn($p) => ['tools' => [
        [
            'name' => 'show-map',
            'description' => 'DISPLAYS a live interactive Google Map in the UI centered on a place, address, or lat/lng. '
                . 'A real map widget appears automatically - DO NOT draw or describe the map yourself. '
                . 'Use this for "show me X on a map", "where is Y", or exploring a location.',
            'inputSchema' => [
                'type' => 'object',
                'properties' => [
                    'query' => ['type' => 'string', 'description' => 'Place name or address, e.g. "Eiffel Tower", "1600 Amphitheatre Pkwy". Preferred over lat/lng when available.'],
                    'lat' => ['type' => 'number', 'description' => 'Latitude (used if query not provided)'],
                    'lng' => ['type' => 'number', 'description' => 'Longitude (used if query not provided)'],
                    'zoom' => ['type' => 'integer', 'minimum' => 1, 'maximum' => 21, 'default' => 13],
                    'mapType' => ['type' => 'string', 'enum' => MAP_TYPES, 'default' => 'roadmap'],
                    'marker' => ['type' => 'boolean', 'default' => true, 'description' => 'Place a pin at the center.'],
                    'label' => ['type' => 'string', 'description' => 'Optional label shown in the marker info window.']
                ]
            ],
            '_meta' => ['ui' => ['resourceUri' => RESOURCE_URI, 'csp' => $csp]]
        ],
        [
            'name' => 'show-directions',
            'description' => 'DISPLAYS live turn-by-turn Google Maps directions between two locations. '
                . 'Renders a route on the map with an itinerary panel - do not describe the route in text.',
            'inputSchema' => [
                'type' => 'object',
                'properties' => [
                    'origin' => ['type' => 'string', 'description' => 'Starting address or place name'],
                    'destination' => ['type' => 'string', 'description' => 'Destination address or place name'],
                    'mode' => ['type' => 'string', 'enum' => TRAVEL_MODES, 'default' => 'DRIVING']
                ],
                'required' => ['origin', 'destination']
            ],
            '_meta' => ['ui' => ['resourceUri' => RESOURCE_URI, 'csp' => $csp]]
        ],
        [
            'name' => 'search-places',
            'description' => 'DISPLAYS Google Maps results for a nearby-place search (e.g. "coffee near Times Square"). '
                . 'Each result is pinned on the map with its name and rating.',
            'inputSchema' => [
                'type' => 'object',
                'properties' => [
                    'query' => ['type' => 'string', 'description' => 'Search query, e.g. "pizza", "museums", "pharmacies"'],
                    'near' => ['type' => 'string', 'description' => 'Area to search within, e.g. "Brooklyn, NY"'],
                    'radius' => ['type' => 'integer', 'default' => 2000, 'description' => 'Search radius in meters (max 50000)']
                ],
                'required' => ['query']
            ],
            '_meta' => ['ui' => ['resourceUri' => RESOURCE_URI, 'csp' => $csp]]
        ]
    ]],

    'tools/call' => function($p) {
        $name = $p['name'] ?? '';
        $args = $p['arguments'] ?? [];
        log_debug('tools/call', ['tool' => $name, 'arguments' => $args]);

        switch ($name) {
            case 'show-map': {
                $where = $args['query'] ?? (isset($args['lat'], $args['lng']) ? "{$args['lat']},{$args['lng']}" : null);
                if (!$where) {
                    return ['content' => [['type' => 'text', 'text' => 'Showing world map.']]];
                }
                // If a query (address/place name) was supplied, geocode it server-side.
                if (!empty($args['query'])) {
                    $geo = google_geocode($args['query']);
                    if (isset($geo['error'])) {
                        return ['content' => [['type' => 'text', 'text' => "Showing map of {$args['query']} (geocode unavailable: {$geo['error']})."]]];
                    }
                    $text = "Showing map of {$geo['formattedAddress']} (lat {$geo['lat']}, lng {$geo['lng']}).";
                    return [
                        'content' => [['type' => 'text', 'text' => $text]],
                        'structuredContent' => ['location' => $geo, 'query' => $args['query']]
                    ];
                }
                $text = "Showing map at {$args['lat']},{$args['lng']}.";
                return [
                    'content' => [['type' => 'text', 'text' => $text]],
                    'structuredContent' => ['location' => ['lat' => $args['lat'], 'lng' => $args['lng']]]
                ];
            }

            case 'show-directions': {
                $o = $args['origin'] ?? '?';
                $d = $args['destination'] ?? '?';
                $m = strtoupper($args['mode'] ?? 'DRIVING');
                $dir = google_directions($o, $d, $m);
                if (isset($dir['error'])) {
                    return ['content' => [['type' => 'text', 'text' => "Directions error ($o → $d, $m): {$dir['error']}"]]];
                }
                $text = "Route {$dir['startAddress']} → {$dir['endAddress']} via "
                      . ($dir['summary'] ?: strtolower($m))
                      . " — {$dir['distance']}, {$dir['duration']} ({$dir['stepCount']} steps).";
                return [
                    'content' => [['type' => 'text', 'text' => $text]],
                    'structuredContent' => ['route' => $dir, 'mode' => $m]
                ];
            }

            case 'search-places': {
                $q = $args['query'] ?? '';
                $n = $args['near'] ?? '';
                $r = (int)($args['radius'] ?? 0);
                if ($q === '') {
                    return ['content' => [['type' => 'text', 'text' => 'Missing query.']], 'isError' => true];
                }
                $res = google_places_text_search($q, $n ?: null, $r);
                if (isset($res['error'])) {
                    return [
                        'content' => [['type' => 'text', 'text' => "Places API error for \"$q\""
                            . ($n ? " near $n" : '') . ": {$res['error']}."]],
                        'structuredContent' => $res,
                        'isError' => false  // iframe still renders its own map; don't block UI
                    ];
                }
                $results = $res['results'] ?? [];
                $count = count($results);
                $header = "Found $count result" . ($count === 1 ? '' : 's') . " for \"$q\""
                        . ($n ? " near $n" : '') . ":";
                $lines = [$header];
                foreach ($results as $i => $pl) {
                    $line = ($i + 1) . '. ' . ($pl['name'] ?: '(no name)');
                    if ($pl['address'])   $line .= " — {$pl['address']}";
                    if ($pl['rating']) {
                        $line .= " — ★ {$pl['rating']}";
                        if ($pl['userRatingCount']) $line .= " ({$pl['userRatingCount']})";
                    }
                    $lines[] = $line;
                }
                return [
                    'content' => [['type' => 'text', 'text' => implode("\n", $lines)]],
                    'structuredContent' => [
                        'query' => $q,
                        'near' => $n,
                        'count' => $count,
                        'results' => $results
                    ]
                ];
            }
        }
        log_debug('tools/call UNKNOWN', ['tool' => $name]);
        return ['content' => [['type' => 'text', 'text' => 'Unknown tool']], 'isError' => true];
    },

    'resources/list' => fn($p) => ['resources' => [[
        'uri' => RESOURCE_URI,
        'name' => 'Google Maps UI',
        'mimeType' => RESOURCE_MIME
    ]]],

    'resources/read' => fn($p) => [
        'contents' => ($p['uri'] ?? '') === RESOURCE_URI
            ? [[
                'uri' => RESOURCE_URI,
                'mimeType' => RESOURCE_MIME,
                'text' => render_html(),
                '_meta' => ['ui' => ['csp' => $csp]]
            ]]
            : []
    ]
];

// Handle request
$raw = file_get_contents('php://input');

// Client-side log relay: iframe POSTs {clientLog: {...}} so browser logs
// land in mcp.log alongside server events. Response is an empty 204.
if ($_SERVER['REQUEST_METHOD'] === 'POST' && $raw) {
    $peek = json_decode($raw, true);
    if (is_array($peek) && isset($peek['clientLog'])) {
        log_debug('client', $peek['clientLog']);
        http_response_code(204);
        exit;
    }
}

// Simple GET endpoint so the iframe can fetch the SAME results the LLM sees
// (instead of running its own client-side Places textSearch, which biases
// by location rather than strictly filtering — and returns neighbouring
// cities). Response matches the structuredContent of tools/call.
if ($_SERVER['REQUEST_METHOD'] === 'GET' && ($_GET['action'] ?? '') === 'search-places') {
    $q = $_GET['query'] ?? '';
    $n = $_GET['near'] ?? '';
    $r = (int)($_GET['radius'] ?? 0);
    log_debug('GET search-places', ['query' => $q, 'near' => $n, 'radius' => $r]);
    if ($q === '') die(json_encode(['error' => 'Missing query']));
    $res = google_places_text_search($q, $n ?: null, $r);
    $res['query'] = $q;
    $res['near'] = $n;
    die(json_encode($res));
}

if ($_SERVER['REQUEST_METHOD'] === 'GET' && !$raw) {
    die(json_encode([
        'name' => SERVER_NAME,
        'version' => SERVER_VERSION,
        'status' => 'ok',
        'apiKeyConfigured' => api_key() !== '',
        'logFile' => LOG_FILE,
        'logExists' => is_file(LOG_FILE)
    ]));
}

$req = json_decode($raw, true);
if (!$req) {
    log_debug('parse-error', ['raw' => substr($raw, 0, 500)]);
    rpc_error(null, -32700, 'Parse error');
}

$id = $req['id'] ?? null;
$method = $req['method'] ?? '';
log_debug('request', ['id' => $id, 'method' => $method, 'params' => $req['params'] ?? null]);

if (!isset($handlers[$method])) {
    log_debug('method-not-found', ['method' => $method]);
    rpc_error($id, -32601, "Method not found: $method");
}

$result = $handlers[$method]($req['params'] ?? []);
log_debug('response', ['id' => $id, 'method' => $method, 'result' => $result]);
respond($id, $result);
