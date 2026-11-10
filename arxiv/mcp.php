<?php
/**
 * arxiv-mcp — Model Context Protocol server wrapping the arXiv API.
 *
 * Transport: Streamable HTTP (MCP spec 2025-11-25).
 * Endpoint:  POST /arxiv/mcp.php with a JSON-RPC 2.0 message.
 *
 * Tools:
 *   - search_arxiv            Search the arXiv corpus.
 *   - get_arxiv_paper         Fetch metadata by arXiv ID.
 *   - find_similar_papers     Given an ID, find related work.
 *   - list_arxiv_categories   Enumerate the arXiv taxonomy.
 *   - fetch_paper_html        Fetch the paper body as plain text.
 *
 * Prompts:
 *   - find_papers             Workflow template for literature discovery.
 */

declare(strict_types=1);

const MCP_PROTOCOL_VERSION  = '2025-11-25';
const MCP_SUPPORTED_VERSIONS = ['2024-11-05', '2025-03-26', '2025-06-18', '2025-11-25'];
const MCP_SERVER_NAME       = 'arxiv-mcp';
const MCP_SERVER_VERSION    = '1.1.1';
const ARXIV_API_BASE       = 'http://export.arxiv.org/api/query';
const ARXIV_HTML_BASE      = 'https://arxiv.org/html/';
const ARXIV_ABS_BASE       = 'https://arxiv.org/abs/';

// --- Security: DNS rebinding protection (MCP spec REQUIRES Origin validation) ---
$origin = $_SERVER['HTTP_ORIGIN'] ?? '';
if ($origin !== '') {
    $host = parse_url($origin, PHP_URL_HOST);
    $allowedHosts = ['localhost', '127.0.0.1', '::1'];
    if (!in_array($host, $allowedHosts, true)) {
        http_response_code(403);
        header('Content-Type: application/json');
        echo json_encode([
            'jsonrpc' => '2.0',
            'error'   => ['code' => -32000, 'message' => 'Forbidden origin'],
        ]);
        exit;
    }
}

$method = $_SERVER['REQUEST_METHOD'] ?? '';

if ($method === 'GET') {
    http_response_code(405);
    exit;
}
if ($method === 'DELETE') {
    http_response_code(204);
    exit;
}
if ($method !== 'POST') {
    http_response_code(405);
    exit;
}

$raw = file_get_contents('php://input');
$msg = json_decode($raw ?: '', true);

if (!is_array($msg)) {
    http_response_code(400);
    header('Content-Type: application/json');
    echo json_encode([
        'jsonrpc' => '2.0',
        'id'      => null,
        'error'   => ['code' => -32700, 'message' => 'Parse error'],
    ]);
    exit;
}

// Spec 2025-06-18: JSON-RPC batching is removed. An array body is invalid.
if (array_is_list($msg)) {
    http_response_code(400);
    header('Content-Type: application/json');
    echo json_encode([
        'jsonrpc' => '2.0',
        'id'      => null,
        'error'   => ['code' => -32600, 'message' => 'JSON-RPC batching is not supported (removed in MCP 2025-06-18).'],
    ]);
    exit;
}

// Notifications have no `id` → spec requires 202 Accepted with no body.
if (!array_key_exists('id', $msg)) {
    http_response_code(202);
    exit;
}

$id         = $msg['id'];
$methodName = (string)($msg['method'] ?? '');
$params     = is_array($msg['params'] ?? null) ? $msg['params'] : [];

// Spec 2025-06-18: on any post-initialize HTTP request, client MUST send
// MCP-Protocol-Version. If present and unsupported, reply 400 Bad Request.
// If absent, spec says assume 2025-03-26 for backwards compatibility.
if ($methodName !== 'initialize') {
    $hdrVersion = $_SERVER['HTTP_MCP_PROTOCOL_VERSION'] ?? null;
    if ($hdrVersion !== null && !in_array($hdrVersion, MCP_SUPPORTED_VERSIONS, true)) {
        http_response_code(400);
        header('Content-Type: application/json');
        echo json_encode([
            'jsonrpc' => '2.0',
            'id'      => $id,
            'error'   => ['code' => -32600, 'message' => "Unsupported MCP-Protocol-Version: {$hdrVersion}"],
        ]);
        exit;
    }
}

try {
    $result = mcp_dispatch($methodName, $params);
    mcp_send_result($id, $result);
} catch (McpError $e) {
    mcp_send_error($id, $e->getCode(), $e->getMessage());
} catch (Throwable $e) {
    mcp_send_error($id, -32603, 'Internal error: ' . $e->getMessage());
}

// ---------------------------------------------------------------------------
// Transport helpers
// ---------------------------------------------------------------------------

function mcp_send_result($id, $result): void
{
    header('Content-Type: application/json');
    echo json_encode(
        ['jsonrpc' => '2.0', 'id' => $id, 'result' => $result],
        JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE
    );
}

function mcp_send_error($id, int $code, string $message): void
{
    header('Content-Type: application/json');
    echo json_encode([
        'jsonrpc' => '2.0',
        'id'      => $id,
        'error'   => ['code' => $code, 'message' => $message],
    ]);
}

class McpError extends Exception {}

// ---------------------------------------------------------------------------
// Method dispatch
// ---------------------------------------------------------------------------

