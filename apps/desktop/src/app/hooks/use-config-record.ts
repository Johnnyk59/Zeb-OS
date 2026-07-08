import { useQuery } from '@tanstack/react-query'

import { getZebConfigRecord } from '@/zeb'
import { queryClient, writeCache } from '@/lib/query-client'
import type { ZebConfigRecord } from '@/types/zeb'

// One shared cache for the whole profile config record (`GET /api/config`).
// Every settings surface (MCP, model, config) reads and writes through this key
// so a save in one shows in the others, and revisiting a tab paints the cache
// instead of blanking on a fresh fetch.
//
// Distinct from session/hooks/use-zeb-config.ts, which is side-effecting —
// it pushes personality/cwd/voice/… into the session stores for live chat.
export const ZEB_CONFIG_KEY = ['zeb-config-record'] as const

// staleTime 0 → serve cache instantly, background-revalidate on every mount.
export const useZebConfigRecord = () =>
  useQuery({ queryKey: ZEB_CONFIG_KEY, queryFn: getZebConfigRecord, staleTime: 0 })

export const setZebConfigCache = writeCache<ZebConfigRecord>(ZEB_CONFIG_KEY)

export const invalidateZebConfig = () => queryClient.invalidateQueries({ queryKey: ZEB_CONFIG_KEY })
