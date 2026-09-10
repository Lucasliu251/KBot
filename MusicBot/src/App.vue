<script setup lang="ts">
import {
  Activity,
  ArrowDown,
  ArrowUp,
  Check,
  ChevronDown,
  CirclePlus,
  Clock3,
  Cpu,
  GripVertical,
  Headphones,
  KeyRound,
  Languages,
  ListMusic,
  LogIn,
  LoaderCircle,
  Megaphone,
  MemoryStick,
  Minus,
  Music2,
  Network,
  LogOut,
  Pause,
  Play,
  Plus,
  Radio,
  QrCode,
  RefreshCw,
  Repeat1,
  Repeat2,
  RotateCcw,
  Search,
  Server,
  Settings,
  ShieldCheck,
  Shuffle,
  SkipBack,
  SkipForward,
  Terminal,
  Trash2,
  UsersRound,
  Volume2,
  Wifi,
  WifiOff,
  X,
} from '@lucide/vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { assetUrl, getJson, postAdminJson, postJson } from './api'
import UserAvatar from './UserAvatar.vue'

type PlayMode = 'order' | 'repeat-one' | 'shuffle'
type MusicProvider = 'netease' | 'bilibili' | 'qqmusic'
type Track = {
  id: string
  name: string
  artist: string
  album?: string
  cover?: string
  duration: number
  position?: number
  playing?: boolean
  queue_index?: number
  provider?: MusicProvider
}
type Guild = { id: string; name: string }
type Channel = { id: string; name: string }
type SearchTrack = {
  id: number | string
  name: string
  ar?: Array<{ name: string }>
  al?: { name?: string; picUrl?: string }
  dt?: number
  provider?: MusicProvider
  playable?: boolean
  restriction?: string
  bvid?: string
  page?: number
  part_count?: number
  webpage_url?: string
}
type HotSearch = {
  keyword: string
  score?: number
  content?: string
  icon_type?: number
}
type SearchMode = 'discover' | 'search'
type DiscoveryView = 'community' | 'platform'
type RecommendationSort = 'latest' | 'popular'
type RecommendationUser = {
  user_id: string
  username: string
  nickname: string
  avatar: string
  note?: string
  updated_at: number
}
type RecommendationTrack = Track & {
  recommendation_count: number
  latest_at: number
  viewer_recommended: boolean
  note?: string
  recommenders: RecommendationUser[]
}
type RecommendationAuthUser = {
  id: string
  username: string
  nickname: string
  avatar: string
}
type LyricLine = { time: number; text: string; translation?: string }
type MusicAuthStatus = {
  available: boolean
  authenticated: boolean
  account?: string
  expired?: boolean
  error?: string
  source?: 'environment' | 'local' | 'none'
  login_source?: 'environment' | 'local'
  cookie_count?: number
  updated_at?: number
  engine?: {
    mode: 'local' | 'external'
    managed: boolean
    reachable: boolean
    endpoint: string
    version?: string
    error?: string
  }
}
type SystemStatusResponse = {
  system: {
    cpu_percent: number
    memory: { total: number; available: number; percent: number; used: number }
    network: { bytes_sent: number; bytes_recv: number; packets_sent: number; packets_recv: number }
  }
  process: { pid: number; memory_rss: number; cpu_percent: number; uptime: number }
  playback: { active_guilds: number; playing_songs: number; queued_songs: number }
  timestamp: number
}
type MonitorLog = {
  timestamp: string
  level: 'error' | 'warning' | 'info' | 'debug'
  message: string
  raw: string
}
type BotLatency = {
  kookRestMs: number | null
  voiceGatewayMs: number | null
  consoleMs: number
  measuredAt: number
  kookError?: string
  transport?: {
    actual_fps: number
    target_fps: number
    late_frames: number
    resyncs: number
    max_lateness_ms: number
  } | null
}

const FALLBACK_COVER = assetUrl('album-placeholder.png')
const PROVIDER_META = {
  netease: { label: 'NETEASE', name: '网易云', icon: assetUrl('netease.png') },
  bilibili: { label: 'BILIBILI', name: 'Bilibili', icon: assetUrl('bilibili.svg') },
  qqmusic: { label: 'QQ MUSIC', name: 'QQ音乐', icon: assetUrl('QQ.png') },
} as const
const MODE_META = {
  order: { label: '顺序播放', icon: Repeat2 },
  'repeat-one': { label: '单曲循环', icon: Repeat1 },
  shuffle: { label: '随机播放', icon: Shuffle },
} as const

const tracks = ref<Track[]>([])
const lyrics = ref<LyricLine[]>([])
const lyricState = ref<'loading' | 'ready' | 'empty'>('loading')
const lyricsTrackId = ref('')
const position = ref(0)
const volume = ref(40)
const isPlaying = ref(false)
const playMode = ref<PlayMode>('order')
const lyricOffset = ref(0)
const showTranslation = ref(false)
const syncOpen = ref(false)
const searchOpen = ref(false)
const settingsOpen = ref(false)
const transitionSettings = ref({ enabled: true, seconds: 4 })
const transitionLoading = ref(false)
const transitionSaving = ref(false)
const transitionError = ref('')
const musicSource = ref<MusicProvider>('netease')
const channelSwitcherOpen = ref(false)
const searchMode = ref<SearchMode>('discover')
const discoveryView = ref<DiscoveryView>('community')
const recommendationSort = ref<RecommendationSort>('popular')
const communityAutoFallback = ref(false)
const recommendationSortAutoFallback = ref(false)
const recommendations = ref<RecommendationTrack[]>([])
const recommendationLoading = ref(false)
const recommendationError = ref('')
const recommendationTotal = ref(0)
const recommendationAuthUser = ref<RecommendationAuthUser | null>(null)
const recommendationAuthConfigured = ref(false)
const recommendationAuthLoading = ref(false)
const recommendationBusyKey = ref('')
const recommendedKeys = ref<Set<string>>(new Set())
const recentlyAddedKeys = ref<Set<string>>(new Set())
const addingSongKey = ref('')
const searching = ref(false)
const discovering = ref(false)
const loadingMoreSearch = ref(false)
const searchHasMore = ref(false)
const activeSearchKeyword = ref('')
const query = ref('')
const searchResults = ref<SearchTrack[]>([])
const hotSearches = ref<HotSearch[]>([])
const discoveryError = ref('')
const playlistInput = ref('')
const neteaseAuth = ref<MusicAuthStatus>({ available: true, authenticated: false, source: 'none' })
const qqAuth = ref<MusicAuthStatus>({ available: true, authenticated: false })
const qqAuthLoading = ref(false)
const qqLoginQr = ref('')
const qqLoginIdentifier = ref('')
const qqLoginType = ref<'qq' | 'wx'>('qq')
const qqLoginState = ref('')
const neteaseAuthLoading = ref(false)
const neteaseLoginQr = ref('')
const neteaseLoginKey = ref('')
const neteaseLoginState = ref('')
const neteaseCookieInput = ref('')
const settingsToken = ref(sessionStorage.getItem('musicSettingsToken') ?? '')
const settingsUnlocked = ref(Boolean(settingsToken.value))
const settingsUnlocking = ref(false)
const settingsError = ref('')
const botLatency = ref<BotLatency | null>(null)
const botLatencyLoading = ref(false)
const botLatencyError = ref('')
const systemStatus = ref<SystemStatusResponse | null>(null)
const systemStatusLoading = ref(false)
const systemStatusError = ref('')
const networkRate = ref({ download: 0, upload: 0, ready: false })
const terminalLogs = ref<MonitorLog[]>([])
const terminalLogsLoading = ref(false)
const terminalLogsError = ref('')
const guilds = ref<Guild[]>([])
const channels = ref<Channel[]>([])
const savedGuildId = localStorage.getItem('currentGuildId') ?? ''
const savedChannelId = localStorage.getItem('currentChannelId') ?? ''
const initialChannelId = window.INITIAL_CHANNEL_ID || window.location.pathname.match(/(?:\/Music)?\/(\d+)\/?$/)?.[1] || ''
const guildId = ref(savedGuildId)
const channelId = ref(initialChannelId || savedChannelId)
const resolvedChannelName = ref('')
const connectedChannelId = ref('')
const connected = ref(false)
const setupError = ref('')
const bootstrapping = ref(true)
const playbackControlPending = ref(false)
const preparingPlayback = ref(false)
const voiceControlPending = ref(false)
const clearingQueue = ref(false)
const refreshing = ref(false)
const toast = ref('')
const seeking = ref(false)
const dragIndex = ref<number | null>(null)
const dragTargetIndex = ref<number | null>(null)
const searchInput = ref<HTMLInputElement | null>(null)
const searchResultsBox = ref<HTMLElement | null>(null)
const terminalLogBox = ref<HTMLElement | null>(null)
let pollTimer: number | undefined
let progressTimer: number | undefined
let toastTimer: number | undefined
let volumeTimer: number | undefined
let qqLoginTimer: number | undefined
let neteaseLoginTimer: number | undefined
let systemMonitorTimer: number | undefined
let terminalLogTimer: number | undefined
let searchInputTimer: number | undefined
let searchAutoFillRunning = false
let lastNetworkSample: { sent: number; received: number; sampledAt: number } | null = null
let lastLatencyCheckedAt = 0
let playlistRequestVersion = 0
let lyricRequestVersion = 0
let searchRequestVersion = 0
let volumeRequestVersion = 0
let lyricTargetId = ''
let playbackAnchorPosition = position.value
let playbackAnchorTime = performance.now()
const lyricCache = new Map<string, LyricLine[]>()
const addedIconTimers = new Map<string, number>()

const current = computed(() => tracks.value.find((track) => track.playing))
const queuedTracks = computed(() => tracks.value.filter((track) => !track.playing))
const playlistTrackKeys = computed(() => new Set(
  tracks.value.map((track) => `${track.provider || 'netease'}:${String(track.id)}`),
))
const duration = computed(() => current.value?.duration || 0)
const progress = computed(() => duration.value > 0 ? Math.min(100, (position.value / duration.value) * 100) : 0)
const channelName = computed(() => channels.value.find((channel) => channel.id === channelId.value)?.name || resolvedChannelName.value || '选择语音频道')
const guildName = computed(() => guilds.value.find((guild) => guild.id === guildId.value)?.name || 'KOOK 服务器')
const modeIcon = computed(() => MODE_META[playMode.value].icon)
const rangeProgressStyle = computed(() => ({ '--range-progress': `${progress.value}%` }))
const volumeProgressStyle = computed(() => ({ '--range-progress': `${volume.value}%` }))
const currentProvider = computed<MusicProvider>(() => current.value?.provider || 'netease')
const currentProviderLabel = computed(() => PROVIDER_META[currentProvider.value].label)
const selectedProviderName = computed(() => PROVIDER_META[musicSource.value].name)
const selectedProviderIcon = computed(() => PROVIDER_META[musicSource.value].icon)
const searchPlaceholder = computed(() => musicSource.value === 'bilibili'
  ? '搜索B站视频，或粘贴 BV / AV / bilibili 链接'
  : `在${selectedProviderName.value}搜索歌曲、艺术家或专辑`)
const neteaseLocalEngineReady = computed(() => (
  neteaseAuth.value.engine?.mode === 'local'
  && neteaseAuth.value.engine?.managed === true
  && neteaseAuth.value.engine?.reachable === true
))

function providerIcon(provider: MusicProvider) {
  return PROVIDER_META[provider].icon
}

function recommendationKey(track: Pick<Track, 'id' | 'provider'> | SearchTrack) {
  return `${track.provider || 'netease'}:${String(track.id)}`
}

function searchTrackKey(track: SearchTrack) {
  return `${track.provider || musicSource.value}:${String(track.id)}`
}

function isSongInPlaylist(track: SearchTrack) {
  const key = searchTrackKey(track)
  return playlistTrackKeys.value.has(key) || recentlyAddedKeys.value.has(key)
}

function markSongAdded(key: string) {
  const keys = new Set(recentlyAddedKeys.value)
  keys.add(key)
  recentlyAddedKeys.value = keys
  const previousTimer = addedIconTimers.get(key)
  if (previousTimer) window.clearTimeout(previousTimer)
  addedIconTimers.set(key, window.setTimeout(() => {
    const nextKeys = new Set(recentlyAddedKeys.value)
    nextKeys.delete(key)
    recentlyAddedKeys.value = nextKeys
    addedIconTimers.delete(key)
  }, 5000))
}

function coverReferrerPolicy(provider?: MusicProvider) {
  return provider === 'bilibili' ? 'no-referrer' : undefined
}

function recommendationPayload(track: Track | SearchTrack | RecommendationTrack) {
  const isSearchTrack = 'ar' in track || 'al' in track || 'dt' in track
  const searchTrack = track as SearchTrack
  const playerTrack = track as Track
  return {
    id: String(track.id),
    provider: isSearchTrack ? searchTrack.provider || musicSource.value : playerTrack.provider || 'netease',
    name: track.name,
    artist: isSearchTrack
      ? searchTrack.ar?.map((artist) => artist.name).join(' / ') || ''
      : playerTrack.artist || '',
    album: isSearchTrack ? searchTrack.al?.name || '' : playerTrack.album || '',
    cover: isSearchTrack ? searchTrack.al?.picUrl || '' : playerTrack.cover || '',
    duration: isSearchTrack ? Number(searchTrack.dt || 0) / 1000 : Number(playerTrack.duration || 0),
  }
}

function recommendationAsSearchTrack(track: RecommendationTrack): SearchTrack {
  return {
    id: track.id,
    provider: track.provider,
    name: track.name,
    ar: [{ name: track.artist || (track.provider === 'bilibili' ? '未知UP主' : '未知艺术家') }],
    al: { name: track.album || '', picUrl: track.cover || '' },
    dt: Number(track.duration || 0) * 1000,
    playable: true,
  }
}