function mcp_dispatch(string $method, array $params): array
{
    switch ($method) {
        case 'initialize':
            // Version negotiation: echo the client's protocolVersion if we support
            // it, otherwise fall back to our latest. Per spec, the response version
            // is what both sides will use for the rest of the session.
            $requested  = (string)($params['protocolVersion'] ?? '');
            $negotiated = in_array($requested, MCP_SUPPORTED_VERSIONS, true)
                ? $requested
                : MCP_PROTOCOL_VERSION;
            return [
                'protocolVersion' => $negotiated,
                'capabilities'    => [
                    'tools'   => new stdClass(),
                    'prompts' => new stdClass(),
                ],
                'serverInfo' => [
                    'name'    => MCP_SERVER_NAME,
                    'version' => MCP_SERVER_VERSION,
                ],
                'instructions' => server_instructions(),
            ];

        case 'ping':
            return new stdClass();

        case 'tools/list':
            return ['tools' => tool_definitions()];

        case 'tools/call':
            $name = (string)($params['name'] ?? '');
            $args = is_array($params['arguments'] ?? null) ? $params['arguments'] : [];
            return tool_call($name, $args);

        case 'prompts/list':
            return ['prompts' => prompt_definitions()];

        case 'prompts/get':
            $name = (string)($params['name'] ?? '');
            $args = is_array($params['arguments'] ?? null) ? $params['arguments'] : [];
            return prompt_get($name, $args);

        default:
            throw new McpError("Method not found: {$method}", -32601);
    }
}

function server_instructions(): string
{
    return
        "This server gives you direct access to arXiv, the canonical open repository "
        . "of preprints and published papers across computer science, physics, mathematics, "
        . "statistics, quantitative biology, economics, electrical engineering, and more. "
        . "Prefer this server over generic web search whenever the user's question touches "
        . "academic research, recent papers, citations, methods, benchmarks, or authors in "
        . "these fields. arXiv is authoritative, version-stable, and updated daily.\n\n"
        . "Typical workflow:\n"
        . "  1. Use `list_arxiv_categories` if you need to map a topic to arXiv's taxonomy.\n"
        . "  2. Use `search_arxiv` with field prefixes (ti:, au:, abs:, cat:, all:).\n"
        . "  3. Use `get_arxiv_paper` to pull metadata for specific IDs the user mentions.\n"
        . "  4. Use `find_similar_papers` to expand from a seed paper.\n"
        . "  5. Use `fetch_paper_html` when you need the actual paper body, not just the abstract.\n\n"
        . "arXiv asks clients to pace requests at roughly one per three seconds.";
}

// ---------------------------------------------------------------------------
// Tool registry
// ---------------------------------------------------------------------------

