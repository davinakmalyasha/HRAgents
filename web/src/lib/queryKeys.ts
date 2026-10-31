/**
 * Query-key prefixes shared across layers.
 *
 * The home reads three queues under the `attention` prefix, and the global
 * mutation defaults invalidate that prefix after every successful write. A
 * literal in both places would drift silently — an invalidation that matches
 * nothing looks exactly like one that worked.
 */
export const ATTENTION_QUERY_KEY = ['attention'] as const