function isRecommended(track: Pick<Track, 'id' | 'provider'> | SearchTrack) {
  return recommendedKeys.value.has(recommendationKey(track))
}

function formatRelativeTime(timestamp = 0) {
  const elapsed = Math.max(0, Math.floor(Date.now() / 1000 - timestamp))
  if (elapsed < 60) return '刚刚'
  if (elapsed < 3600) return `${Math.floor(elapsed / 60)} 分钟前`
  if (elapsed < 86400) return `${Math.floor(elapsed / 3600)} 小时前`
  if (elapsed < 604800) return `${Math.floor(elapsed / 86400)} 天前`
  return new Date(timestamp * 1000).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
}

function formatTime(seconds = 0) {
  if (!Number.isFinite(seconds) || seconds < 0) return '00:00'
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`
}

function formatBytes(bytes = 0) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / (1024 ** unitIndex)
  return `${value >= 10 || unitIndex === 0 ? value.toFixed(0) : value.toFixed(1)} ${units[unitIndex]}`
}

function formatNetworkRate(bytesPerSecond = 0) {
  return `${formatBytes(bytesPerSecond)}/s`
}

function formatUptime(seconds = 0) {
  if (!Number.isFinite(seconds) || seconds < 0) return '—'
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (days > 0) return `${days}天 ${hours}小时`
  if (hours > 0) return `${hours}小时 ${minutes}分钟`
  return `${minutes}分钟`
}

const latencyQuality = computed(() => {
  if (!botLatency.value) return { label: '等待探测', className: '' }
  const voiceMs = botLatency.value.voiceGatewayMs
  if (voiceMs !== null) {
    if (voiceMs < 30) return { label: '语音优秀', className: 'is-good' }
    if (voiceMs < 80) return { label: '语音正常', className: 'is-normal' }
    return { label: '语音偏高', className: 'is-slow' }
  }
  const restMs = botLatency.value.kookRestMs
  if (restMs !== null && restMs < 150) return { label: 'API 正常', className: 'is-good' }
  if (restMs !== null && restMs < 300) return { label: 'API 偏慢', className: 'is-normal' }
  return { label: '偏高', className: 'is-slow' }
})

async function measureConsoleLatency() {
  const samples: number[] = []
  for (let index = 0; index < 3; index += 1) {
    const startedAt = performance.now()
    await getJson(`/api/network/ping?sample=${Date.now()}-${index}`)
    samples.push(performance.now() - startedAt)
  }
  samples.sort((left, right) => left - right)
  return Math.round(samples[Math.floor(samples.length / 2)] || 0)
}

async function loadBotLatency(force = false) {
  const now = Date.now()
  if (botLatencyLoading.value || (!force && now - lastLatencyCheckedAt < 10_000)) return
  botLatencyLoading.value = true
  botLatencyError.value = ''
  try {
    const [consoleMs, data] = await Promise.all([
      measureConsoleLatency(),
      getJson<{
        online: boolean
        kook_rest_ms: number | null
        kook_error?: string
        voice_gateway_ms: number | null
        transport?: BotLatency['transport']
        measured_at: number
      }>(`/api/network/latency?guild_id=${encodeURIComponent(guildId.value)}`),
    ])
    botLatency.value = {
      kookRestMs: data.kook_rest_ms,
      voiceGatewayMs: data.voice_gateway_ms,
      consoleMs,
      measuredAt: data.measured_at,
      kookError: data.kook_error,
      transport: data.transport,
    }
    lastLatencyCheckedAt = Date.now()
  } catch (error) {
    botLatencyError.value = error instanceof Error ? error.message : '延迟探测失败'
    lastLatencyCheckedAt = Date.now()
  } finally {
    botLatencyLoading.value = false
  }
}

async function loadSystemStatus() {
  if (systemStatusLoading.value) return
  systemStatusLoading.value = true
  systemStatusError.value = ''
  try {
    const data = await getJson<SystemStatusResponse>('/api/system/status')
    const sampledAt = performance.now()
    if (lastNetworkSample) {
      const elapsedSeconds = Math.max((sampledAt - lastNetworkSample.sampledAt) / 1000, 0.001)
      networkRate.value = {
        download: Math.max(0, (data.system.network.bytes_recv - lastNetworkSample.received) / elapsedSeconds),
        upload: Math.max(0, (data.system.network.bytes_sent - lastNetworkSample.sent) / elapsedSeconds),
        ready: true,
      }
    }
    lastNetworkSample = {
      sent: data.system.network.bytes_sent,
      received: data.system.network.bytes_recv,
      sampledAt,
    }
    systemStatus.value = data
  } catch (error) {
    systemStatusError.value = error instanceof Error ? error.message : '无法读取服务器状态'
  } finally {
    systemStatusLoading.value = false
  }
}

async function loadTerminalLogs() {
  if (terminalLogsLoading.value) return
  terminalLogsLoading.value = true
  terminalLogsError.value = ''
  const box = terminalLogBox.value
  const stickToBottom = !box || box.scrollHeight - box.scrollTop - box.clientHeight < 36
  try {
    const data = await getJson<{ logs: MonitorLog[] }>('/api/logs?type=debug&lines=120')
    terminalLogs.value = data.logs ?? []
    if (stickToBottom) {
      await nextTick()
      if (terminalLogBox.value) terminalLogBox.value.scrollTop = terminalLogBox.value.scrollHeight
    }
  } catch (error) {
    terminalLogsError.value = error instanceof Error ? error.message : '无法读取服务日志'
  } finally {
    terminalLogsLoading.value = false
  }
}

function stopSettingsMonitor() {
  if (systemMonitorTimer) window.clearInterval(systemMonitorTimer)
  if (terminalLogTimer) window.clearInterval(terminalLogTimer)
  systemMonitorTimer = undefined
  terminalLogTimer = undefined
}

function startSettingsMonitor() {
  stopSettingsMonitor()
  lastNetworkSample = null
  networkRate.value = { download: 0, upload: 0, ready: false }
  void loadSystemStatus()
  void loadTerminalLogs()
  systemMonitorTimer = window.setInterval(() => { void loadSystemStatus() }, 5000)
  terminalLogTimer = window.setInterval(() => { void loadTerminalLogs() }, 3000)
}

function parseLyrics(raw = ''): LyricLine[] {
  return raw
    .split('\n')
    .flatMap((line) => {
      const tags = [...line.matchAll(/\[(\d{1,3}):(\d{2})(?:\.(\d{1,3}))?\]/g)]
      const text = line.replace(/\[[^\]]+\]/g, '').trim()
      if (!text) return []
      return tags.map((tag) => ({ time: Number(tag[1]) * 60 + Number(tag[2]) + Number(`0.${tag[3] ?? 0}`), text }))
    })
    .sort((a, b) => a.time - b.time)
}

function mergeTranslatedLyrics(raw = '', translatedRaw = ''): LyricLine[] {
  const originalLines = parseLyrics(raw)
  const translatedLines = parseLyrics(translatedRaw)
  if (!translatedLines.length) return originalLines

  let translatedIndex = 0
  return originalLines.map((line) => {
    while (
      translatedIndex + 1 < translatedLines.length
      && translatedLines[translatedIndex + 1].time <= line.time
    ) translatedIndex += 1

    const candidates = [
      translatedLines[translatedIndex - 1],
      translatedLines[translatedIndex],
      translatedLines[translatedIndex + 1],
    ].filter((item): item is LyricLine => Boolean(item))
    const nearest = candidates.sort(
      (left, right) => Math.abs(left.time - line.time) - Math.abs(right.time - line.time),
    )[0]
    const translation = nearest && Math.abs(nearest.time - line.time) <= 0.75
      ? nearest.text.trim()
      : ''
    return {
      ...line,
      translation: translation && translation !== line.text.trim() ? translation : undefined,
    }
  })
}

function notify(message: string) {
  toast.value = message
  if (toastTimer) window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { toast.value = '' }, 2400)
}

async function loadRecommendationAuth() {
  recommendationAuthLoading.value = true
  try {
    const data = await getJson<{
      configured: boolean
      authenticated: boolean
      user?: RecommendationAuthUser
    }>('/api/auth/kook/status')
    recommendationAuthConfigured.value = Boolean(data.configured)
    recommendationAuthUser.value = data.authenticated && data.user ? data.user : null
  } catch {
    recommendationAuthConfigured.value = false
    recommendationAuthUser.value = null
  } finally {
    recommendationAuthLoading.value = false
  }
}

function oauthReturnPath() {
  const url = new URL(window.location.href)
  url.searchParams.delete('oauth')
  url.searchParams.delete('message')
  return `${url.pathname}${url.search}`
}

async function beginRecommendationLogin(track?: ReturnType<typeof recommendationPayload>) {
  if (!recommendationAuthConfigured.value) {
    notify('推荐登录尚未配置，请联系管理员配置 KOOK OAuth')
    return
  }
  if (track && guildId.value) {
    sessionStorage.setItem('pendingMusicRecommendation', JSON.stringify({ guild_id: guildId.value, track }))
  }
  recommendationAuthLoading.value = true
  try {
    const returnTo = oauthReturnPath()
    const data = await getJson<{ authorization_url: string }>(`/api/auth/kook/url?return_to=${encodeURIComponent(returnTo)}`)
    window.location.assign(data.authorization_url)
  } catch (error) {
    recommendationAuthLoading.value = false
    notify(error instanceof Error ? error.message : '无法打开 KOOK 登录')
  }
}

async function logoutRecommendationUser() {
  try {
    await postJson('/api/auth/kook/logout', {})
    recommendationAuthUser.value = null
    recommendedKeys.value = new Set()
    await loadRecommendationBoard()
    notify('已退出推荐身份')
  } catch (error) {
    notify(error instanceof Error ? error.message : '退出失败')
  }
}

async function loadRecommendationBoard() {
  if (!guildId.value) {
    recommendations.value = []
    recommendationTotal.value = 0
    return
  }
  recommendationLoading.value = true
  recommendationError.value = ''
  try {
    const fetchBoard = (sort: RecommendationSort) => getJson<{
      items: RecommendationTrack[]
      total: number
    }>(`/api/recommendations?guild_id=${encodeURIComponent(guildId.value)}&sort=${sort}&limit=50&offset=0`)

    let effectiveSort = recommendationSort.value
    let data = await fetchBoard(effectiveSort)
    let items = data.items ?? []
    const allCountsEqual = () => (
      items.length > 1
      && items.every((track) => track.recommendation_count === items[0].recommendation_count)
    )

    if (effectiveSort === 'popular' && allCountsEqual()) {
      effectiveSort = 'latest'
      recommendationSortAutoFallback.value = true
      data = await fetchBoard(effectiveSort)
      items = data.items ?? []
    } else if (effectiveSort === 'latest' && recommendationSortAutoFallback.value && !allCountsEqual()) {
      effectiveSort = 'popular'
      recommendationSortAutoFallback.value = false
      data = await fetchBoard(effectiveSort)
      items = data.items ?? []
    }

    recommendationSort.value = effectiveSort
    recommendations.value = items
    recommendationTotal.value = Number(data.total || 0)
    recommendedKeys.value = new Set(
      recommendations.value.filter((track) => track.viewer_recommended).map(recommendationKey),
    )
    if (recommendationTotal.value === 0 && discoveryView.value === 'community') {
      communityAutoFallback.value = true
      discoveryView.value = 'platform'
    } else if (recommendationTotal.value > 0 && communityAutoFallback.value) {
      communityAutoFallback.value = false
      discoveryView.value = 'community'
    }
  } catch (error) {
    recommendations.value = []
    recommendationTotal.value = 0
    recommendationError.value = error instanceof Error ? error.message : '大家推荐暂时不可用'
  } finally {
    recommendationLoading.value = false
  }
}

async function setRecommendation(
  track: Track | SearchTrack | RecommendationTrack | ReturnType<typeof recommendationPayload>,
  active: boolean,
) {
  const payload = 'artist' in track && 'cover' in track && !('ar' in track)
    ? {
        id: String(track.id),
        provider: track.provider || 'netease',
        name: track.name,
        artist: track.artist || '',
        album: track.album || '',
        cover: track.cover || '',
        duration: Number(track.duration || 0),
      }
    : recommendationPayload(track as Track | SearchTrack | RecommendationTrack)
  if (!guildId.value) {
    notify('请先选择 KOOK 服务器')
    return
  }
  if (!recommendationAuthUser.value) {
    if (active) await beginRecommendationLogin(payload)
    else notify('请先使用 KOOK 登录')
    return
  }
  const key = `${payload.provider}:${payload.id}`
  if (recommendationBusyKey.value === key) return
  recommendationBusyKey.value = key
  try {
    const data = await postJson<{ active: boolean; recommendation_count: number; key: string }>('/api/recommendations/toggle', {
      guild_id: guildId.value,
      track: payload,
      active,
    })
    const nextKeys = new Set(recommendedKeys.value)
    if (data.active) nextKeys.add(data.key)
    else nextKeys.delete(data.key)
    recommendedKeys.value = nextKeys
    notify(data.active ? `已向大家推荐《${payload.name}》` : `已撤回《${payload.name}》的推荐`)
    await loadRecommendationBoard()
  } catch (error) {
    notify(error instanceof Error ? error.message : '推荐操作失败')
  } finally {
    recommendationBusyKey.value = ''
  }
}

async function toggleRecommendation(track: Track | SearchTrack | RecommendationTrack) {
  await setRecommendation(track, !isRecommended(track))
}

async function selectDiscoveryView(view: DiscoveryView) {
  if (discoveryView.value === view) return
  communityAutoFallback.value = false
  discoveryView.value = view
  if (!query.value.trim()) await loadDiscovery()
}

async function selectRecommendationSort(sort: RecommendationSort) {
  if (recommendationSort.value === sort) return
  recommendationSortAutoFallback.value = false
  recommendationSort.value = sort
  await loadRecommendationBoard()
}

async function finishRecommendationLoginReturn() {
  const url = new URL(window.location.href)
  const outcome = url.searchParams.get('oauth')
  if (!outcome) return
  const message = url.searchParams.get('message') || ''
  url.searchParams.delete('oauth')
  url.searchParams.delete('message')
  window.history.replaceState(window.history.state, '', `${url.pathname}${url.search}${url.hash}`)
  if (outcome !== 'success') {
    sessionStorage.removeItem('pendingMusicRecommendation')
    notify(message || 'KOOK 登录没有完成')
    return
  }
  await loadRecommendationAuth()
  const rawPending = sessionStorage.getItem('pendingMusicRecommendation')
  sessionStorage.removeItem('pendingMusicRecommendation')
  if (rawPending && recommendationAuthUser.value) {
    try {
      const pending = JSON.parse(rawPending) as { guild_id: string; track: ReturnType<typeof recommendationPayload> }
      if (pending.guild_id === guildId.value) await setRecommendation(pending.track, true)
      else notify('登录成功，请在原服务器重新推荐歌曲')
    } catch {
      notify('KOOK 登录成功')
    }
  } else {
    notify('KOOK 登录成功')
  }
}

function coverFallback(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  if (!image.src.endsWith('/album-placeholder.png')) image.src = FALLBACK_COVER
}

function stopQQLoginPoll() {
  if (qqLoginTimer) window.clearInterval(qqLoginTimer)
  qqLoginTimer = undefined
}

function stopNeteaseLoginPoll() {
  if (neteaseLoginTimer) window.clearInterval(neteaseLoginTimer)
  neteaseLoginTimer = undefined
}

function settingsFailure(error: unknown, fallback: string) {
  const message = error instanceof Error ? error.message : fallback
  if (message.includes('HTTP 404')) return '登录接口未加载，请停止旧进程后重新运行 npm run dev'
  if (message.includes('管理密钥')) {
    settingsUnlocked.value = false
    sessionStorage.removeItem('musicSettingsToken')
    stopSettingsMonitor()
  }
  return message
}

async function loadMusicProviders() {
  qqAuthLoading.value = true
  neteaseAuthLoading.value = true
  try {
    const data = await getJson<{
      providers?: { netease?: MusicAuthStatus; qqmusic?: MusicAuthStatus }
    }>('/api/music/providers')
    neteaseAuth.value = data.providers?.netease ?? { available: true, authenticated: false, source: 'none' }
    qqAuth.value = data.providers?.qqmusic ?? { available: false, authenticated: false, error: 'QQ 音乐组件不可用' }
  } catch (error) {
    neteaseAuth.value = { available: false, authenticated: false, error: error instanceof Error ? error.message : '无法读取网易云状态' }
    qqAuth.value = { available: false, authenticated: false, error: error instanceof Error ? error.message : '无法读取 QQ 音乐状态' }
  } finally {
    qqAuthLoading.value = false
    neteaseAuthLoading.value = false
  }
}

async function loadTransitionSettings() {
  transitionLoading.value = true
  transitionError.value = ''
  try {
    const data = await getJson<{ transition: { enabled: boolean; seconds: number } }>('/api/music/transitions')
    transitionSettings.value = data.transition
  } catch (error) {
    transitionError.value = error instanceof Error ? error.message : '无法读取播放设置'
  } finally { transitionLoading.value = false }
}

async function saveTransitionSettings() {
  if (transitionSaving.value || transitionLoading.value) return
  transitionSaving.value = true
  transitionError.value = ''
  try {
    const data = await postAdminJson<{ transition: { enabled: boolean; seconds: number } }>('/api/music/transitions', transitionSettings.value, settingsToken.value)
    transitionSettings.value = data.transition
    notify('渐入渐出设置已保存，从下一首生效')
  } catch (error) {
    transitionError.value = settingsFailure(error, '保存失败')
  } finally { transitionSaving.value = false }
}

async function unlockMusicSettings() {
  const token = settingsToken.value.trim()
  if (!token || settingsUnlocking.value) return
  settingsUnlocking.value = true
  settingsError.value = ''
  try {
    await postAdminJson('/api/music/settings/unlock', {}, token)
    settingsToken.value = token
    sessionStorage.setItem('musicSettingsToken', token)
    settingsUnlocked.value = true
    await loadMusicProviders()
    if (settingsOpen.value) startSettingsMonitor()
    notify('音乐后台已解锁')
  } catch (error) {
    settingsUnlocked.value = false
    settingsError.value = settingsFailure(error, '无法解锁音乐后台')
  } finally {
    settingsUnlocking.value = false
  }
}

function lockMusicSettings() {
  stopQQLoginPoll()
  stopNeteaseLoginPoll()
  stopSettingsMonitor()
  settingsUnlocked.value = false
  settingsToken.value = ''
  settingsError.value = ''
  sessionStorage.removeItem('musicSettingsToken')
}

async function pollNeteaseLogin() {
  if (!neteaseLoginKey.value || !settingsUnlocked.value) return
  try {
    const data = await postAdminJson<{
      status: 'scan' | 'confirm' | 'done' | 'timeout' | 'error'
      message?: string
      auth?: MusicAuthStatus
    }>('/api/netease/login/status', { key: neteaseLoginKey.value }, settingsToken.value)
    if (data.status === 'done') {
      stopNeteaseLoginPoll()
      neteaseLoginState.value = '登录成功，Cookie 已持久化'
      if (data.auth) neteaseAuth.value = data.auth
      else await loadMusicProviders()
      neteaseLoginQr.value = ''
      neteaseLoginKey.value = ''
      notify('网易云音乐账号已连接')
    } else if (data.status === 'confirm') {
      neteaseLoginState.value = '已扫码，请在网易云 App 中确认'
    } else if (data.status === 'scan') {
      neteaseLoginState.value = '等待网易云音乐 App 扫码'
    } else {
      stopNeteaseLoginPoll()
      neteaseLoginState.value = data.status === 'timeout' ? '二维码已过期，请刷新' : (data.message || '登录状态异常')
    }
  } catch (error) {
    stopNeteaseLoginPoll()
    neteaseLoginState.value = settingsFailure(error, '网易云登录状态检查失败')
  }
}

async function startNeteaseLogin() {
  if (neteaseAuthLoading.value || !settingsUnlocked.value) return
  stopNeteaseLoginPoll()
  neteaseAuthLoading.value = true
  neteaseLoginQr.value = ''
  neteaseLoginKey.value = ''
  neteaseLoginState.value = '正在生成二维码'
  try {
    const data = await postAdminJson<{ key: string; image: string }>('/api/netease/login/qrcode', {}, settingsToken.value)
    neteaseLoginKey.value = data.key
    neteaseLoginQr.value = data.image
    neteaseLoginState.value = '请使用网易云音乐 App 扫码'
    neteaseLoginTimer = window.setInterval(() => { void pollNeteaseLogin() }, 1800)
  } catch (error) {
    neteaseLoginState.value = settingsFailure(error, '网易云二维码生成失败')
  } finally {
    neteaseAuthLoading.value = false
  }
}

async function saveNeteaseCookie() {
  const cookie = neteaseCookieInput.value.trim()
  if (!cookie || neteaseAuthLoading.value || !settingsUnlocked.value) return
  neteaseAuthLoading.value = true
  try {
    const data = await postAdminJson<{ auth?: MusicAuthStatus }>('/api/netease/cookie', { cookie }, settingsToken.value)
    if (data.auth) neteaseAuth.value = data.auth
    neteaseCookieInput.value = ''
    notify('网易云 Cookie 已安全保存')
  } catch (error) {
    notify(settingsFailure(error, '网易云 Cookie 保存失败'))
  } finally {
    neteaseAuthLoading.value = false
  }
}

async function logoutNetease() {
  try {
    await postAdminJson('/api/netease/logout', {}, settingsToken.value)
    stopNeteaseLoginPoll()
    neteaseLoginQr.value = ''
    neteaseLoginState.value = ''
    await loadMusicProviders()
    notify('已删除网易云本地登录信息')
  } catch (error) {
    notify(settingsFailure(error, '网易云登录信息删除失败'))
  }
}

async function pollQQLogin() {
  if (!qqLoginIdentifier.value) return
  try {
    const data = await postAdminJson<{
      status: 'scan' | 'conf' | 'done' | 'timeout' | 'refuse'
      auth?: MusicAuthStatus
    }>('/api/qqmusic/login/status', { identifier: qqLoginIdentifier.value, login_type: qqLoginType.value }, settingsToken.value)
    if (data.status === 'done') {
      stopQQLoginPoll()
      qqLoginState.value = '登录成功'
      if (data.auth) qqAuth.value = data.auth
      else await loadMusicProviders()
      qqLoginQr.value = ''
      qqLoginIdentifier.value = ''
      notify('QQ 音乐会员账号已连接')
    } else if (data.status === 'conf') {
      qqLoginState.value = '已扫码，请在手机上确认'
    } else if (data.status === 'scan') {
      qqLoginState.value = '等待扫码'
    } else {
      stopQQLoginPoll()
      qqLoginState.value = data.status === 'refuse' ? '已取消登录' : '二维码已过期'
    }
  } catch (error) {
    stopQQLoginPoll()
    qqLoginState.value = settingsFailure(error, '登录状态检查失败')
  }
}

async function startQQLogin(loginType: 'qq' | 'wx') {
  if (qqAuthLoading.value) return
  stopQQLoginPoll()
  qqAuthLoading.value = true
  qqLoginQr.value = ''
  qqLoginIdentifier.value = ''
  qqLoginType.value = loginType
  qqLoginState.value = '正在生成二维码'
  try {
    const data = await postAdminJson<{ identifier: string; image: string; login_type: 'qq' | 'wx' }>('/api/qqmusic/login/qrcode', { login_type: loginType }, settingsToken.value)
    qqLoginIdentifier.value = data.identifier
    qqLoginQr.value = data.image
    qqLoginState.value = loginType === 'wx' ? '请使用微信扫码' : '请使用手机 QQ 扫码'
    qqLoginTimer = window.setInterval(() => { void pollQQLogin() }, 1600)
  } catch (error) {
    qqLoginState.value = settingsFailure(error, '二维码生成失败')
  } finally {
    qqAuthLoading.value = false
  }
}

async function logoutQQMusic() {
  try {
    await postAdminJson('/api/qqmusic/logout', {}, settingsToken.value)
    stopQQLoginPoll()
    qqLoginQr.value = ''
    qqLoginState.value = ''
    await loadMusicProviders()
    notify('已退出 QQ 音乐账号')
  } catch (error) {
    notify(settingsFailure(error, 'QQ 音乐退出失败'))
  }
}

async function selectMusicSource(provider: MusicProvider) {
  if (musicSource.value === provider) return
  musicSource.value = provider
  searchRequestVersion += 1
  searching.value = false
  discovering.value = false
  loadingMoreSearch.value = false
  searchResults.value = []
  hotSearches.value = []
  searchHasMore.value = false
  discoveryError.value = ''
  if (!searchOpen.value) return
  if (query.value.trim()) await runSearch()
  else await loadDiscovery()
}

function syncPlaybackPosition(nextPosition: number, force = false) {
  const normalized = Math.max(0, Number(nextPosition) || 0)
  const drift = normalized - position.value
  position.value = force || Math.abs(drift) > 1.25
    ? normalized
    : Math.max(0, position.value + drift * 0.4)
  playbackAnchorPosition = position.value
  playbackAnchorTime = performance.now()
}

async function loadPlaylist(selectedGuild = guildId.value) {
  if (!selectedGuild) return
  const requestVersion = ++playlistRequestVersion
  try {
    const data = await getJson<{ playlist: Track[]; connected?: boolean; channel_id?: string; playing?: boolean; paused?: boolean; preparing?: boolean }>(`/api/playlist/current?guild_id=${encodeURIComponent(selectedGuild)}`)
    if (requestVersion !== playlistRequestVersion) return
    if (data.success === false) throw new Error(data.error)
    if (selectedGuild === guildId.value && typeof data.connected === 'boolean') {
      connectedChannelId.value = data.channel_id || ''
      connected.value = data.connected && connectedChannelId.value === channelId.value
    }
    const playlist = (data.playlist ?? []).map((track) => ({ ...track, id: String(track.id), duration: Number(track.duration || 0) }))
    const previousTrackId = current.value ? `${current.value.provider || 'netease'}:${current.value.id}` : ''
    const incomingCurrent = playlist.find((track) => track.playing)
    tracks.value = playlist
    if (incomingCurrent) {
      const incomingTrackId = `${incomingCurrent.provider || 'netease'}:${incomingCurrent.id}`
      syncPlaybackPosition(Number(incomingCurrent.position || 0), previousTrackId !== incomingTrackId)
      if (typeof data.preparing === 'boolean') preparingPlayback.value = data.preparing
      if (typeof data.playing === 'boolean' || typeof data.paused === 'boolean') {
        isPlaying.value = Boolean(data.playing) && !data.paused
      } else if (previousTrackId !== incomingTrackId) {
        // 兼容后端滚动升级：新曲目出现时先冻结，等待状态接口确认起播。
        isPlaying.value = false
      }
    } else {
      position.value = 0
      isPlaying.value = false
      preparingPlayback.value = false
    }
  } catch {
    if (requestVersion !== playlistRequestVersion) return
  }
}

async function loadPlayerState(selectedGuild: string) {
  try {
    const data = await getJson<{ connected: boolean; channel_id?: string; volume?: number; play_mode?: PlayMode; paused?: boolean; playing?: boolean; preparing?: boolean; position?: number }>(`/api/player/state?guild_id=${encodeURIComponent(selectedGuild)}`)
    connectedChannelId.value = data.channel_id || ''
    connected.value = Boolean(data.connected) && connectedChannelId.value === channelId.value
    isPlaying.value = Boolean(data.playing) && !data.paused
    preparingPlayback.value = Boolean(data.preparing)
    if (typeof data.position === 'number' && current.value) syncPlaybackPosition(data.position)
    if (typeof data.volume === 'number') volume.value = Math.round(data.volume * 100)
    if (data.play_mode) playMode.value = data.play_mode
  } catch {
    connectedChannelId.value = ''
    connected.value = false
  }
}

async function refreshAll() {
  refreshing.value = true
  await Promise.all([loadPlaylist(), guildId.value ? loadPlayerState(guildId.value) : Promise.resolve()])
  window.setTimeout(() => { refreshing.value = false }, 360)
}

async function loadChannels(preferredChannelId = channelId.value) {
  if (!guildId.value) return
  try {
    const data = await getJson<{ channels: Channel[] }>(`/api/channels?guild_id=${encodeURIComponent(guildId.value)}`)
    channels.value = data.channels ?? []
    setupError.value = ''
    const preferred = channels.value.find((channel) => channel.id === preferredChannelId)
    if (preferred) {
      channelId.value = preferred.id
      resolvedChannelName.value = preferred.name
    } else if (preferredChannelId) {
      channelId.value = preferredChannelId
    } else {
      channelId.value = ''
      resolvedChannelName.value = ''
    }
  } catch (error) {
    channels.value = []
    setupError.value = error instanceof Error ? error.message : '无法读取语音频道'
  }
}

async function selectGuild(id: string, preferredChannelId = '') {
  guildId.value = id
  if (!preferredChannelId) {
    channelId.value = ''
    resolvedChannelName.value = ''
  }
  localStorage.setItem('currentGuildId', id)
  const name = guilds.value.find((guild) => guild.id === id)?.name
  if (name) localStorage.setItem('currentGuildName', name)
  await Promise.all([loadChannels(preferredChannelId), loadPlaylist(id), loadPlayerState(id)])
  if (searchOpen.value && !query.value.trim() && discoveryView.value === 'community') {
    await loadRecommendationBoard()
  }
}

function consoleBasePath() {
  const scriptRoot = String(window.APP_BASE || '').replace(/\/$/, '')
  return scriptRoot || '/Music'
}

function updateChannelRoute(id: string, replace = false) {
  const oauthQuery = new URLSearchParams()
  const currentQuery = new URLSearchParams(window.location.search)
  for (const key of ['oauth', 'message']) {
    const value = currentQuery.get(key)
    if (value) oauthQuery.set(key, value)
  }
  const suffix = oauthQuery.size ? `?${oauthQuery.toString()}` : ''
  const target = `${id ? `${consoleBasePath()}/${encodeURIComponent(id)}` : consoleBasePath()}${suffix}`
  window.history[replace ? 'replaceState' : 'pushState']({ channelId: id }, '', target)
}

async function resolveChannelContext(id: string, replaceRoute = false) {
  if (!id) return
  const data = await getJson<{ context: { guild_id: string; channel_id: string; channel_name: string } }>(`/api/channel/context?channel_id=${encodeURIComponent(id)}`)
  const context = data.context
  resolvedChannelName.value = context.channel_name
  channelId.value = context.channel_id
  localStorage.setItem('currentChannelId', context.channel_id)
  await selectGuild(context.guild_id, context.channel_id)
  updateChannelRoute(context.channel_id, replaceRoute)
}

async function chooseChannel(channel: Channel) {
  channelId.value = channel.id
  resolvedChannelName.value = channel.name
  setupError.value = ''
  localStorage.setItem('currentChannelId', channel.id)
  updateChannelRoute(channel.id)
  channelSwitcherOpen.value = false
  await Promise.all([loadPlaylist(), guildId.value ? loadPlayerState(guildId.value) : Promise.resolve()])
}

async function handleGuildSelection(event: Event) {
  const id = (event.target as HTMLSelectElement).value
  if (!id) return
  localStorage.removeItem('currentChannelId')
  updateChannelRoute('')
  await selectGuild(id)
}

async function handlePopState() {
  const id = window.location.pathname.match(/(?:\/Music)?\/(\d+)\/?$/)?.[1] || ''
  if (!id || id === channelId.value) return
  try {
    await resolveChannelContext(id, true)
  } catch (error) {
    setupError.value = error instanceof Error ? error.message : '无法打开该语音频道'
    channelSwitcherOpen.value = true
  }
}

onMounted(async () => {
  try {
    const data = await getJson<{ guilds: Guild[] }>('/api/guilds')
    guilds.value = data.guilds ?? []
    setupError.value = ''

    if (initialChannelId) {
      await resolveChannelContext(initialChannelId, true)
    } else {
      const selectedGuild = guilds.value.some((guild) => guild.id === savedGuildId) ? savedGuildId : guilds.value[0]?.id
      if (selectedGuild) await selectGuild(selectedGuild, savedChannelId)
      if (savedChannelId && channelId.value) updateChannelRoute(channelId.value, true)
      channelSwitcherOpen.value = !channelId.value
    }
  } catch (error) {
    setupError.value = error instanceof Error ? error.message : '后端服务暂时不可用'
    channelSwitcherOpen.value = true
  } finally {
    bootstrapping.value = false
    if (!current.value) lyricState.value = 'empty'
  }
  await loadRecommendationAuth()
  await finishRecommendationLoginReturn()
  if (guildId.value) await loadRecommendationBoard()
  window.addEventListener('popstate', handlePopState)
  pollTimer = window.setInterval(() => { if (guildId.value) void loadPlaylist() }, 1000)
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
  if (progressTimer) window.clearInterval(progressTimer)
  if (toastTimer) window.clearTimeout(toastTimer)
  if (volumeTimer) window.clearTimeout(volumeTimer)
  if (searchInputTimer) window.clearTimeout(searchInputTimer)
  stopQQLoginPoll()
  stopNeteaseLoginPoll()
  stopSettingsMonitor()
  for (const timer of addedIconTimers.values()) window.clearTimeout(timer)
  addedIconTimers.clear()
  window.removeEventListener('popstate', handlePopState)
  window.removeEventListener('pointerup', finishPointerDrag)
  document.body.classList.remove('is-queue-dragging')
})

watch([isPlaying, () => current.value?.id, duration], () => {
  if (progressTimer) window.clearInterval(progressTimer)
  playbackAnchorPosition = position.value
  playbackAnchorTime = performance.now()
  if (!isPlaying.value || !current.value || duration.value <= 0) return
  progressTimer = window.setInterval(() => {
    if (seeking.value) return
    const elapsed = (performance.now() - playbackAnchorTime) / 1000
    position.value = Math.min(duration.value, playbackAnchorPosition + elapsed)
  }, 100)
}, { immediate: true })

watch(searchOpen, async (open) => {
  if (!open) {
    if (searchInputTimer) window.clearTimeout(searchInputTimer)
    searchInputTimer = undefined
    searchRequestVersion += 1
    searching.value = false
    discovering.value = false
    loadingMoreSearch.value = false
    return
  }
  await nextTick()
  if (!query.value.trim()) void loadDiscovery()
  window.setTimeout(() => searchInput.value?.focus(), 80)
})

watch(settingsOpen, async (open) => {
  if (!open) {
    stopQQLoginPoll()
    stopNeteaseLoginPoll()
    stopSettingsMonitor()
    return
  }
  await Promise.all([loadMusicProviders(), loadTransitionSettings()])
  if (!settingsUnlocked.value) return
  startSettingsMonitor()
  if (qqLoginIdentifier.value && !qqLoginTimer) {
    qqLoginTimer = window.setInterval(() => { void pollQQLogin() }, 1600)
  }
  if (neteaseLoginKey.value && !neteaseLoginTimer) {
    neteaseLoginTimer = window.setInterval(() => { void pollNeteaseLogin() }, 1800)
  }
})

watch(() => current.value ? `${current.value.provider || 'netease'}:${current.value.id}` : '', async (trackKey) => {
  const playingTrack = current.value
  if (!trackKey || !playingTrack) {
    lyricTargetId = ''
    lyricsTrackId.value = ''
    lyricRequestVersion += 1
    lyrics.value = []
    lyricState.value = bootstrapping.value ? 'loading' : 'empty'
    return
  }
  if (trackKey === lyricTargetId) return
  lyricTargetId = trackKey
  const requestVersion = ++lyricRequestVersion

  lyricsTrackId.value = trackKey
  const cachedLyrics = lyricCache.get(trackKey)
  if (cachedLyrics) {
    lyrics.value = cachedLyrics
    lyricState.value = 'ready'
  } else {
    lyrics.value = []
    lyricState.value = 'loading'
  }

  const provider = playingTrack.provider || 'netease'
  const id = playingTrack.id
  const detailPromise = getJson<{ song?: { album?: string; cover?: string; duration?: number } }>(`/api/song/detail?id=${encodeURIComponent(id)}&provider=${provider}`)
  const lyricPromise = provider === 'bilibili' ? Promise.resolve([] as LyricLine[]) : (async () => {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const response = await getJson<{ lyric?: string; translated_lyric?: string }>(`/api/song/lyrics?id=${encodeURIComponent(id)}&provider=${provider}`)
        const parsed = mergeTranslatedLyrics(
          response.lyric ?? '',
          response.translated_lyric ?? '',
        )
        if (parsed.length || attempt === 1) return parsed
      } catch {
        if (attempt === 1) return []
      }
      await new Promise((resolve) => window.setTimeout(resolve, 450))
    }
    return []
  })()

  const [detailResult, lyricResult] = await Promise.allSettled([detailPromise, lyricPromise])
  if (requestVersion !== lyricRequestVersion || lyricTargetId !== trackKey) return

  if (detailResult.status === 'fulfilled') {
    const detail = detailResult.value
    if (detail.song) {
      tracks.value = tracks.value.map((track) => track.id === id && (track.provider || 'netease') === provider
        ? { ...track, album: detail.song?.album || track.album, cover: detail.song?.cover || track.cover, duration: detail.song?.duration || track.duration }
        : track)
    }
  }

  const parsedLyrics = lyricResult.status === 'fulfilled' ? lyricResult.value : []
  if (parsedLyrics.length) {
    lyricCache.set(trackKey, parsedLyrics)
    lyrics.value = parsedLyrics
    lyricState.value = 'ready'
  } else if (!cachedLyrics) {
    lyrics.value = []
    lyricState.value = 'empty'
  }
})

const activeLyricIndex = computed(() => {
  const adjusted = position.value + lyricOffset.value
  for (let index = lyrics.value.length - 1; index >= 0; index -= 1) {
    if (adjusted >= lyrics.value[index].time) return index
  }
  return 0
})
const lyricItems = computed(() => lyrics.value.map((line, index) => ({
  line,
  index,
  offset: index - activeLyricIndex.value,
  distance: Math.abs(index - activeLyricIndex.value),
})))
const hasTranslation = computed(() => lyrics.value.some((line) => Boolean(line.translation)))

async function togglePlayback() {
  if (preparingPlayback.value) {
    notify('歌曲正在预热，请稍候')
    return
  }
  if (!guildId.value || !current.value || playbackControlPending.value) {
    if (!current.value) notify('当前没有正在播放的歌曲')
    return
  }
  const next = !isPlaying.value
  playbackControlPending.value = true
  try {
    const data = await postJson<{ paused?: boolean; position?: number }>(next ? '/api/resume' : '/api/pause', { guild_id: guildId.value })
    isPlaying.value = data.paused === undefined ? next : !data.paused
    preparingPlayback.value = false
    if (typeof data.position === 'number') syncPlaybackPosition(data.position, true)
  } catch (error) {
    notify(error instanceof Error ? error.message : '播放状态切换失败')
  } finally {
    playbackControlPending.value = false
  }
}

async function previousTrack() {
  if (!guildId.value) {
    notify('请先选择语音频道')
    return
  }
  try {
    await postJson('/api/previous', { guild_id: guildId.value })
    await loadPlaylist()
  } catch (error) { notify(error instanceof Error ? error.message : '暂时无法返回上一首') }
}

async function nextTrack() {
  if (!guildId.value || !current.value) {
    notify('当前没有正在播放的歌曲')
    return
  }
  try {
    await postJson('/api/skip', { guild_id: guildId.value })
    await loadPlaylist()
  } catch (error) { notify(error instanceof Error ? error.message : '跳转失败') }
}

async function clearQueue() {
  if (clearingQueue.value) return
  if (!guildId.value) {
    notify('请先选择语音频道')
    return
  }
  clearingQueue.value = true
  try {
    const data = await postJson<{ disconnected?: boolean; playlist?: Track[] }>('/api/clear', { guild_id: guildId.value })
    tracks.value = data.playlist ?? []
    lyrics.value = []
    lyricState.value = 'empty'
    lyricsTrackId.value = ''
    lyricTargetId = ''
    lyricRequestVersion += 1
    syncPlaybackPosition(0, true)
    isPlaying.value = false
    preparingPlayback.value = false
    connected.value = data.disconnected === false
    connectedChannelId.value = connected.value ? channelId.value : ''
    notify(connected.value ? '冷却期间收到新歌曲，机器人继续播放' : '已清空全部音乐并退出语音频道')
  } catch (error) {
    notify(error instanceof Error ? error.message : '清空失败')
    await Promise.all([loadPlaylist(), loadPlayerState(guildId.value)])
  } finally {
    clearingQueue.value = false
  }
}

async function cyclePlayMode() {
  if (!guildId.value) {
    notify('请先选择语音频道')
    return
  }
  const modes: PlayMode[] = ['order', 'repeat-one', 'shuffle']
  const next = modes[(modes.indexOf(playMode.value) + 1) % modes.length]
  playMode.value = next
  notify(`已切换为${MODE_META[next].label}`)
  try { await postJson('/api/play-mode', { guild_id: guildId.value, mode: next }) }
  catch (error) { notify(error instanceof Error ? error.message : '播放模式切换失败') }
}

async function commitSeek() {
  seeking.value = false
  syncPlaybackPosition(position.value, true)
  if (!guildId.value || !current.value) return
  try { await postJson('/api/seek', { guild_id: guildId.value, position: Math.round(position.value) }) }
  catch (error) { notify(error instanceof Error ? error.message : '进度调整失败') }
}

async function commitVolume() {
  if (volumeTimer) {
    window.clearTimeout(volumeTimer)
    volumeTimer = undefined
  }
  if (!guildId.value) return
  const requestVersion = ++volumeRequestVersion
  const requestedVolume = volume.value / 100
  try {
    const data = await postJson<{ volume?: number }>('/api/volume', { guild_id: guildId.value, volume: requestedVolume })
    if (requestVersion === volumeRequestVersion
        && Math.abs(volume.value / 100 - requestedVolume) < 0.005
        && typeof data.volume === 'number') {
      volume.value = Math.round(data.volume * 100)
    }
  } catch (error) {
    if (requestVersion === volumeRequestVersion) notify(error instanceof Error ? error.message : '音量调整失败')
  }
}

function scheduleVolumeCommit() {
  // 拖动开始立即生效，持续拖动时最多每 80ms 合并一次最新值。
  if (volumeTimer) return
  void commitVolume()
  volumeTimer = window.setTimeout(() => {
    volumeTimer = undefined
    void commitVolume()
  }, 80)
}

async function connectVoice() {
  if (voiceControlPending.value) return
  if (!guildId.value || !channelId.value) {
    channelSwitcherOpen.value = true
    notify('请先选择语音频道')
    return
  }
  const leaving = connected.value
  const switching = !leaving && Boolean(connectedChannelId.value) && connectedChannelId.value !== channelId.value
  voiceControlPending.value = true
  try {
    await postJson(leaving ? '/api/leave' : '/api/join', leaving
      ? { guild_id: guildId.value }
      : { guild_id: guildId.value, channel_id: channelId.value })
    connected.value = !leaving
    connectedChannelId.value = connected.value ? channelId.value : ''
    notify(leaving ? '已断开语音频道' : switching ? `已切换到 ${channelName.value}` : `已连接到 ${channelName.value}`)
  } catch (error) {
    notify(error instanceof Error ? error.message : '语音频道操作失败')
    await loadPlayerState(guildId.value)
  } finally {
    voiceControlPending.value = false
  }
}

function getSearchPageSize() {
  const availableHeight = searchResultsBox.value?.clientHeight || 420
  // 多取一行，确保首屏天然可滚动；仍只请求当前抽屉所需的小批量数据。
  return Math.max(5, Math.min(12, Math.ceil(availableHeight / 67) + 1))
}

async function ensureSearchResultsScrollable() {
  if (searchAutoFillRunning || !searchOpen.value) return
  searchAutoFillRunning = true
  try {
    for (let attempt = 0; attempt < 4 && searchHasMore.value; attempt += 1) {
      await nextTick()
      const box = searchResultsBox.value
      if (!box || box.scrollHeight > box.clientHeight + 2) break
      await loadMoreSearchResults()
    }
  } finally {
    searchAutoFillRunning = false
  }
}

async function loadDiscovery() {
  if (!searchOpen.value || query.value.trim()) return
  const requestVersion = ++searchRequestVersion
  searchMode.value = 'discover'
  activeSearchKeyword.value = ''
  searchResults.value = []
  hotSearches.value = []
  searchHasMore.value = false
  discoveryError.value = ''
  searching.value = false
  loadingMoreSearch.value = false
  discovering.value = true
  if (searchResultsBox.value) searchResultsBox.value.scrollTop = 0
  if (discoveryView.value === 'community') {
    discovering.value = false
    await loadRecommendationBoard()
    if (communityAutoFallback.value) await loadDiscovery()
    return
  }
  if (musicSource.value === 'bilibili') {
    discovering.value = false
    return
  }
  try {
    const limit = getSearchPageSize()
    const provider = musicSource.value
    const data = await getJson<{
      hot_searches?: HotSearch[]
      songs: SearchTrack[]
      pagination?: { has_more?: boolean }
    }>(`/api/discover?provider=${provider}&limit=${limit}&offset=0`)
    if (requestVersion !== searchRequestVersion) return
    hotSearches.value = data.hot_searches ?? []
    searchResults.value = data.songs ?? []
    searchHasMore.value = Boolean(data.pagination?.has_more)
  } catch (error) {
    if (requestVersion !== searchRequestVersion) return
    discoveryError.value = error instanceof Error ? error.message : `${selectedProviderName.value}发现页暂时不可用`
    searchResults.value = []
    searchHasMore.value = false
  } finally {
    if (requestVersion === searchRequestVersion) {
      discovering.value = false
      void ensureSearchResultsScrollable()
    }
  }
}

async function handleSearchQueryInput() {
  if (searchInputTimer) window.clearTimeout(searchInputTimer)
  searchInputTimer = undefined
  // 输入发生变化时立刻废弃旧请求，避免慢响应覆盖新关键词。
  searchRequestVersion += 1
  await nextTick()
  if (!query.value.trim()) {
    void loadDiscovery()
    return
  }
  searchInputTimer = window.setTimeout(() => {
    searchInputTimer = undefined
    void runSearch()
  }, 280)
}

function runHotSearch(keyword: string) {
  query.value = keyword
  void runSearch()
}

async function runSearch() {
  if (searchInputTimer) window.clearTimeout(searchInputTimer)
  searchInputTimer = undefined
  const keyword = query.value.trim()
  if (!keyword) {
    void loadDiscovery()
    return
  }
  const requestVersion = ++searchRequestVersion
  searchMode.value = 'search'
  activeSearchKeyword.value = keyword
  searchResults.value = []
  searchHasMore.value = false
  discoveryError.value = ''
  discovering.value = false
  loadingMoreSearch.value = false
  searching.value = true
  if (searchResultsBox.value) searchResultsBox.value.scrollTop = 0
  try {
    const limit = getSearchPageSize()
    const provider = musicSource.value
    const data = await getJson<{
      songs: SearchTrack[]
      pagination?: { has_more?: boolean }
    }>(`/api/search?provider=${provider}&keyword=${encodeURIComponent(keyword)}&limit=${limit}&offset=0`)
    if (requestVersion !== searchRequestVersion) return
    searchResults.value = data.songs ?? []
    searchHasMore.value = Boolean(data.pagination?.has_more)
    if (!searchResults.value.length) notify('没有找到匹配的歌曲')
  } catch (error) {
    if (requestVersion !== searchRequestVersion) return
    searchResults.value = []
    searchHasMore.value = false
    notify(error instanceof Error ? error.message : '搜索服务暂时不可用')
  } finally {
    if (requestVersion === searchRequestVersion) {
      searching.value = false
      void ensureSearchResultsScrollable()
    }
  }
}

async function loadMoreSearchResults() {
  if (searching.value || discovering.value || loadingMoreSearch.value || !searchHasMore.value) return
  if (searchMode.value === 'discover' && discoveryView.value === 'community') return
  if (searchMode.value === 'search' && !activeSearchKeyword.value) return
  const requestVersion = searchRequestVersion
  const offset = searchResults.value.length
  const limit = getSearchPageSize()
  const endpoint = searchMode.value === 'discover'
    ? `/api/discover?provider=${musicSource.value}&limit=${limit}&offset=${offset}`
    : `/api/search?provider=${musicSource.value}&keyword=${encodeURIComponent(activeSearchKeyword.value)}&limit=${limit}&offset=${offset}`
  loadingMoreSearch.value = true
  try {
    const data = await getJson<{
      songs: SearchTrack[]
      pagination?: { has_more?: boolean }
    }>(endpoint)
    if (requestVersion !== searchRequestVersion) return
    const knownIds = new Set(searchResults.value.map((song) => String(song.id)))
    const nextSongs = (data.songs ?? []).filter((song) => !knownIds.has(String(song.id)))
    searchResults.value = [...searchResults.value, ...nextSongs]
    searchHasMore.value = Boolean(data.pagination?.has_more)
  } catch (error) {
    if (requestVersion === searchRequestVersion) {
      notify(error instanceof Error ? error.message : '更多搜索结果加载失败')
    }
  } finally {
    if (requestVersion === searchRequestVersion) loadingMoreSearch.value = false
  }
}

function handleSearchScroll(event: Event) {
  const target = event.currentTarget as HTMLElement
  const remaining = target.scrollHeight - target.scrollTop - target.clientHeight
  if (remaining < 90) void loadMoreSearchResults()
}

async function addSong(song: SearchTrack) {
  if (song.playable === false) {
    notify(song.restriction || '该视频无法加入播放队列')
    return
  }
  if (!guildId.value || !channelId.value) {
    notify('请先选择并连接语音频道')
    return
  }
  const trackKey = searchTrackKey(song)
  if (isSongInPlaylist(song)) {
    notify(`《${song.name}》已在播放队列中`)
    return
  }
  if (addingSongKey.value === trackKey) return
  addingSongKey.value = trackKey
  try {
    const provider = song.provider || musicSource.value
    await postJson('/api/play', {
      guild_id: guildId.value,
      channel_id: channelId.value,
      song_id: String(song.id),
      song_name: song.name,
      artist_name: song.ar?.map((artist) => artist.name).join(' / ') || '未知艺术家',
      album_name: song.al?.name || '',
      cover_url: song.al?.picUrl || '',
      duration: (song.dt || 0) / 1000,
      provider,
    })
    markSongAdded(trackKey)
    notify(`《${song.name}》已加入队列`)
    await loadPlaylist()
  } catch (error) { notify(error instanceof Error ? error.message : '添加失败') }
  finally { addingSongKey.value = '' }
}

async function importPlaylist() {
  const id = playlistInput.value.match(/(?:id=|playlist\/)(\d+)/)?.[1] || playlistInput.value.match(/\d{5,}/)?.[0]
  if (!id || !guildId.value || !channelId.value) {
    notify('请输入有效歌单链接或 ID，并先选择语音频道')
    return
  }
  searching.value = true
  try {
    const data = await postJson<{ count?: number }>('/api/playlist', { guild_id: guildId.value, channel_id: channelId.value, playlist_id: id })
    notify(`已导入 ${data.count ?? 0} 首歌曲`)
    playlistInput.value = ''
    await loadPlaylist()
  } catch (error) { notify(error instanceof Error ? error.message : '歌单导入失败') }
  finally { searching.value = false }
}

function handleDragStart(event: DragEvent, index: number) {
  dragIndex.value = index
  dragTargetIndex.value = index
  event.dataTransfer?.setData('text/plain', String(index))
  if (event.dataTransfer) event.dataTransfer.effectAllowed = 'move'
}

function handlePointerDragStart(event: PointerEvent, index: number) {
  event.preventDefault()
  dragIndex.value = index
  dragTargetIndex.value = index
  document.body.classList.add('is-queue-dragging')
  window.removeEventListener('pointerup', finishPointerDrag)
  window.addEventListener('pointerup', finishPointerDrag, { once: true })
}

function handleDragEnter(index: number) {
  if (dragIndex.value !== null) dragTargetIndex.value = index
}

function finishPointerDrag() {
  document.body.classList.remove('is-queue-dragging')
  const target = dragTargetIndex.value ?? dragIndex.value
  if (target !== null) void dropQueue(target)
}

function cancelDrag() {
  document.body.classList.remove('is-queue-dragging')
  dragIndex.value = null
  dragTargetIndex.value = null
}

async function dropQueue(targetIndex: number) {
  if (dragIndex.value === null) return
  if (dragIndex.value === targetIndex) {
    dragIndex.value = null
    dragTargetIndex.value = null
    return
  }
  const fromVisualIndex = dragIndex.value
  const from = queuedTracks.value[fromVisualIndex]?.queue_index ?? fromVisualIndex
  const to = queuedTracks.value[targetIndex]?.queue_index ?? targetIndex
  const nextQueue = [...queuedTracks.value]
  const [moved] = nextQueue.splice(fromVisualIndex, 1)
  nextQueue.splice(targetIndex, 0, moved)
  const playing = tracks.value.filter((track) => track.playing)
  tracks.value = [...playing, ...nextQueue.map((track, index) => ({ ...track, queue_index: index }))]
  dragIndex.value = null
  dragTargetIndex.value = null
  if (guildId.value) {
    try { await postJson('/api/queue/reorder', { guild_id: guildId.value, from_index: from, to_index: to }) }
    catch (error) {
      notify(error instanceof Error ? error.message : '排序保存失败')
      await loadPlaylist()
    }
  }
}

const removingQueueIndex = ref<number | null>(null)

async function removeQueuedTrack(track: Track, visualIndex: number) {
  if (!guildId.value || removingQueueIndex.value !== null) return
  const queueIndex = track.queue_index ?? visualIndex
  removingQueueIndex.value = visualIndex
  const playing = tracks.value.filter((item) => item.playing)
  const remaining = queuedTracks.value
    .filter((_, index) => index !== visualIndex)
    .map((item, index) => ({ ...item, queue_index: index }))
  tracks.value = [...playing, ...remaining]
  try {
    await postJson('/api/remove', { guild_id: guildId.value, index: queueIndex })
    notify(`已从队列移除《${track.name}》`)
    await loadPlaylist()
  } catch (error) {
    notify(error instanceof Error ? error.message : '移除失败')
    await loadPlaylist()
  } finally {
    removingQueueIndex.value = null
  }
}
</script>

<template>
  <main class="app-shell">
    <header class="topbar">
      <div class="brand-cluster">
        <div class="brand-mark" aria-hidden="true"><Radio :size="19" :stroke-width="2.4" /></div>
        <div class="brand-title">互联网垃圾桶 <span>音乐</span></div>
        <span class="header-divider" />
        <div class="channel-switcher-anchor">
          <button class="channel-name" :class="{ 'is-empty': !channelId }" :title="`${channelName} · 点击切换`" @click="channelSwitcherOpen = !channelSwitcherOpen">
            <Headphones :size="16" /><span>{{ channelName }}</span><ChevronDown :size="14" />
          </button>
          <button v-if="channelSwitcherOpen" class="channel-switcher-scrim" aria-label="关闭频道选择" @click="channelSwitcherOpen = false" />
          <section v-if="channelSwitcherOpen" class="channel-switcher-popover" aria-label="选择语音频道">
            <div class="channel-switcher-head">
              <div><span class="eyebrow">PLAY IN</span><h2>选择语音频道</h2></div>
              <button class="icon-button" title="关闭" @click="channelSwitcherOpen = false"><X :size="18" /></button>
            </div>
            <label class="guild-picker">
              <span>KOOK 服务器</span>
              <span class="select-wrap">
                <Server :size="15" />
                <select :value="guildId" @change="handleGuildSelection">
                  <option v-if="!guilds.length" value="">暂无可用服务器</option>
                  <option v-for="guild in guilds" :key="guild.id" :value="guild.id">{{ guild.name }}</option>
                </select>
                <ChevronDown :size="15" />
              </span>
            </label>
            <div class="channel-choice-list">
              <button v-for="channel in channels" :key="channel.id" class="channel-choice" :class="{ 'is-selected': channel.id === channelId }" @click="chooseChannel(channel)">
                <span class="channel-choice-icon"><Volume2 :size="16" /></span>
                <span class="channel-choice-meta"><strong>{{ channel.name }}</strong><small>{{ guildName }} · {{ channel.id }}</small></span>
                <Check v-if="channel.id === channelId" :size="17" />
              </button>
              <div v-if="!channels.length" class="channel-choice-empty">
                <Headphones :size="24" />
                <strong>{{ setupError ? '无法读取频道' : '没有可用语音频道' }}</strong>
                <span>{{ setupError || '请确认机器人已加入服务器并拥有查看频道权限' }}</span>
              </div>
            </div>
            <div class="channel-switcher-foot">选择后会生成可收藏、可分享的 <code>/Music/频道ID</code> 地址</div>
          </section>
        </div>
      </div>
      <div class="top-actions">
        <div class="connection-latency-anchor" @mouseenter="loadBotLatency()" @focusin="loadBotLatency()">
          <button class="connection-state" :class="connected ? 'is-connected' : 'is-disconnected'" :disabled="voiceControlPending" :aria-busy="voiceControlPending" aria-describedby="connection-latency-tip" :title="connected ? '点击断开语音连接' : '点击连接所选语音频道'" @click="connectVoice">
            <LoaderCircle v-if="voiceControlPending" :size="17" class="continuous-spin" /><Wifi v-else-if="connected" :size="17" /><WifiOff v-else :size="17" /><span>{{ voiceControlPending ? '处理中' : connected ? '已连接' : channelId ? '待连接' : '未选择' }}</span>
          </button>
          <div id="connection-latency-tip" class="latency-tooltip" role="tooltip">
            <div class="latency-tooltip-head">
              <span><Activity :size="15" />网络延迟</span>
              <span v-if="botLatency" class="latency-quality" :class="latencyQuality.className">{{ latencyQuality.label }}</span>
            </div>
            <div v-if="botLatencyLoading && !botLatency" class="latency-loading"><LoaderCircle :size="15" class="continuous-spin" />正在探测链路</div>
            <div v-else-if="botLatencyError && !botLatency" class="latency-error">{{ botLatencyError }}</div>
            <template v-else-if="botLatency">
              <div class="latency-row"><span>浏览器 → 控制台</span><strong>{{ botLatency.consoleMs }} ms</strong></div>
              <div class="latency-row" :title="botLatency.kookError || '复用 HTTPS 连接测量 KOOK REST API 响应'"><span>MusicBot → KOOK API</span><strong>{{ botLatency.kookRestMs === null ? '—' : `${botLatency.kookRestMs} ms` }}</strong></div>
              <div class="latency-row"><span>MusicBot → 语音网关</span><strong>{{ botLatency.voiceGatewayMs === null ? (connected ? '不可探测' : '未连接') : `${botLatency.voiceGatewayMs} ms` }}</strong></div>
              <div class="latency-foot"><span class="live-dot" /><template v-if="botLatency.transport">发送 {{ botLatency.transport.actual_fps.toFixed(1) }} / {{ botLatency.transport.target_fps.toFixed(0) }} fps</template><template v-else>三段独立探测 · 10 秒复用</template></div>
            </template>
          </div>
        </div>
        <button class="icon-button" aria-label="搜索音乐" title="搜索音乐" @click="searchOpen = true"><Search :size="19" /></button>
        <button class="icon-button" aria-label="刷新页面状态" title="刷新页面状态" @click="refreshAll"><RefreshCw :size="19" :class="{ 'spin-once': refreshing }" /></button>
        <button class="icon-button" aria-label="音乐后台设置" title="音乐后台设置" @click="settingsOpen = true"><Settings :size="19" /></button>
      </div>
    </header>

    <section class="console-grid">
      <section class="panel player-panel">
        <div class="cover-wrap">
          <img class="album-cover" :src="current?.cover || FALLBACK_COVER" :alt="current ? `${current.name} 专辑封面` : '默认专辑封面'" :referrerpolicy="coverReferrerPolicy(currentProvider)" @error="coverFallback" />
          <div class="playing-stamp"><span class="playing-dot" />{{ bootstrapping ? 'LOADING' : current ? (preparingPlayback ? 'BUFFERING' : isPlaying ? 'PLAYING' : 'PAUSED') : 'IDLE' }}</div>
        </div>
        <div class="track-meta">
          <h1>{{ current?.name || (bootstrapping ? '正在加载' : '等待播放') }}</h1>
          <h2>{{ current?.artist || (bootstrapping ? '正在读取播放器状态' : '从右上角搜索并添加音乐') }}</h2>
          <p>{{ current?.album || '互联网垃圾桶音乐控制台' }}</p>
        </div>
        <div class="source-row">
          <span class="source-dot" :class="`is-${currentProvider}`"><img class="provider-logo" :class="`is-${currentProvider}`" :src="providerIcon(currentProvider)" :alt="`${currentProviderLabel} 图标`" /></span><span class="source-name">{{ currentProviderLabel }}</span>
          <button
            v-if="current"
            class="current-recommend-button"
            :class="{ 'is-active': isRecommended(current) }"
            :disabled="recommendationBusyKey === recommendationKey(current)"
            :title="isRecommended(current) ? '撤回我的推荐' : '推荐给这个服务器的所有人'"
            @click="toggleRecommendation(current)"
          >
            <LoaderCircle v-if="recommendationBusyKey === recommendationKey(current)" :size="13" class="continuous-spin" />
            <Megaphone v-else :size="13" />
            <span>{{ isRecommended(current) ? '已推荐' : '推荐' }}</span>
          </button>
        </div>
        <div class="slider-block progress-block">
          <input
            v-model.number="position"
            class="range-input progress-range"
            type="range"
            min="0"
            :max="Math.max(duration, 1)"
            step="1"
            :style="rangeProgressStyle"
            aria-label="歌曲进度"
            :disabled="!current"
            @pointerdown="seeking = true"
            @pointerup="seeking = false"
            @pointercancel="seeking = false"
            @change="commitSeek"
          />
          <div class="time-row"><span>{{ formatTime(position) }}</span><span>{{ formatTime(duration) }}</span></div>
        </div>
        <div class="slider-block volume-block">
          <Volume2 :size="17" />
          <input v-model.number="volume" class="range-input volume-range" type="range" min="0" max="100" :style="volumeProgressStyle" aria-label="音量" @input="scheduleVolumeCommit" @change="commitVolume" />
          <span class="volume-value">{{ volume }}%</span>
        </div>
        <div class="transport-controls">
          <button title="上一首" @click="previousTrack"><SkipBack :size="20" /><span>上一首</span></button>
          <button :disabled="clearingQueue" title="清空全部音乐并退出语音频道" @click="clearQueue"><LoaderCircle v-if="clearingQueue" :size="19" class="continuous-spin" /><Trash2 v-else :size="19" /><span>{{ clearingQueue ? '退出中' : '清空' }}</span></button>
          <button class="primary-control" :disabled="!current || playbackControlPending || preparingPlayback" :title="preparingPlayback ? '歌曲预热中' : isPlaying ? '暂停' : '继续播放'" @click="togglePlayback">
            <LoaderCircle v-if="playbackControlPending || preparingPlayback" :size="19" class="continuous-spin" /><Pause v-else-if="isPlaying" :size="20" /><Play v-else :size="20" fill="currentColor" /><span>{{ preparingPlayback ? '预热中' : playbackControlPending ? '切换中' : isPlaying ? '暂停' : '播放' }}</span>
          </button>
          <button title="下一首" @click="nextTrack"><SkipForward :size="20" /><span>下一首</span></button>
          <button :class="{ 'is-active': playMode !== 'order' }" title="切换播放模式" @click="cyclePlayMode">
            <component :is="modeIcon" :size="19" /><span>{{ MODE_META[playMode].label }}</span>
          </button>
        </div>
      </section>

      <section class="panel lyrics-panel">
        <div class="panel-heading lyrics-heading">
          <div><span class="eyebrow">NOW PLAYING</span><h3>实时歌词</h3></div>
          <div class="lyrics-actions">
            <button class="translation-toggle" :class="{ 'is-active': showTranslation && hasTranslation }" :disabled="!hasTranslation" :aria-pressed="showTranslation && hasTranslation" :title="hasTranslation ? (showTranslation ? '隐藏歌词翻译' : '显示歌词翻译') : '当前歌曲没有可用翻译'" @click="showTranslation = !showTranslation"><Languages :size="16" /><span>译</span></button>
            <div class="sync-control">
              <button class="subtle-button" title="调整歌词同步" @click="syncOpen = !syncOpen"><Clock3 :size="16" /><span>同步</span></button>
              <div v-if="syncOpen" class="sync-popover">
                <div class="popover-label"><span>歌词时差</span><strong>{{ lyricOffset > 0 ? '+' : '' }}{{ lyricOffset.toFixed(1) }}s</strong></div>
                <div class="sync-buttons">
                  <button title="歌词提前 0.5 秒" @click="lyricOffset = Number((lyricOffset - 0.5).toFixed(1))"><Minus :size="16" /></button>
                  <button title="重置同步" @click="lyricOffset = 0"><RotateCcw :size="15" /></button>
                  <button title="歌词延后 0.5 秒" @click="lyricOffset = Number((lyricOffset + 0.5).toFixed(1))"><Plus :size="16" /></button>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="lyrics-stage" :class="{ 'has-translation': showTranslation && hasTranslation }" aria-live="polite">
          <div v-if="lyricState === 'loading'" class="lyric-status">
            <LoaderCircle :size="22" class="continuous-spin" />
            <span>正在同步歌词</span>
          </div>
          <div v-else-if="lyricState === 'empty'" class="lyric-status">
            <Music2 :size="24" />
            <span>{{ current ? '这首歌暂时没有可用歌词' : '播放歌曲后将在这里显示歌词' }}</span>
          </div>
          <div v-else class="lyrics-list">
            <div
              v-for="item in lyricItems"
              :key="`${lyricsTrackId}-${item.index}-${item.line.time}`"
              class="lyric-line"
              :class="{ 'is-current': item.index === activeLyricIndex, 'is-hidden': item.distance > 8 }"
              :style="{ '--offset': String(item.offset), '--distance': String(item.distance) }"
            >
              <span class="lyric-original">{{ item.line.text }}</span>
              <span v-if="showTranslation && item.line.translation" class="lyric-translation">{{ item.line.translation }}</span>
            </div>
          </div>
        </div>
        <div class="lyric-footer"><span>{{ formatTime(position + lyricOffset) }}</span><span>歌词已自动对齐</span></div>
      </section>

      <section class="panel queue-panel">
        <div class="panel-heading queue-heading">
          <div class="queue-title"><ListMusic :size="19" /><h3>播放队列</h3></div><span class="queue-count">{{ queuedTracks.length }} 首</span>
        </div>
        <div class="queue-list">
          <article v-if="current" class="queue-card is-current">
            <span class="queue-playing-bars" aria-label="正在播放"><i /><i /><i /></span><span class="queue-number">NOW</span>
            <img :src="current.cover || FALLBACK_COVER" alt="" :referrerpolicy="coverReferrerPolicy(current.provider)" @error="coverFallback" />
            <div class="queue-track-meta"><strong>{{ current.name }}</strong><span>{{ current.artist }}</span></div><div class="queue-actions"><button class="queue-recommend" :class="{ 'is-active': isRecommended(current) }" :disabled="recommendationBusyKey === recommendationKey(current)" :title="isRecommended(current) ? '撤回我的推荐' : '推荐给大家'" @click.stop="toggleRecommendation(current)"><LoaderCircle v-if="recommendationBusyKey === recommendationKey(current)" :size="13" class="continuous-spin" /><Megaphone v-else :size="14" /></button><span class="queue-duration">{{ formatTime(current.duration) }}</span></div>
          </article>
          <article v-for="(track, index) in queuedTracks" :key="`${track.id}-${track.queue_index ?? index}`" class="queue-card" :class="{ 'is-dragging': dragIndex === index, 'is-drag-over': dragIndex !== null && dragTargetIndex === index && dragIndex !== index }" draggable="true" @dragstart="handleDragStart($event, index)" @dragend="cancelDrag" @dragenter.prevent="handleDragEnter(index)" @dragover.prevent @drop.prevent="dropQueue(index)" @pointerenter="handleDragEnter(index)">
            <GripVertical class="drag-handle" :size="17" aria-label="拖动调整顺序" @pointerdown="handlePointerDragStart($event, index)" /><span class="queue-number">{{ String(index + 1).padStart(2, '0') }}</span>
            <img :src="track.cover || FALLBACK_COVER" alt="" :referrerpolicy="coverReferrerPolicy(track.provider)" @error="coverFallback" />
            <div class="queue-track-meta"><strong>{{ track.name }}</strong><span>{{ track.artist }}</span></div><div class="queue-actions"><button class="queue-recommend" :class="{ 'is-active': isRecommended(track) }" :disabled="recommendationBusyKey === recommendationKey(track)" :title="isRecommended(track) ? '撤回我的推荐' : '推荐给大家'" @pointerdown.stop @click.stop="toggleRecommendation(track)"><LoaderCircle v-if="recommendationBusyKey === recommendationKey(track)" :size="13" class="continuous-spin" /><Megaphone v-else :size="14" /></button><button class="queue-remove" :disabled="removingQueueIndex !== null" :title="`从队列移除《${track.name}》`" :aria-label="`从队列移除《${track.name}》`" @pointerdown.stop @click.stop="removeQueuedTrack(track, index)"><LoaderCircle v-if="removingQueueIndex === index" :size="13" class="continuous-spin" /><X v-else :size="14" /></button><span class="queue-duration">{{ formatTime(track.duration) }}</span></div>
          </article>
          <div v-if="!current && !queuedTracks.length" class="empty-queue"><Music2 :size="30" /><strong>播放队列为空</strong><span>搜索一首歌，让声音填满这里</span></div>
        </div>
        <div class="queue-footer"><GripVertical :size="14" /><span>拖动歌曲卡片调整播放顺序</span></div>
      </section>
    </section>

    <template v-if="settingsOpen">
      <button class="settings-scrim" aria-label="关闭音乐后台" @click="settingsOpen = false" />
      <aside class="settings-drawer" aria-label="音乐服务后台">
        <div class="settings-drawer-head">
          <div><span class="eyebrow">MUSIC ADMIN</span><h2>音乐服务后台</h2><p>账号凭证仅保存在运行 MusicBot 的服务器</p></div>
          <button class="icon-button" title="关闭" @click="settingsOpen = false"><X :size="19" /></button>
        </div>

        <div class="provider-engine-state settings-engine-state" :class="{ 'is-local-online': neteaseLocalEngineReady, 'is-engine-error': !neteaseLocalEngineReady }">
          <i aria-hidden="true" />
          <div>
            <strong>{{ neteaseAuthLoading ? '正在检测网易云解析引擎' : neteaseLocalEngineReady ? `本项目本地解析引擎${neteaseAuth.engine?.version ? ` v${neteaseAuth.engine.version}` : ''}` : neteaseAuth.engine?.mode === 'local' ? '本地外置解析引擎' : '外部解析引擎' }}</strong>
            <span>{{ neteaseAuth.engine?.endpoint || '等待后端返回引擎地址' }}{{ neteaseLocalEngineReady ? ' · 由 MusicBot 管理且仅本机可访问' : ' · 当前不是本项目内置引擎' }}</span>
          </div>
          <em>{{ neteaseAuthLoading ? '检测中' : neteaseLocalEngineReady ? '本项目在线' : '异常' }}</em>
        </div>

        <section v-if="!settingsUnlocked" class="settings-lock-card">
          <span class="settings-lock-icon"><ShieldCheck :size="25" /></span>
          <div><h3>验证管理身份</h3><p>请输入服务器 `.env` 中的 `MUSIC_SETTINGS_TOKEN`；未配置时使用 `SECRET_KEY`。</p></div>
          <label class="settings-secret-input">
            <KeyRound :size="17" />
            <input v-model="settingsToken" type="password" autocomplete="current-password" placeholder="管理密钥" @keydown.enter="unlockMusicSettings" />
            <button :disabled="settingsUnlocking || !settingsToken.trim()" @click="unlockMusicSettings"><LoaderCircle v-if="settingsUnlocking" :size="16" class="continuous-spin" /><template v-else>解锁</template></button>
          </label>
          <p v-if="settingsError" class="settings-error">{{ settingsError }}</p>
        </section>

        <div v-else class="settings-content">
          <div class="settings-security-note">
            <ShieldCheck :size="17" /><span>管理密钥只保留到当前浏览器会话；Cookie 和登录凭证不会返回到网页。</span>
            <button @click="lockMusicSettings">锁定</button>
          </div>

          <section class="provider-settings-card transition-settings-card" aria-label="歌曲渐入渐出设置">
            <div class="transition-heading">
              <div><h3>歌曲渐入渐出</h3><p>当前歌曲渐弱，下一首渐强</p></div>
              <label class="transition-toggle"><input v-model="transitionSettings.enabled" type="checkbox" role="switch" aria-label="开启渐入渐出" :disabled="transitionLoading || transitionSaving" /><span /></label>
            </div>
            <div class="transition-duration"><span>过渡时长</span><strong>{{ transitionSettings.seconds }} 秒</strong></div>
            <input v-model.number="transitionSettings.seconds" class="range-input" type="range" min="1" max="12" step="1" aria-label="渐入渐出时长" :disabled="!transitionSettings.enabled || transitionLoading || transitionSaving" :style="{ '--range-progress': `${(transitionSettings.seconds - 1) / 11 * 100}%` }" />
            <div class="transition-range-labels"><span>1秒</span><span>默认4秒</span><span>12秒</span></div>
            <p class="transition-description">适用于所有音源，包含手动切歌。保存后从下一首生效；暂停、拖动进度和清空队列保持即时响应。</p>
            <p v-if="transitionError" class="monitor-inline-error">{{ transitionError }}</p>
            <div class="provider-settings-actions"><button class="provider-primary-action" :disabled="transitionLoading || transitionSaving" @click="saveTransitionSettings"><LoaderCircle v-if="transitionSaving" :size="15" class="continuous-spin" /><Check v-else :size="15" />{{ transitionSaving ? '保存中' : '保存设置' }}</button></div>
          </section>

          <section class="system-monitor-card">
            <div class="system-monitor-head">
              <div>
                <span class="system-monitor-icon"><Activity :size="17" /></span>
                <span><strong>运行状态</strong><small v-if="systemStatus">PID {{ systemStatus.process.pid }} · 已运行 {{ formatUptime(systemStatus.process.uptime) }}</small><small v-else>MusicBot 服务资源</small></span>
              </div>
              <button title="立即刷新运行状态与日志" :disabled="systemStatusLoading || terminalLogsLoading" @click="loadSystemStatus(); loadTerminalLogs()"><RefreshCw :size="15" :class="{ 'continuous-spin': systemStatusLoading }" />刷新</button>
            </div>

            <p v-if="systemStatusError" class="monitor-inline-error">{{ systemStatusError }}</p>
            <div class="system-metrics-grid">
              <article class="system-metric">
                <div class="system-metric-label"><span><Cpu :size="15" />CPU</span><strong>{{ systemStatus ? `${systemStatus.system.cpu_percent.toFixed(0)}%` : '—' }}</strong></div>
                <div class="system-meter"><i :style="{ width: `${Math.min(systemStatus?.system.cpu_percent || 0, 100)}%` }" /></div>
                <small>{{ systemStatus ? '系统 1 秒平均采样' : '等待采样' }}</small>
              </article>
              <article class="system-metric">
                <div class="system-metric-label"><span><MemoryStick :size="15" />内存</span><strong>{{ systemStatus ? `${systemStatus.system.memory.percent.toFixed(0)}%` : '—' }}</strong></div>
                <div class="system-meter is-memory"><i :style="{ width: `${Math.min(systemStatus?.system.memory.percent || 0, 100)}%` }" /></div>
                <small>{{ systemStatus ? `${formatBytes(systemStatus.system.memory.total - systemStatus.system.memory.available)} / ${formatBytes(systemStatus.system.memory.total)}` : '等待采样' }}</small>
              </article>
              <article class="system-metric is-network">
                <div class="system-metric-label"><span><Network :size="15" />网络</span><strong>{{ networkRate.ready ? '实时' : '采样中' }}</strong></div>
                <div class="network-rate-row"><span><ArrowDown :size="13" />{{ networkRate.ready ? formatNetworkRate(networkRate.download) : '—' }}</span><span><ArrowUp :size="13" />{{ networkRate.ready ? formatNetworkRate(networkRate.upload) : '—' }}</span></div>
                <small>下载 / 上传 · 主机总流量</small>
              </article>
            </div>

            <div class="monitor-terminal-shell">
              <div class="monitor-terminal-head">
                <span><Terminal :size="14" />debug.log</span>
                <span class="terminal-live-state"><i />LIVE · {{ terminalLogs.length }} 行</span>
              </div>
              <div ref="terminalLogBox" class="monitor-terminal" aria-label="MusicBot 实时日志" aria-live="polite">
                <div v-if="terminalLogsLoading && !terminalLogs.length" class="terminal-placeholder"><LoaderCircle :size="15" class="continuous-spin" />正在连接日志流</div>
                <div v-else-if="terminalLogsError" class="terminal-placeholder is-error">{{ terminalLogsError }}</div>
                <div v-else-if="!terminalLogs.length" class="terminal-placeholder">debug.log 暂时没有内容</div>
                <div v-for="(log, index) in terminalLogs" :key="`${log.timestamp}-${index}-${log.raw}`" class="terminal-line" :class="`is-${log.level}`">
                  <span class="terminal-line-number">{{ String(index + 1).padStart(3, '0') }}</span><code>{{ log.raw }}</code>
                </div>
              </div>
            </div>
          </section>

          <section class="provider-settings-card is-netease">
            <div class="provider-settings-head">
              <span class="provider-settings-icon"><img class="provider-logo is-netease" :src="providerIcon('netease')" alt="网易云音乐图标" /></span>
              <div><h3>网易云音乐</h3><p>扫码自动获取 Cookie，也可以手动替换</p></div>
              <span class="provider-status" :class="{ 'is-online': neteaseAuth.authenticated, 'is-loading': neteaseAuthLoading }">{{ neteaseAuthLoading ? '读取中' : neteaseAuth.authenticated ? '已持久化' : '未登录' }}</span>
            </div>
            <div class="provider-credential-summary">
              <strong>{{ neteaseAuth.authenticated ? '会员登录态可用' : '当前使用匿名接口' }}</strong>
              <span v-if="neteaseAuth.authenticated">{{ neteaseAuth.source === 'environment' ? '来自环境变量' : `本地 Cookie · ${neteaseAuth.cookie_count || 0} 项` }}</span>
              <span v-else>{{ neteaseAuth.error || '建议使用网易云音乐 App 扫码，成功后自动保存' }}</span>
            </div>
            <div v-if="neteaseLoginQr" class="provider-login-flow">
              <img :src="neteaseLoginQr" alt="网易云音乐登录二维码" />
              <div><strong>{{ neteaseLoginState }}</strong><span>二维码只用于本次登录，Cookie 成功保存后自动消失</span></div>
              <button @click="startNeteaseLogin">刷新二维码</button>
            </div>
            <p v-else-if="neteaseLoginState" class="provider-login-message">{{ neteaseLoginState }}</p>
            <div class="provider-settings-actions">
              <button class="provider-primary-action" :disabled="neteaseAuthLoading" @click="startNeteaseLogin"><QrCode :size="16" />{{ neteaseAuth.authenticated ? '重新扫码' : '网易云扫码' }}</button>
              <button v-if="neteaseAuth.authenticated" class="provider-danger-action" @click="logoutNetease"><LogOut :size="15" />删除登录</button>
            </div>
            <details class="manual-credential">
              <summary>高级：手动粘贴或替换 Cookie</summary>
              <p>在已登录的 music.163.com 请求中复制完整 Cookie 请求头。保存后输入框会立即清空，后台不会把现有 Cookie 回传到浏览器。</p>
              <textarea v-model="neteaseCookieInput" autocomplete="off" spellcheck="false" placeholder="MUSIC_U=...; __csrf=..." />
              <button :disabled="neteaseAuthLoading || !neteaseCookieInput.trim()" @click="saveNeteaseCookie">保存并替换</button>
            </details>
          </section>

          <section class="provider-settings-card is-qqmusic">
            <div class="provider-settings-head">
              <span class="provider-settings-icon"><img class="provider-logo is-qqmusic" :src="providerIcon('qqmusic')" alt="QQ音乐图标" /></span>
              <div><h3>QQ音乐</h3><p>扫码保存可刷新的会员凭证</p></div>
              <span class="provider-status" :class="{ 'is-online': qqAuth.authenticated, 'is-loading': qqAuthLoading }">{{ qqAuthLoading ? '读取中' : qqAuth.authenticated ? '已持久化' : '未登录' }}</span>
            </div>
            <div class="provider-credential-summary">
              <strong>{{ qqAuth.authenticated ? 'QQ音乐会员登录态可用' : '搜索可用，完整播放需要登录' }}</strong>
              <span v-if="qqAuth.authenticated">{{ qqAuth.account || '账号已连接' }} · {{ qqAuth.login_source === 'environment' ? '来自环境变量' : '本地受限凭证文件' }}</span>
              <span v-else>{{ qqAuth.error || '支持手机 QQ 或微信扫码，过期前会自动刷新凭证' }}</span>
            </div>
            <div v-if="qqLoginQr" class="provider-login-flow">
              <img :src="qqLoginQr" alt="QQ 音乐登录二维码" />
              <div><strong>{{ qqLoginState }}</strong><span>登录成功后会自动获得会员完整播放权限</span></div>
              <button @click="startQQLogin(qqLoginType)">刷新二维码</button>
            </div>
            <p v-else-if="qqLoginState" class="provider-login-message">{{ qqLoginState }}</p>
            <div class="provider-settings-actions">
              <button class="provider-primary-action" :disabled="qqAuthLoading || !qqAuth.available" @click="startQQLogin('qq')"><QrCode :size="16" />手机 QQ</button>
              <button class="provider-secondary-action" :disabled="qqAuthLoading || !qqAuth.available" @click="startQQLogin('wx')">微信扫码</button>
              <button v-if="qqAuth.authenticated" class="provider-danger-action" @click="logoutQQMusic"><LogOut :size="15" />删除登录</button>
            </div>
            <div class="credential-lifetime-note">凭证默认写入 <code>data/qqmusic</code>，服务重启后仍然有效；容器部署请挂载持久卷。</div>
          </section>
        </div>
      </aside>
    </template>

    <template v-if="searchOpen">
      <button class="search-scrim" aria-label="关闭搜索" @click="searchOpen = false" />
      <aside class="search-drawer" aria-label="音乐搜索菜单">
        <div class="search-drawer-head">
          <div><span class="eyebrow">MUSIC LIBRARY</span><h2>搜索音乐</h2></div>
          <button class="icon-button" title="关闭" @click="searchOpen = false"><X :size="19" /></button>
        </div>
        <div class="source-toggle" :class="{ 'is-bilibili': musicSource === 'bilibili', 'is-qqmusic': musicSource === 'qqmusic' }" role="tablist" aria-label="选择音乐源">
          <span class="source-toggle-thumb" aria-hidden="true" />
          <button role="tab" :aria-selected="musicSource === 'netease'" @click="selectMusicSource('netease')"><img class="provider-logo is-netease" :src="providerIcon('netease')" alt="" />网易云</button>
          <button role="tab" :aria-selected="musicSource === 'bilibili'" @click="selectMusicSource('bilibili')"><img class="provider-logo is-bilibili" :src="providerIcon('bilibili')" alt="" />Bilibili</button>
          <button role="tab" :aria-selected="musicSource === 'qqmusic'" @click="selectMusicSource('qqmusic')"><img class="provider-logo is-qqmusic" :src="providerIcon('qqmusic')" alt="" />QQ音乐</button>
        </div>
        <div class="search-box">
          <Search :size="19" /><input ref="searchInput" v-model="query" :placeholder="searchPlaceholder" @input="handleSearchQueryInput" @keydown.enter="runSearch" />
          <button :disabled="searching || !query.trim()" @click="runSearch"><LoaderCircle v-if="searching" :size="17" class="continuous-spin" /><template v-else>搜索</template></button>
        </div>
        <section v-if="!query.trim()" class="discovery-navigation" aria-label="发现音乐">
          <div class="discovery-tabs" role="tablist" aria-label="发现内容">
            <button role="tab" :aria-selected="discoveryView === 'community'" @click="selectDiscoveryView('community')"><UsersRound :size="15" />大家推荐<span v-if="recommendationTotal">{{ recommendationTotal }}</span></button>
            <button role="tab" :aria-selected="discoveryView === 'platform'" @click="selectDiscoveryView('platform')"><ListMusic :size="15" />平台榜单</button>
          </div>
          <div v-if="discoveryView === 'community'" class="recommendation-toolbar">
            <div class="recommendation-sort" aria-label="推荐排序">
              <button :class="{ 'is-active': recommendationSort === 'latest' }" @click="selectRecommendationSort('latest')">最新</button>
              <button :class="{ 'is-active': recommendationSort === 'popular' }" @click="selectRecommendationSort('popular')">人气</button>
            </div>
            <div class="recommendation-identity">
              <template v-if="recommendationAuthUser">
                <UserAvatar :src="recommendationAuthUser.avatar" :name="recommendationAuthUser.nickname || recommendationAuthUser.username" />
                <span>{{ recommendationAuthUser.nickname || recommendationAuthUser.username }}</span>
                <button title="退出推荐身份" @click="logoutRecommendationUser"><LogOut :size="13" /></button>
              </template>
              <button v-else :disabled="recommendationAuthLoading || !recommendationAuthConfigured" :title="recommendationAuthConfigured ? '使用 KOOK 身份登录' : '管理员尚未配置 KOOK OAuth'" @click="beginRecommendationLogin()"><LogIn :size="14" />{{ recommendationAuthLoading ? '读取中' : recommendationAuthConfigured ? 'KOOK 登录' : '推荐未配置' }}</button>
            </div>
          </div>
        </section>
        <div ref="searchResultsBox" class="search-results" @scroll.passive="handleSearchScroll">
          <template v-if="searchMode === 'discover' && discoveryView === 'community'">
            <article v-for="track in recommendations" :key="`recommendation-${recommendationKey(track)}`" class="recommendation-card">
              <button class="recommendation-main" :title="[track.name, track.artist, track.album, track.note ? `推荐：${track.note}` : ''].filter(Boolean).join(' · ')" @click="addSong(recommendationAsSearchTrack(track))">
                <span class="recommendation-cover"><img :src="track.cover || FALLBACK_COVER" alt="" :referrerpolicy="coverReferrerPolicy(track.provider)" @error="coverFallback" /><img class="recommendation-provider" :class="`is-${track.provider || 'netease'}`" :src="providerIcon(track.provider || 'netease')" alt="" /></span>
                <span class="result-meta recommendation-meta">
                  <strong>{{ track.name }}</strong>
                  <span class="recommendation-artist">{{ track.artist || (track.provider === 'bilibili' ? '未知UP主' : '未知艺术家') }}</span>
                  <span class="recommendation-social" :title="track.recommenders.map(person => person.nickname || person.username).join('、') + ' 推荐'">
                    <span class="recommender-avatars"><UserAvatar v-for="person in track.recommenders.slice(0, 3)" :key="person.user_id" :src="person.avatar" :name="person.nickname || person.username" /></span>
                    <span class="recommendation-byline">{{ track.recommenders[0]?.nickname || track.recommenders[0]?.username || 'KOOK 用户' }}<template v-if="track.recommendation_count > 1"> 等 {{ track.recommendation_count }} 人</template>推荐</span>
                    <span class="recommendation-time">· {{ formatRelativeTime(track.latest_at) }}</span>
                  </span>
                </span>
              </button>
              <button class="recommend-control" :class="{ 'is-active': isRecommended(track) }" :disabled="recommendationBusyKey === recommendationKey(track)" :title="isRecommended(track) ? '撤回我的推荐' : '我也推荐'" @click="toggleRecommendation(track)">
                <LoaderCircle v-if="recommendationBusyKey === recommendationKey(track)" :size="15" class="continuous-spin" /><Megaphone v-else :size="15" /><span>{{ isRecommended(track) ? '已推荐' : '推荐' }}</span>
              </button>
              <button class="recommendation-play" title="加入播放队列" @click="addSong(recommendationAsSearchTrack(track))"><CirclePlus :size="20" /></button>
            </article>
            <div v-if="recommendationLoading && !recommendations.length" class="search-placeholder"><LoaderCircle :size="26" class="continuous-spin" /><strong>正在读取大家推荐</strong><span>汇总这个服务器成员主动留下的好歌</span></div>
            <div v-else-if="!recommendations.length" class="search-placeholder"><UsersRound :size="28" /><strong>还没有人推荐歌曲</strong><span>{{ recommendationError || '从当前播放或搜索结果点“推荐”，成为第一个分享的人' }}</span></div>
            <div v-else class="search-results-end">{{ recommendationSort === 'latest' ? '按最近推荐时间排列' : '按推荐人数排列，同票时最近优先' }}</div>
          </template>
          <template v-else>
            <section v-if="searchMode === 'discover' && (hotSearches.length || searchResults.length)" class="discover-section">
              <div class="discover-heading">
                <span class="discover-title"><img class="provider-logo provider-inline-icon" :class="`is-${musicSource}`" :src="selectedProviderIcon" alt="" />{{ selectedProviderName }}热搜</span>
                <small>点击关键词直接搜索</small>
              </div>
              <div v-if="hotSearches.length" class="hot-search-grid">
                <button v-for="(item, index) in hotSearches" :key="item.keyword" class="hot-search-item" :class="{ 'is-top': index < 3 }" :title="item.content || `搜索 ${item.keyword}`" @click="runHotSearch(item.keyword)">
                  <span class="hot-search-rank">{{ String(index + 1).padStart(2, '0') }}</span>
                  <span class="hot-search-keyword">{{ item.keyword }}</span>
                </button>
              </div>
              <div class="discover-heading chart-heading">
                <span class="discover-title"><img class="provider-logo provider-inline-icon" :class="`is-${musicSource}`" :src="selectedProviderIcon" alt="" />{{ selectedProviderName }}热歌榜</span>
                <small>向下滚动继续浏览</small>
              </div>
            </section>
            <article v-for="song in searchResults" :key="`${searchMode}-${song.provider || musicSource}-${song.id}`" class="search-result" :class="{ 'is-unavailable': song.playable === false }">
              <button class="search-result-main" :disabled="song.playable === false" :title="song.playable === false ? song.restriction : `加入《${song.name}》`" @click="addSong(song)">
                <img :src="song.al?.picUrl || FALLBACK_COVER" alt="" :referrerpolicy="coverReferrerPolicy(song.provider || musicSource)" @error="coverFallback" />
                <span class="result-meta"><strong>{{ song.name }}</strong><span>{{ song.playable === false ? song.restriction : `${song.ar?.map((artist) => artist.name).join(' / ') || (musicSource === 'bilibili' ? '未知UP主' : '未知艺术家')} · ${song.al?.name || (musicSource === 'bilibili' ? 'Bilibili 视频' : '未知专辑')}` }}</span></span>
              </button>
              <span class="result-duration">{{ formatTime((song.dt || 0) / 1000) }}</span>
              <button class="recommend-control is-compact" :class="{ 'is-active': isRecommended(song) }" :disabled="song.playable === false || recommendationBusyKey === recommendationKey(song)" :title="isRecommended(song) ? '撤回我的推荐' : '推荐给大家'" @click="toggleRecommendation(song)"><LoaderCircle v-if="recommendationBusyKey === recommendationKey(song)" :size="15" class="continuous-spin" /><Megaphone v-else :size="15" /></button>
              <button
                class="result-add"
                :class="{ 'is-success': isSongInPlaylist(song) }"
                :disabled="song.playable === false || addingSongKey === searchTrackKey(song) || isSongInPlaylist(song)"
                :title="isSongInPlaylist(song) ? '已加入播放队列' : addingSongKey === searchTrackKey(song) ? '正在加入' : '加入播放队列'"
                @click="addSong(song)"
              >
                <LoaderCircle v-if="addingSongKey === searchTrackKey(song)" :size="17" class="continuous-spin" />
                <span v-else-if="isSongInPlaylist(song)" class="result-add-success"><Check :size="14" :stroke-width="2.8" /></span>
                <CirclePlus v-else :size="20" />
              </button>
            </article>
            <div v-if="discovering && !searchResults.length" class="search-placeholder"><LoaderCircle :size="26" class="continuous-spin" /><strong>正在加载{{ selectedProviderName }}热榜</strong><span>看看大家此刻都在听什么</span></div>
            <div v-else-if="!searchResults.length" class="search-placeholder">
              <Search v-if="musicSource === 'bilibili'" :size="28" /><Radio v-else-if="searchMode === 'discover'" :size="28" /><Search v-else :size="28" />
              <strong>{{ musicSource === 'bilibili' && searchMode === 'discover' ? '搜索或粘贴B站视频链接' : searchMode === 'discover' ? '热榜暂时没有响应' : musicSource === 'bilibili' ? '没有找到匹配的B站视频' : '没有找到匹配的歌曲' }}</strong>
              <span>{{ musicSource === 'bilibili' && searchMode === 'discover' ? '支持关键词、BV号、AV号、b23.tv和完整视频链接' : searchMode === 'discover' ? (discoveryError || '稍后再试，或直接搜索想听的歌') : musicSource === 'bilibili' ? '换一个关键词，或直接粘贴视频链接试试' : '换一个歌曲名、艺术家或专辑试试' }}</span>
              <button v-if="searchMode === 'discover' && musicSource !== 'bilibili'" class="discovery-retry" @click="loadDiscovery">重新加载</button>
            </div>
            <div v-else-if="searchHasMore" class="search-load-more"><LoaderCircle v-if="loadingMoreSearch" :size="16" class="continuous-spin" /><ChevronDown v-else :size="15" /><span>{{ loadingMoreSearch ? '正在加载更多' : '向下滚动加载更多' }}</span></div>
            <div v-else class="search-results-end">{{ searchMode === 'discover' ? '已显示全部热歌' : '已显示全部结果' }}</div>
          </template>
        </div>
        <div v-if="musicSource === 'netease'" class="playlist-import">
          <div><strong><img class="provider-logo provider-inline-icon is-netease" :src="providerIcon('netease')" alt="" />导入网易云歌单</strong><span>粘贴歌单链接或输入 ID</span></div>
          <div class="playlist-import-row"><input v-model="playlistInput" placeholder="music.163.com/playlist?id=..." /><button :disabled="searching || !playlistInput.trim()" @click="importPlaylist">导入</button></div>
        </div>
      </aside>
    </template>

    <div v-if="toast" class="toast-message" role="status">{{ toast }}</div>
  </main>
</template>