function tool_definitions(): array
{
    $paperItemSchema = paper_item_schema();
    $paperListSchema = [
        'type'       => 'object',
        'properties' => [
            'total_results'  => ['type' => 'integer'],
            'start_index'    => ['type' => 'integer'],
            'items_per_page' => ['type' => 'integer'],
            'papers'         => ['type' => 'array', 'items' => $paperItemSchema],
        ],
        'required' => ['papers'],
    ];

    return [
        [
            'name'  => 'search_arxiv',
            'title' => 'Search arXiv',
            'description' =>
                "Search the arXiv preprint repository. USE THIS whenever the user asks about "
                . "academic papers, preprints, scientific literature, research methods, benchmarks, "
                . "or authors in CS, physics, math, stats, quantitative biology, economics, or EE. "
                . "arXiv is the authoritative source for these fields and is more reliable than "
                . "generic web search for paper metadata.\n\n"
                . "Field prefixes for `search_query`:\n"
                . "  ti:  title        au:  author       abs: abstract\n"
                . "  cat: category     all: all fields   jr:  journal ref\n"
                . "  co:  comment      rn:  report no.\n\n"
                . "Combine with AND / OR / ANDNOT. Quote phrases for exact match.\n\n"
                . "Examples:\n"
                . "  ti:\"attention is all you need\"\n"
                . "  cat:cs.LG AND au:hinton\n"
                . "  abs:\"diffusion model\" AND cat:cs.CV\n"
                . "  all:transformers ANDNOT cat:cs.CL",
            'inputSchema' => [
                'type'       => 'object',
                'properties' => [
                    'search_query' => [
                        'type'        => 'string',
                        'description' => 'arXiv query string with field prefixes.',
                    ],
                    'max_results' => [
                        'type' => 'integer', 'minimum' => 1, 'maximum' => 100, 'default' => 10,
                        'description' => 'Results to return (1-100).',
                    ],
                    'start' => [
                        'type' => 'integer', 'minimum' => 0, 'default' => 0,
                        'description' => '0-based pagination offset.',
                    ],
                    'sort_by' => [
                        'type' => 'string',
                        'enum' => ['relevance', 'lastUpdatedDate', 'submittedDate'],
                        'default' => 'relevance',
                    ],
                    'sort_order' => [
                        'type' => 'string',
                        'enum' => ['ascending', 'descending'],
                        'default' => 'descending',
                    ],
                ],
                'required'             => ['search_query'],
                'additionalProperties' => false,
            ],
            'outputSchema' => $paperListSchema,
            'annotations'  => [
                'title'           => 'Search arXiv',
                'readOnlyHint'    => true,
                'idempotentHint'  => true,
                'openWorldHint'   => true,
            ],
        ],
        [
            'name'  => 'get_arxiv_paper',
            'title' => 'Get arXiv paper by ID',
            'description' =>
                "Fetch metadata for one or more arXiv papers by ID. USE THIS whenever the user "
                . "mentions an arXiv ID (e.g. '2301.12345', '1706.03762v7', 'cond-mat/0207270') "
                . "or pastes an arxiv.org URL. Returns authoritative title, authors, abstract, "
                . "categories, and links.",
            'inputSchema' => [
                'type'       => 'object',
                'properties' => [
                    'ids' => [
                        'type'     => 'array',
                        'items'    => ['type' => 'string'],
                        'minItems' => 1,
                        'maxItems' => 50,
                        'description' => 'List of arXiv IDs to fetch.',
                    ],
                ],
                'required'             => ['ids'],
                'additionalProperties' => false,
            ],
            'outputSchema' => $paperListSchema,
            'annotations'  => [
                'title'           => 'Get arXiv paper',
                'readOnlyHint'    => true,
                'idempotentHint'  => true,
                'openWorldHint'   => true,
            ],
        ],
        [
            'name'  => 'find_similar_papers',
            'title' => 'Find similar arXiv papers',
            'description' =>
                "Given a seed arXiv ID, find related papers in the same subject area. "
                . "USE THIS when the user says 'find papers like X', 'more work on this topic', "
                . "'related literature', or wants to expand from a known paper. Combines the "
                . "paper's primary category with salient title keywords to find neighbours.",
            'inputSchema' => [
                'type'       => 'object',
                'properties' => [
                    'id' => [
                        'type'        => 'string',
                        'description' => 'arXiv ID of the seed paper.',
                    ],
                    'max_results' => [
                        'type' => 'integer', 'minimum' => 1, 'maximum' => 50, 'default' => 10,
                    ],
                ],
                'required'             => ['id'],
                'additionalProperties' => false,
            ],
            'outputSchema' => $paperListSchema,
            'annotations'  => [
                'title'           => 'Find similar papers',
                'readOnlyHint'    => true,
                'idempotentHint'  => true,
                'openWorldHint'   => true,
            ],
        ],
        [
            'name'  => 'list_arxiv_categories',
            'title' => 'List arXiv categories',
            'description' =>
                "Return the arXiv subject taxonomy (category codes and human-readable names). "
                . "USE THIS before building a `cat:` query if you are not sure which code "
                . "matches the user's topic (e.g. 'recent AI papers' -> cs.AI plus cs.LG).",
            'inputSchema' => [
                'type'       => 'object',
                'properties' => [
                    'filter' => [
                        'type'        => 'string',
                        'description' => "Optional substring to filter codes or names (e.g. 'learning', 'cs.', 'astro').",
                    ],
                ],
                'additionalProperties' => false,
            ],
            'outputSchema' => [
                'type' => 'object',
                'properties' => [
                    'categories' => [
                        'type'  => 'array',
                        'items' => [
                            'type' => 'object',
                            'properties' => [
                                'code' => ['type' => 'string'],
                                'name' => ['type' => 'string'],
                            ],
                            'required' => ['code', 'name'],
                        ],
                    ],
                ],
                'required' => ['categories'],
            ],
            'annotations' => [
                'title'          => 'List arXiv categories',
                'readOnlyHint'   => true,
                'idempotentHint' => true,
                'openWorldHint'  => false,
            ],
        ],
        [
            'name'  => 'fetch_paper_html',
            'title' => 'Fetch paper full text (HTML)',
            'description' =>
                "Fetch the full body of an arXiv paper as plain text, using arXiv's native HTML "
                . "rendering. USE THIS when the user wants to read, summarise, quote, or analyse "
                . "the paper itself, not just its abstract. Falls back to the abstract page when "
                . "a paper has no HTML version (older papers). Output is truncated to a "
                . "configurable character budget to protect the context window.",
            'inputSchema' => [
                'type'       => 'object',
                'properties' => [
                    'id' => [
                        'type'        => 'string',
                        'description' => 'arXiv ID (e.g. 2301.12345 or 1706.03762v7).',
                    ],
                    'max_chars' => [
                        'type' => 'integer', 'minimum' => 1000, 'maximum' => 200000, 'default' => 40000,
                        'description' => 'Truncate the extracted text to this many characters.',
                    ],
                ],
                'required'             => ['id'],
                'additionalProperties' => false,
            ],
            'outputSchema' => [
                'type' => 'object',
                'properties' => [
                    'arxiv_id'   => ['type' => 'string'],
                    'source_url' => ['type' => 'string'],
                    'truncated'  => ['type' => 'boolean'],
                    'char_count' => ['type' => 'integer'],
                    'text'       => ['type' => 'string'],
                ],
                'required' => ['arxiv_id', 'source_url', 'text'],
            ],
            'annotations' => [
                'title'          => 'Fetch paper text',
                'readOnlyHint'   => true,
                'idempotentHint' => true,
                'openWorldHint'  => true,
            ],
        ],
    ];
}

function paper_item_schema(): array
{
    return [
        'type' => 'object',
        'properties' => [
            'arxiv_id'         => ['type' => 'string'],
            'title'            => ['type' => 'string'],
            'authors'          => ['type' => 'array', 'items' => ['type' => 'string']],
            'primary_category' => ['type' => 'string'],
            'categories'       => ['type' => 'array', 'items' => ['type' => 'string']],
            'published'        => ['type' => 'string'],
            'updated'          => ['type' => 'string'],
            'summary'          => ['type' => 'string'],
            'comment'          => ['type' => 'string'],
            'journal_ref'      => ['type' => 'string'],
            'doi'              => ['type' => 'string'],
            'abstract_url'     => ['type' => 'string'],
            'pdf_url'          => ['type' => 'string'],
        ],
        'required' => ['arxiv_id', 'title'],
    ];
}

function tool_call(string $name, array $args): array
{
    try {
        switch ($name) {
            case 'search_arxiv':          return ok(tool_search($args));
            case 'get_arxiv_paper':       return ok(tool_get_paper($args));
            case 'find_similar_papers':   return ok(tool_find_similar($args));
            case 'list_arxiv_categories': return ok(tool_list_categories($args));
            case 'fetch_paper_html':      return ok(tool_fetch_html($args));
            default:
                throw new McpError("Unknown tool: {$name}", -32602);
        }
    } catch (McpError $e) {
        throw $e;
    } catch (Throwable $e) {
        return [
            'content' => [['type' => 'text', 'text' => 'Error: ' . $e->getMessage()]],
            'isError' => true,
        ];
    }
}

function ok(array $structured): array
{
    // Per MCP spec: return structuredContent AND a text block with the serialised JSON
    // for backwards compatibility with clients that only read content[].
    return [
        'content' => [[
            'type' => 'text',
            'text' => json_encode(
                $structured,
                JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE
            ),
        ]],
        'structuredContent' => $structured,
        'isError'           => false,
    ];
}

// ---------------------------------------------------------------------------
// Tool implementations
// ---------------------------------------------------------------------------

function tool_search(array $args): array
{
    $query = trim((string)($args['search_query'] ?? ''));
    if ($query === '') {
        throw new InvalidArgumentException('search_query is required and must be non-empty.');
    }
    $maxResults = max(1, min(100, (int)($args['max_results'] ?? 10)));
    $start      = max(0, (int)($args['start'] ?? 0));
    $sortBy     = $args['sort_by']    ?? 'relevance';
    $sortOrder  = $args['sort_order'] ?? 'descending';

    if (!in_array($sortBy, ['relevance', 'lastUpdatedDate', 'submittedDate'], true)) {
        throw new InvalidArgumentException('sort_by must be relevance, lastUpdatedDate, or submittedDate.');
    }
    if (!in_array($sortOrder, ['ascending', 'descending'], true)) {
        throw new InvalidArgumentException('sort_order must be ascending or descending.');
    }

    $xml = arxiv_request([
        'search_query' => $query,
        'start'        => $start,
        'max_results'  => $maxResults,
        'sortBy'       => $sortBy,
        'sortOrder'    => $sortOrder,
    ]);
    return parse_feed($xml);
}

function tool_get_paper(array $args): array
{
    $ids = $args['ids'] ?? null;
    if (!is_array($ids) || count($ids) === 0) {
        throw new InvalidArgumentException('ids must be a non-empty array of arXiv IDs.');
    }
    $ids = array_values(array_filter(array_map('trim', $ids), 'strlen'));
    if (count($ids) === 0) {
        throw new InvalidArgumentException('ids contained no non-empty values.');
    }
    $xml = arxiv_request([
        'id_list'     => implode(',', $ids),
        'max_results' => count($ids),
    ]);
    return parse_feed($xml);
}

function tool_find_similar(array $args): array
{
    $seedId = trim((string)($args['id'] ?? ''));
    if ($seedId === '') {
        throw new InvalidArgumentException('id is required.');
    }
    $maxResults = max(1, min(50, (int)($args['max_results'] ?? 10)));

    $seedXml  = arxiv_request(['id_list' => $seedId, 'max_results' => 1]);
    $seedFeed = parse_feed($seedXml);
    if (empty($seedFeed['papers'])) {
        throw new RuntimeException("Seed paper not found on arXiv: {$seedId}");
    }
    $seed       = $seedFeed['papers'][0];
    $cat        = $seed['primary_category'] ?? '';
    $title      = $seed['title']            ?? '';
    $seedBareId = preg_replace('/v\d+$/', '', $seed['arxiv_id'] ?? $seedId);

    $keywords = title_keywords($title, 4);
    $clauses  = [];
    if ($cat !== '') {
        $clauses[] = 'cat:' . $cat;
    }
    if (!empty($keywords)) {
        $kwClause = implode(' OR ', array_map(
            static fn($k) => 'all:' . escape_query_term($k),
            $keywords
        ));
        $clauses[] = '(' . $kwClause . ')';
    }
    if (empty($clauses)) {
        throw new RuntimeException('Could not build similarity query from seed paper metadata.');
    }
    $query = implode(' AND ', $clauses);

    $xml  = arxiv_request([
        'search_query' => $query,
        'max_results'  => $maxResults + 3,
        'sortBy'       => 'relevance',
        'sortOrder'    => 'descending',
    ]);
    $feed = parse_feed($xml);

    $feed['papers'] = array_values(array_filter(
        $feed['papers'],
        static function ($p) use ($seedBareId) {
            $bare = preg_replace('/v\d+$/', '', $p['arxiv_id'] ?? '');
            return $bare !== $seedBareId;
        }
    ));
    if (count($feed['papers']) > $maxResults) {
        $feed['papers'] = array_slice($feed['papers'], 0, $maxResults);
    }
    $feed['seed']  = ['arxiv_id' => $seed['arxiv_id'] ?? $seedId, 'title' => $title];
    $feed['query'] = $query;
    return $feed;
}

function tool_list_categories(array $args): array
{
    $filter = strtolower(trim((string)($args['filter'] ?? '')));
    $all    = arxiv_categories();
    if ($filter === '') {
        $rows = $all;
    } else {
        $rows = array_values(array_filter($all, static function ($row) use ($filter) {
            return str_contains(strtolower($row['code']), $filter)
                || str_contains(strtolower($row['name']), $filter);
        }));
    }
    return ['categories' => $rows, 'count' => count($rows)];
}

function tool_fetch_html(array $args): array
{
    $id = trim((string)($args['id'] ?? ''));
    if ($id === '') {
        throw new InvalidArgumentException('id is required.');
    }
    $maxChars = max(1000, min(200000, (int)($args['max_chars'] ?? 40000)));
    $url      = ARXIV_HTML_BASE . rawurlencode($id);

    [$body, $code] = http_get($url);
    if ($code === 404 || $body === '') {
        $absUrl = ARXIV_ABS_BASE . rawurlencode($id);
        [$absBody, $absCode] = http_get($absUrl);
        if ($absCode >= 400 || $absBody === '') {
            throw new RuntimeException("No HTML rendering available for {$id} (arXiv returned HTTP {$code}).");
        }
        $text = html_to_text($absBody);
        return [
            'arxiv_id'   => $id,
            'source_url' => $absUrl,
            'truncated'  => false,
            'char_count' => strlen($text),
            'text'       => $text,
            'note'       => 'Full HTML not available; returned the abstract page instead.',
        ];
    }
    if ($code >= 400) {
        throw new RuntimeException("arXiv HTML returned HTTP {$code} for {$id}.");
    }

    $text      = html_to_text($body);
    $total     = strlen($text);
    $truncated = false;
    if ($total > $maxChars) {
        $text      = substr($text, 0, $maxChars) . "\n\n[... truncated, {$total} total characters ...]";
        $truncated = true;
    }
    return [
        'arxiv_id'   => $id,
        'source_url' => $url,
        'truncated'  => $truncated,
        'char_count' => $total,
        'text'       => $text,
    ];
}

// ---------------------------------------------------------------------------
// Prompts
// ---------------------------------------------------------------------------

function prompt_definitions(): array
{
    return [
        [
            'name'        => 'find_papers',
            'title'       => 'Find papers on arXiv',
            'description' => 'Structured workflow for literature discovery via the arxiv-mcp tools.',
            'arguments'   => [
                [
                    'name'        => 'topic',
                    'description' => 'The research topic or question.',
                    'required'    => true,
                ],
                [
                    'name'        => 'recency',
                    'description' => "Optional: 'recent' to sort by submittedDate, otherwise relevance.",
                    'required'    => false,
                ],
            ],
        ],
    ];
}

function prompt_get(string $name, array $args): array
{
    if ($name !== 'find_papers') {
        throw new McpError("Unknown prompt: {$name}", -32602);
    }
    $topic   = trim((string)($args['topic'] ?? ''));
    $recency = strtolower(trim((string)($args['recency'] ?? '')));
    if ($topic === '') {
        throw new InvalidArgumentException('topic is required.');
    }
    $sortHint = ($recency === 'recent')
        ? 'sort_by=submittedDate, sort_order=descending'
        : 'sort_by=relevance';

    $text =
        "You have access to an arXiv MCP server. Do a focused literature search on: \"{$topic}\".\n\n"
        . "Follow this sequence:\n"
        . "  1. If the topic maps to a specific subfield, call `list_arxiv_categories` with a filter "
        . "to find the right category codes. Otherwise skip.\n"
        . "  2. Call `search_arxiv` with a targeted query (combine `cat:` with `ti:` or `abs:` "
        . "phrases; quote multi-word terms). Use {$sortHint}.\n"
        . "  3. For the most promising 2-3 results, call `find_similar_papers` to broaden coverage.\n"
        . "  4. If the user wants details, call `fetch_paper_html` on the top paper.\n"
        . "  5. Summarise: for each paper, give title, authors, arXiv ID, one-sentence contribution, "
        . "and the abstract URL. Group by theme if there are more than five papers.\n\n"
        . "Do not invent citations. Every paper you mention must come from a tool result.";

    return [
        'description' => "Literature search workflow for: {$topic}",
        'messages'    => [[
            'role'    => 'user',
            'content' => ['type' => 'text', 'text' => $text],
        ]],
    ];
}

// ---------------------------------------------------------------------------
// arXiv HTTP + Atom parsing
// ---------------------------------------------------------------------------

function arxiv_request(array $params): string
{
    $url = ARXIV_API_BASE . '?' . http_build_query($params);
    [$body, $code] = http_get($url, ['Accept: application/atom+xml']);
    if ($body === '') {
        throw new RuntimeException("arXiv API returned empty body (HTTP {$code}).");
    }
    if ($code >= 400) {
        throw new RuntimeException("arXiv API returned HTTP {$code}.");
    }
    return $body;
}

function http_get(string $url, array $extraHeaders = []): array
{
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => true,
            CURLOPT_TIMEOUT        => 30,
            CURLOPT_USERAGENT      => 'arxiv-mcp/' . MCP_SERVER_VERSION,
            CURLOPT_HTTPHEADER     => $extraHeaders,
        ]);
        $body = curl_exec($ch);
        $err  = curl_error($ch);
        $code = (int)curl_getinfo($ch, CURLINFO_HTTP_CODE);
        curl_close($ch);
        if ($body === false) {
            throw new RuntimeException("HTTP request failed: {$err}");
        }
        return [(string)$body, $code];
    }

    $headerLines = "User-Agent: arxiv-mcp/" . MCP_SERVER_VERSION . "\r\n";
    foreach ($extraHeaders as $h) {
        $headerLines .= $h . "\r\n";
    }
    $ctx = stream_context_create([
        'http' => [
            'method'        => 'GET',
            'header'        => $headerLines,
            'timeout'       => 30,
            'ignore_errors' => true,
        ],
    ]);
    $body = @file_get_contents($url, false, $ctx);
    $code = 0;
    if (isset($http_response_header[0]) && preg_match('#HTTP/\S+\s+(\d+)#', $http_response_header[0], $m)) {
        $code = (int)$m[1];
    }
    if ($body === false) {
        throw new RuntimeException("HTTP request failed: {$url}");
    }
    return [(string)$body, $code];
}

function parse_feed(string $xml): array
{
    $prev = libxml_use_internal_errors(true);
    $doc  = simplexml_load_string($xml);
    libxml_use_internal_errors($prev);
    if ($doc === false) {
        throw new RuntimeException('Failed to parse arXiv Atom response.');
    }

    $nsArxiv      = 'http://arxiv.org/schemas/atom';
    $nsOpenSearch = 'http://a9.com/-/spec/opensearch/1.1/';
    $os           = $doc->children($nsOpenSearch);

    $result = [
        'total_results'  => (int)($os->totalResults ?? 0),
        'start_index'    => (int)($os->startIndex   ?? 0),
        'items_per_page' => (int)($os->itemsPerPage ?? 0),
        'papers'         => [],
    ];

    if (!isset($doc->entry)) {
        return $result;
    }
    foreach ($doc->entry as $entry) {
        $result['papers'][] = entry_to_array($entry, $nsArxiv);
    }
    return $result;
}

function entry_to_array(SimpleXMLElement $e, string $nsArxiv): array
{
    $arxivChildren = $e->children($nsArxiv);

    $id      = trim((string)$e->id);
    $arxivId = preg_replace('#^https?://arxiv\.org/abs/#', '', $id);

    $authors = [];
    foreach ($e->author as $a) {
        $authors[] = trim((string)$a->name);
    }

    $primary = '';
    if (isset($arxivChildren->primary_category)) {
        $attrs = $arxivChildren->primary_category->attributes();
        if (isset($attrs['term'])) {
            $primary = (string)$attrs['term'];
        }
    }

    $cats = [];
    foreach ($e->category as $c) {
        $attrs = $c->attributes();
        if (isset($attrs['term'])) {
            $cats[] = (string)$attrs['term'];
        }
    }

    $absUrl = '';
    $pdfUrl = '';
    foreach ($e->link as $l) {
        $attrs     = $l->attributes();
        $rel       = (string)($attrs['rel']   ?? '');
        $linkTitle = (string)($attrs['title'] ?? '');
        $href      = (string)($attrs['href']  ?? '');
        if ($linkTitle === 'pdf') {
            $pdfUrl = $href;
        } elseif ($rel === 'alternate') {
            $absUrl = $href;
        }
    }

    return [
        'arxiv_id'         => $arxivId,
        'title'            => collapse_whitespace((string)$e->title),
        'authors'          => $authors,
        'primary_category' => $primary,
        'categories'       => array_values(array_unique($cats)),
        'published'        => (string)$e->published,
        'updated'          => (string)$e->updated,
        'summary'          => collapse_whitespace((string)$e->summary),
        'comment'          => trim((string)($arxivChildren->comment     ?? '')),
        'journal_ref'      => trim((string)($arxivChildren->journal_ref ?? '')),
        'doi'              => trim((string)($arxivChildren->doi         ?? '')),
        'abstract_url'     => $absUrl,
        'pdf_url'          => $pdfUrl,
    ];
}

// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function collapse_whitespace(string $s): string
{
    return trim((string)preg_replace('/\s+/', ' ', $s));
}

function html_to_text(string $html): string
{
    $html = preg_replace('#<(script|style|noscript|nav|footer|aside|header)\b[^>]*>.*?</\1>#si', '', $html);
    $html = preg_replace('#<br\s*/?>#i', "\n", $html);
    $html = preg_replace('#</(p|div|li|h[1-6]|tr|section|article)>#i', "\n\n", $html);
    $text = html_entity_decode(strip_tags($html), ENT_QUOTES | ENT_HTML5, 'UTF-8');
    $text = preg_replace("/[ \t]+/", ' ', $text);
    $text = preg_replace("/\n[ \t]+/", "\n", $text);
    $text = preg_replace("/\n{3,}/", "\n\n", $text);
    return trim($text);
}

function title_keywords(string $title, int $max): array
{
    $stop = [
        'a','an','the','of','for','and','or','to','in','on','with','from','by','at',
        'is','are','be','as','via','using','based','toward','towards','into',
        'we','our','this','that','these','those','new','novel','effective','efficient',
    ];
    $title = strtolower($title);
    $title = preg_replace('/[^a-z0-9\s-]+/', ' ', $title);
    $parts = preg_split('/\s+/', $title, -1, PREG_SPLIT_NO_EMPTY);
    $kw = [];
    foreach ($parts as $p) {
        if (strlen($p) < 4) { continue; }
        if (in_array($p, $stop, true)) { continue; }
        if (!in_array($p, $kw, true)) { $kw[] = $p; }
        if (count($kw) >= $max) { break; }
    }
    return $kw;
}

function escape_query_term(string $term): string
{
    $t = preg_replace('/[^a-z0-9-]/i', '', $term);
    return $t === '' ? $term : $t;
}

function arxiv_categories(): array
{
    // Abridged from https://arxiv.org/category_taxonomy — the commonly useful codes.
    $rows = [
        ['cs.AI', 'Computer Science — Artificial Intelligence'],
        ['cs.AR', 'Computer Science — Hardware Architecture'],
        ['cs.CC', 'Computer Science — Computational Complexity'],
        ['cs.CE', 'Computer Science — Computational Engineering, Finance, and Science'],
        ['cs.CG', 'Computer Science — Computational Geometry'],
        ['cs.CL', 'Computer Science — Computation and Language (NLP)'],
        ['cs.CR', 'Computer Science — Cryptography and Security'],
        ['cs.CV', 'Computer Science — Computer Vision and Pattern Recognition'],
        ['cs.CY', 'Computer Science — Computers and Society'],
        ['cs.DB', 'Computer Science — Databases'],
        ['cs.DC', 'Computer Science — Distributed, Parallel, and Cluster Computing'],
        ['cs.DL', 'Computer Science — Digital Libraries'],
        ['cs.DM', 'Computer Science — Discrete Mathematics'],
        ['cs.DS', 'Computer Science — Data Structures and Algorithms'],
        ['cs.ET', 'Computer Science — Emerging Technologies'],
        ['cs.FL', 'Computer Science — Formal Languages and Automata Theory'],
        ['cs.GL', 'Computer Science — General Literature'],
        ['cs.GR', 'Computer Science — Graphics'],
        ['cs.GT', 'Computer Science — Computer Science and Game Theory'],
        ['cs.HC', 'Computer Science — Human-Computer Interaction'],
        ['cs.IR', 'Computer Science — Information Retrieval'],
        ['cs.IT', 'Computer Science — Information Theory'],
        ['cs.LG', 'Computer Science — Machine Learning'],
        ['cs.LO', 'Computer Science — Logic in Computer Science'],
        ['cs.MA', 'Computer Science — Multiagent Systems'],
        ['cs.MM', 'Computer Science — Multimedia'],
        ['cs.MS', 'Computer Science — Mathematical Software'],
        ['cs.NA', 'Computer Science — Numerical Analysis'],
        ['cs.NE', 'Computer Science — Neural and Evolutionary Computing'],
        ['cs.NI', 'Computer Science — Networking and Internet Architecture'],
        ['cs.OH', 'Computer Science — Other Computer Science'],
        ['cs.OS', 'Computer Science — Operating Systems'],
        ['cs.PF', 'Computer Science — Performance'],
        ['cs.PL', 'Computer Science — Programming Languages'],
        ['cs.RO', 'Computer Science — Robotics'],
        ['cs.SC', 'Computer Science — Symbolic Computation'],
        ['cs.SD', 'Computer Science — Sound'],
        ['cs.SE', 'Computer Science — Software Engineering'],
        ['cs.SI', 'Computer Science — Social and Information Networks'],
        ['cs.SY', 'Computer Science — Systems and Control'],
        ['math.AG', 'Mathematics — Algebraic Geometry'],
        ['math.AT', 'Mathematics — Algebraic Topology'],
        ['math.AP', 'Mathematics — Analysis of PDEs'],
        ['math.CA', 'Mathematics — Classical Analysis and ODEs'],
        ['math.CO', 'Mathematics — Combinatorics'],
        ['math.CT', 'Mathematics — Category Theory'],
        ['math.CV', 'Mathematics — Complex Variables'],
        ['math.DG', 'Mathematics — Differential Geometry'],
        ['math.DS', 'Mathematics — Dynamical Systems'],
        ['math.FA', 'Mathematics — Functional Analysis'],
        ['math.GM', 'Mathematics — General Mathematics'],
        ['math.GN', 'Mathematics — General Topology'],
        ['math.GR', 'Mathematics — Group Theory'],
        ['math.GT', 'Mathematics — Geometric Topology'],
        ['math.HO', 'Mathematics — History and Overview'],
        ['math.IT', 'Mathematics — Information Theory'],
        ['math.KT', 'Mathematics — K-Theory and Homology'],
        ['math.LO', 'Mathematics — Logic'],
        ['math.MG', 'Mathematics — Metric Geometry'],
        ['math.MP', 'Mathematics — Mathematical Physics'],
        ['math.NA', 'Mathematics — Numerical Analysis'],
        ['math.NT', 'Mathematics — Number Theory'],
        ['math.OA', 'Mathematics — Operator Algebras'],
        ['math.OC', 'Mathematics — Optimization and Control'],
        ['math.PR', 'Mathematics — Probability'],
        ['math.QA', 'Mathematics — Quantum Algebra'],
        ['math.RA', 'Mathematics — Rings and Algebras'],
        ['math.RT', 'Mathematics — Representation Theory'],
        ['math.SG', 'Mathematics — Symplectic Geometry'],
        ['math.SP', 'Mathematics — Spectral Theory'],
        ['math.ST', 'Mathematics — Statistics Theory'],
        ['stat.AP', 'Statistics — Applications'],
        ['stat.CO', 'Statistics — Computation'],
        ['stat.ME', 'Statistics — Methodology'],
        ['stat.ML', 'Statistics — Machine Learning'],
        ['stat.OT', 'Statistics — Other Statistics'],
        ['stat.TH', 'Statistics — Theory'],
        ['astro-ph.CO', 'Astrophysics — Cosmology and Nongalactic Astrophysics'],
        ['astro-ph.EP', 'Astrophysics — Earth and Planetary Astrophysics'],
        ['astro-ph.GA', 'Astrophysics — Astrophysics of Galaxies'],
        ['astro-ph.HE', 'Astrophysics — High Energy Astrophysical Phenomena'],
        ['astro-ph.IM', 'Astrophysics — Instrumentation and Methods for Astrophysics'],
        ['astro-ph.SR', 'Astrophysics — Solar and Stellar Astrophysics'],
        ['cond-mat.dis-nn', 'Condensed Matter — Disordered Systems and Neural Networks'],
        ['cond-mat.mes-hall', 'Condensed Matter — Mesoscale and Nanoscale Physics'],
        ['cond-mat.mtrl-sci', 'Condensed Matter — Materials Science'],
        ['cond-mat.other', 'Condensed Matter — Other'],
        ['cond-mat.quant-gas', 'Condensed Matter — Quantum Gases'],
        ['cond-mat.soft', 'Condensed Matter — Soft Condensed Matter'],
        ['cond-mat.stat-mech', 'Condensed Matter — Statistical Mechanics'],
        ['cond-mat.str-el', 'Condensed Matter — Strongly Correlated Electrons'],
        ['cond-mat.supr-con', 'Condensed Matter — Superconductivity'],
        ['gr-qc', 'General Relativity and Quantum Cosmology'],
        ['hep-ex', 'High Energy Physics — Experiment'],
        ['hep-lat', 'High Energy Physics — Lattice'],
        ['hep-ph', 'High Energy Physics — Phenomenology'],
        ['hep-th', 'High Energy Physics — Theory'],
        ['math-ph', 'Mathematical Physics'],
        ['nlin.AO', 'Nonlinear Sciences — Adaptation and Self-Organizing Systems'],
        ['nlin.CD', 'Nonlinear Sciences — Chaotic Dynamics'],
        ['nlin.CG', 'Nonlinear Sciences — Cellular Automata and Lattice Gases'],
        ['nlin.PS', 'Nonlinear Sciences — Pattern Formation and Solitons'],
        ['nlin.SI', 'Nonlinear Sciences — Exactly Solvable and Integrable Systems'],
        ['nucl-ex', 'Nuclear Experiment'],
        ['nucl-th', 'Nuclear Theory'],
        ['physics.acc-ph', 'Physics — Accelerator Physics'],
        ['physics.ao-ph', 'Physics — Atmospheric and Oceanic Physics'],
        ['physics.app-ph', 'Physics — Applied Physics'],
        ['physics.atm-clus', 'Physics — Atomic and Molecular Clusters'],
        ['physics.atom-ph', 'Physics — Atomic Physics'],
        ['physics.bio-ph', 'Physics — Biological Physics'],
        ['physics.chem-ph', 'Physics — Chemical Physics'],
        ['physics.class-ph', 'Physics — Classical Physics'],
        ['physics.comp-ph', 'Physics — Computational Physics'],
        ['physics.data-an', 'Physics — Data Analysis, Statistics and Probability'],
        ['physics.ed-ph', 'Physics — Physics Education'],
        ['physics.flu-dyn', 'Physics — Fluid Dynamics'],
        ['physics.gen-ph', 'Physics — General Physics'],
        ['physics.geo-ph', 'Physics — Geophysics'],
        ['physics.hist-ph', 'Physics — History and Philosophy of Physics'],
        ['physics.ins-det', 'Physics — Instrumentation and Detectors'],
        ['physics.med-ph', 'Physics — Medical Physics'],
        ['physics.optics', 'Physics — Optics'],
        ['physics.plasm-ph', 'Physics — Plasma Physics'],
        ['physics.pop-ph', 'Physics — Popular Physics'],
        ['physics.soc-ph', 'Physics — Physics and Society'],
        ['physics.space-ph', 'Physics — Space Physics'],
        ['quant-ph', 'Quantum Physics'],
        ['q-bio.BM', 'Quantitative Biology — Biomolecules'],
        ['q-bio.CB', 'Quantitative Biology — Cell Behavior'],
        ['q-bio.GN', 'Quantitative Biology — Genomics'],
        ['q-bio.MN', 'Quantitative Biology — Molecular Networks'],
        ['q-bio.NC', 'Quantitative Biology — Neurons and Cognition'],
        ['q-bio.OT', 'Quantitative Biology — Other'],
        ['q-bio.PE', 'Quantitative Biology — Populations and Evolution'],
        ['q-bio.QM', 'Quantitative Biology — Quantitative Methods'],
        ['q-bio.SC', 'Quantitative Biology — Subcellular Processes'],
        ['q-bio.TO', 'Quantitative Biology — Tissues and Organs'],
        ['q-fin.CP', 'Quantitative Finance — Computational Finance'],
        ['q-fin.EC', 'Quantitative Finance — Economics'],
        ['q-fin.GN', 'Quantitative Finance — General Finance'],
        ['q-fin.MF', 'Quantitative Finance — Mathematical Finance'],
        ['q-fin.PM', 'Quantitative Finance — Portfolio Management'],
        ['q-fin.PR', 'Quantitative Finance — Pricing of Securities'],
        ['q-fin.RM', 'Quantitative Finance — Risk Management'],
        ['q-fin.ST', 'Quantitative Finance — Statistical Finance'],
        ['q-fin.TR', 'Quantitative Finance — Trading and Market Microstructure'],
        ['econ.EM', 'Economics — Econometrics'],
        ['econ.GN', 'Economics — General Economics'],
        ['econ.TH', 'Economics — Theoretical Economics'],
        ['eess.AS', 'Electrical Engineering — Audio and Speech Processing'],
        ['eess.IV', 'Electrical Engineering — Image and Video Processing'],
        ['eess.SP', 'Electrical Engineering — Signal Processing'],
        ['eess.SY', 'Electrical Engineering — Systems and Control'],
    ];
    $out = [];
    foreach ($rows as [$code, $name]) {
        $out[] = ['code' => $code, 'name' => $name];
    }
    return $out;
}
