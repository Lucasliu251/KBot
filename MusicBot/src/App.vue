<script setup lang="ts">
import {
  Check,
  ChevronDown,
  CirclePlus,
  Clock3,
  GripVertical,
  Headphones,
  ListMusic,
  LoaderCircle,
  Minus,
  Music2,
  Pause,
  Play,
  Plus,
  Radio,
  RefreshCw,
  Repeat1,
  Repeat2,
  RotateCcw,
  Search,
  Server,
  Shuffle,
  SkipBack,
  SkipForward,
  Trash2,
  Volume2,
  Wifi,
  WifiOff,
  X,
} from '@lucide/vue'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { assetUrl, getJson, postJson } from './api'

type PlayMode = 'order' | 'repeat-one' | 'shuffle'
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
}
type Guild = { id: string; name: string }
type Channel = { id: string; name: string }
type SearchTrack = {
  id: number | string
  name: string
  ar?: Array<{ name: string }>
  al?: { name?: string; picUrl?: string }
  dt?: number
}
type LyricLine = { time: number; text: string }

const FALLBACK_COVER = assetUrl('album-placeholder.png')
const DEMO_TRACKS: Track[] = [
  { id: 'demo-1', name: '凌晨来信', artist: '灰色电台', album: '城市失眠指南', cover: FALLBACK_COVER, duration: 238, position: 87, playing: true },
  { id: 'demo-2', name: '飞鸟经过的夜晚', artist: '匿名旅人', album: '风的回声', cover: FALLBACK_COVER, duration: 214, queue_index: 0 },
  { id: 'demo-3', name: '把黄昏留在窗边', artist: '南方邮局', album: '日落以后', cover: FALLBACK_COVER, duration: 253, queue_index: 1 },
  { id: 'demo-4', name: '温柔的噪音', artist: '低空飞行', album: '白昼梦', cover: FALLBACK_COVER, duration: 196, queue_index: 2 },
  { id: 'demo-5', name: '世界安静三秒', artist: '云层收音机', album: '无人的海岸线', cover: FALLBACK_COVER, duration: 226, queue_index: 3 },
]
const DEMO_LYRICS: LyricLine[] = [
  { time: 0, text: '路灯把影子写得很长' },
  { time: 12, text: '晚风穿过没有人的广场' },
  { time: 25, text: '收音机里传来一阵微光' },
  { time: 38, text: '像某封忘记寄出的信一样' },
  { time: 51, text: '我们曾沿着河岸慢慢走' },
  { time: 64, text: '把沉默留给身后的高楼' },
  { time: 77, text: '这一刻城市放轻了呼吸' },
  { time: 90, text: '我听见你在凌晨的回音' },
  { time: 103, text: '穿过雨落下来的缝隙' },
  { time: 116, text: '停在离我不远的屋顶' },
  { time: 129, text: '如果明天仍旧没有答案' },
  { time: 142, text: '就让今晚再走得慢一点' },
  { time: 155, text: '让旧唱片继续转一圈' },
  { time: 168, text: '让没说完的话留在耳边' },
  { time: 181, text: '天亮之前不必告别' },
  { time: 194, text: '我们只是路过这场长夜' },
  { time: 207, text: '等第一班列车驶过窗前' },
  { time: 220, text: '再把名字交还给明天' },
]
const MODE_META = {
  order: { label: '顺序播放', icon: Repeat2 },
  'repeat-one': { label: '单曲循环', icon: Repeat1 },
  shuffle: { label: '随机播放', icon: Shuffle },
} as const

const tracks = ref<Track[]>(DEMO_TRACKS.map((track) => ({ ...track })))
const lyrics = ref<LyricLine[]>(DEMO_LYRICS)
const lyricState = ref<'loading' | 'ready' | 'empty'>('ready')
const lyricsTrackId = ref('demo-1')
const position = ref(DEMO_TRACKS[0].position ?? 0)
const volume = ref(68)
const isPlaying = ref(true)
const playMode = ref<PlayMode>('order')
const lyricOffset = ref(0)
const syncOpen = ref(false)
const searchOpen = ref(false)
const channelSwitcherOpen = ref(false)
const searching = ref(false)
const loadingMoreSearch = ref(false)
const searchHasMore = ref(false)
const activeSearchKeyword = ref('')
const query = ref('')
const searchResults = ref<SearchTrack[]>([])
const playlistInput = ref('')
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
const demoMode = ref(true)
const refreshing = ref(false)
const toast = ref('')
const seeking = ref(false)
const dragIndex = ref<number | null>(null)
const dragTargetIndex = ref<number | null>(null)
const searchInput = ref<HTMLInputElement | null>(null)
const searchResultsBox = ref<HTMLElement | null>(null)
let pollTimer: number | undefined
let progressTimer: number | undefined
let toastTimer: number | undefined
let playlistRequestVersion = 0
let lyricRequestVersion = 0
let searchRequestVersion = 0
let lyricTargetId = 'demo-1'
let playbackAnchorPosition = position.value
let playbackAnchorTime = performance.now()
const lyricCache = new Map<string, LyricLine[]>()
let hasLoadedLivePlaylist = false

const current = computed(() => tracks.value.find((track) => track.playing))
const queuedTracks = computed(() => tracks.value.filter((track) => !track.playing))
const duration = computed(() => current.value?.duration || 0)
const progress = computed(() => duration.value > 0 ? Math.min(100, (position.value / duration.value) * 100) : 0)
const channelName = computed(() => channels.value.find((channel) => channel.id === channelId.value)?.name || resolvedChannelName.value || '选择语音频道')
const guildName = computed(() => guilds.value.find((guild) => guild.id === guildId.value)?.name || 'KOOK 服务器')
const modeIcon = computed(() => MODE_META[playMode.value].icon)
const rangeProgressStyle = computed(() => ({ '--range-progress': `${progress.value}%` }))
const volumeProgressStyle = computed(() => ({ '--range-progress': `${volume.value}%` }))

function formatTime(seconds = 0) {
  if (!Number.isFinite(seconds) || seconds < 0) return '00:00'
  return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`
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

function notify(message: string) {
  toast.value = message
  if (toastTimer) window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { toast.value = '' }, 2400)
}

function coverFallback(event: Event) {
  const image = event.currentTarget as HTMLImageElement
  if (!image.src.endsWith('/album-placeholder.png')) image.src = FALLBACK_COVER
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
    const data = await getJson<{ playlist: Track[] }>(`/api/playlist/current?guild_id=${encodeURIComponent(selectedGuild)}`)
    if (requestVersion !== playlistRequestVersion) return
    if (data.success === false) throw new Error(data.error)
    const playlist = (data.playlist ?? []).map((track) => ({ ...track, id: String(track.id), duration: Number(track.duration || 0) }))
    const previousTrackId = current.value?.id
    const incomingCurrent = playlist.find((track) => track.playing)
    tracks.value = playlist
    if (incomingCurrent) syncPlaybackPosition(Number(incomingCurrent.position || 0), previousTrackId !== incomingCurrent.id)
    demoMode.value = false
    hasLoadedLivePlaylist = true
  } catch {
    if (requestVersion !== playlistRequestVersion || hasLoadedLivePlaylist) return
    if (tracks.value.length === 0) tracks.value = DEMO_TRACKS.map((track) => ({ ...track }))
    demoMode.value = true
  }
}

async function loadPlayerState(selectedGuild: string) {
  try {
    const data = await getJson<{ connected: boolean; channel_id?: string; volume?: number; play_mode?: PlayMode; paused?: boolean }>(`/api/player/state?guild_id=${encodeURIComponent(selectedGuild)}`)
    connectedChannelId.value = data.channel_id || ''
    connected.value = Boolean(data.connected) && connectedChannelId.value === channelId.value
    isPlaying.value = !data.paused
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
}

function consoleBasePath() {
  const scriptRoot = String(window.APP_BASE || '').replace(/\/$/, '')
  return scriptRoot || '/Music'
}

function updateChannelRoute(id: string, replace = false) {
  const target = id ? `${consoleBasePath()}/${encodeURIComponent(id)}` : consoleBasePath()
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

async function handleChannelSelection(event: Event) {
  const id = (event.target as HTMLSelectElement).value
  const channel = channels.value.find((item) => item.id === id)
  if (channel) await chooseChannel(channel)
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
    demoMode.value = true
    setupError.value = error instanceof Error ? error.message : '后端服务暂时不可用'
    channelSwitcherOpen.value = true
  }
  window.addEventListener('popstate', handlePopState)
  pollTimer = window.setInterval(() => { if (guildId.value) void loadPlaylist() }, 2000)
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
  if (progressTimer) window.clearInterval(progressTimer)
  if (toastTimer) window.clearTimeout(toastTimer)
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
  if (!open) return
  await nextTick()
  window.setTimeout(() => searchInput.value?.focus(), 80)
})

watch(() => current.value?.id, async (id) => {
  if (!id || id === lyricTargetId) return
  lyricTargetId = id
  const requestVersion = ++lyricRequestVersion

  if (demoMode.value || id.startsWith('demo-')) {
    lyricsTrackId.value = id
    lyrics.value = DEMO_LYRICS
    lyricState.value = 'ready'
    return
  }

  lyricsTrackId.value = id
  const cachedLyrics = lyricCache.get(id)
  if (cachedLyrics) {
    lyrics.value = cachedLyrics
    lyricState.value = 'ready'
  } else {
    lyrics.value = []
    lyricState.value = 'loading'
  }

  const detailPromise = getJson<{ song?: { album?: string; cover?: string; duration?: number } }>(`/api/song/detail?id=${encodeURIComponent(id)}`)
  const lyricPromise = (async () => {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const response = await getJson<{ lyric?: string }>(`/api/song/lyrics?id=${encodeURIComponent(id)}`)
        const parsed = parseLyrics(response.lyric ?? '')
        if (parsed.length || attempt === 1) return parsed
      } catch {
        if (attempt === 1) return []
      }
      await new Promise((resolve) => window.setTimeout(resolve, 450))
    }
    return []
  })()

  const [detailResult, lyricResult] = await Promise.allSettled([detailPromise, lyricPromise])
  if (requestVersion !== lyricRequestVersion || lyricTargetId !== id) return

  if (detailResult.status === 'fulfilled') {
    const detail = detailResult.value
    if (detail.song) {
      tracks.value = tracks.value.map((track) => track.id === id
        ? { ...track, album: detail.song?.album || track.album, cover: detail.song?.cover || track.cover, duration: detail.song?.duration || track.duration }
        : track)
    }
  }

  const parsedLyrics = lyricResult.status === 'fulfilled' ? lyricResult.value : []
  if (parsedLyrics.length) {
    lyricCache.set(id, parsedLyrics)
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

async function togglePlayback() {
  const next = !isPlaying.value
  isPlaying.value = next
  if (demoMode.value || !guildId.value) return
  try {
    await postJson(next ? '/api/resume' : '/api/pause', { guild_id: guildId.value })
  } catch (error) {
    isPlaying.value = !next
    notify(error instanceof Error ? error.message : '播放状态切换失败')
  }
}

async function previousTrack() {
  if (demoMode.value) {
    const active = tracks.value.findIndex((track) => track.playing)
    const previous = active <= 0 ? tracks.value.length - 1 : active - 1
    tracks.value = tracks.value.map((track, index) => ({ ...track, playing: index === previous }))
    position.value = 0
    return
  }
  try {
    await postJson('/api/previous', { guild_id: guildId.value })
    await loadPlaylist()
  } catch (error) { notify(error instanceof Error ? error.message : '暂时无法返回上一首') }
}

async function nextTrack() {
  if (demoMode.value) {
    const active = tracks.value.findIndex((track) => track.playing)
    const next = active < 0 || active === tracks.value.length - 1 ? 0 : active + 1
    tracks.value = tracks.value.map((track, index) => ({ ...track, playing: index === next }))
    position.value = 0
    return
  }
  try {
    await postJson('/api/skip', { guild_id: guildId.value })
    await loadPlaylist()
  } catch (error) { notify(error instanceof Error ? error.message : '跳转失败') }
}

async function clearQueue() {
  if (!window.confirm('确认清空等待播放的歌曲？当前歌曲不会被中断。')) return
  tracks.value = tracks.value.filter((track) => track.playing)
  if (demoMode.value) return
  try {
    await postJson('/api/clear', { guild_id: guildId.value })
    notify('播放队列已清空')
  } catch (error) {
    notify(error instanceof Error ? error.message : '清空失败')
    await loadPlaylist()
  }
}

async function cyclePlayMode() {
  const modes: PlayMode[] = ['order', 'repeat-one', 'shuffle']
  const next = modes[(modes.indexOf(playMode.value) + 1) % modes.length]
  playMode.value = next
  notify(`已切换为${MODE_META[next].label}`)
  if (!demoMode.value && guildId.value) {
    try { await postJson('/api/play-mode', { guild_id: guildId.value, mode: next }) }
    catch (error) { notify(error instanceof Error ? error.message : '播放模式切换失败') }
  }
}

async function commitSeek() {
  seeking.value = false
  syncPlaybackPosition(position.value, true)
  if (demoMode.value || !guildId.value) return
  try { await postJson('/api/seek', { guild_id: guildId.value, position: Math.round(position.value) }) }
  catch (error) { notify(error instanceof Error ? error.message : '进度调整失败') }
}

async function commitVolume() {
  if (demoMode.value || !guildId.value) return
  try { await postJson('/api/volume', { guild_id: guildId.value, volume: volume.value / 100 }) }
  catch (error) { notify(error instanceof Error ? error.message : '音量调整失败') }
}

async function connectVoice() {
  if (!guildId.value || !channelId.value) {
    channelSwitcherOpen.value = true
    notify('请先选择语音频道')
    return
  }
  if (!connected.value && connectedChannelId.value && connectedChannelId.value !== channelId.value) {
    const confirmed = window.confirm('机器人正在另一个语音频道播放。切换连接会停止当前播放并清空队列，是否继续？')
    if (!confirmed) return
  }
  try {
    await postJson(connected.value ? '/api/leave' : '/api/join', connected.value
      ? { guild_id: guildId.value }
      : { guild_id: guildId.value, channel_id: channelId.value })
    connected.value = !connected.value
    connectedChannelId.value = connected.value ? channelId.value : ''
    notify(connected.value ? `已连接到 ${channelName.value}` : '已断开语音频道')
  } catch (error) { notify(error instanceof Error ? error.message : '语音频道操作失败') }
}

function getSearchPageSize() {
  const availableHeight = searchResultsBox.value?.clientHeight || 420
  return Math.max(4, Math.min(12, Math.ceil(availableHeight / 67)))
}

async function runSearch() {
  const keyword = query.value.trim()
  if (!keyword) return
  const requestVersion = ++searchRequestVersion
  activeSearchKeyword.value = keyword
  searchResults.value = []
  searchHasMore.value = false
  searching.value = true
  try {
    const limit = getSearchPageSize()
    const data = await getJson<{
      songs: SearchTrack[]
      pagination?: { has_more?: boolean }
    }>(`/api/search?keyword=${encodeURIComponent(keyword)}&limit=${limit}&offset=0`)
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
    if (requestVersion === searchRequestVersion) searching.value = false
  }
}

async function loadMoreSearchResults() {
  if (searching.value || loadingMoreSearch.value || !searchHasMore.value || !activeSearchKeyword.value) return
  const requestVersion = searchRequestVersion
  const offset = searchResults.value.length
  const limit = getSearchPageSize()
  loadingMoreSearch.value = true
  try {
    const data = await getJson<{
      songs: SearchTrack[]
      pagination?: { has_more?: boolean }
    }>(`/api/search?keyword=${encodeURIComponent(activeSearchKeyword.value)}&limit=${limit}&offset=${offset}`)
    if (requestVersion !== searchRequestVersion) return
    const knownIds = new Set(searchResults.value.map((song) => String(song.id)))
    const nextSongs = (data.songs ?? []).filter((song) => !knownIds.has(String(song.id)))
    searchResults.value = [...searchResults.value, ...nextSongs]
    searchHasMore.value = Boolean(data.pagination?.has_more)
  } catch (error) {
    if (requestVersion === searchRequestVersion) {
      notify(error instanceof Error ? error.message : '更多搜索结果加载失败')
    }
  } finally { loadingMoreSearch.value = false }
}

function handleSearchScroll(event: Event) {
  const target = event.currentTarget as HTMLElement
  const remaining = target.scrollHeight - target.scrollTop - target.clientHeight
  if (remaining < 90) void loadMoreSearchResults()
}

async function addSong(song: SearchTrack) {
  if (!guildId.value || !channelId.value) {
    notify('请先选择并连接语音频道')
    return
  }
  try {
    await postJson('/api/play', {
      guild_id: guildId.value,
      channel_id: channelId.value,
      song_id: String(song.id),
      song_name: song.name,
      artist_name: song.ar?.map((artist) => artist.name).join(' / ') || '未知艺术家',
      album_name: song.al?.name || '',
      cover_url: song.al?.picUrl || '',
    })
    notify(`《${song.name}》已加入队列`)
    await loadPlaylist()
  } catch (error) { notify(error instanceof Error ? error.message : '添加失败') }
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
  if (!demoMode.value && guildId.value) {
    try { await postJson('/api/queue/reorder', { guild_id: guildId.value, from_index: from, to_index: to }) }
    catch (error) {
      notify(error instanceof Error ? error.message : '排序保存失败')
      await loadPlaylist()
    }
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
        <button class="connection-state" :class="connected ? 'is-connected' : 'is-disconnected'" :title="connected ? '点击断开语音连接' : '点击连接所选语音频道'" @click="connectVoice">
          <Wifi v-if="connected" :size="17" /><WifiOff v-else :size="17" /><span>{{ connected ? '已连接' : channelId ? '待连接' : '未选择' }}</span>
        </button>
        <button class="icon-button" aria-label="搜索音乐" title="搜索音乐" @click="searchOpen = true"><Search :size="19" /></button>
        <button class="icon-button" aria-label="刷新页面状态" title="刷新页面状态" @click="refreshAll"><RefreshCw :size="19" :class="{ 'spin-once': refreshing }" /></button>
      </div>
    </header>

    <section class="console-grid">
      <section class="panel player-panel">
        <div class="cover-wrap">
          <img class="album-cover" :src="current?.cover || FALLBACK_COVER" :alt="current ? `${current.name} 专辑封面` : '默认专辑封面'" @error="coverFallback" />
          <div class="playing-stamp"><span class="playing-dot" />{{ isPlaying ? 'PLAYING' : 'PAUSED' }}</div>
        </div>
        <div class="track-meta">
          <h1>{{ current?.name || '等待播放' }}</h1>
          <h2>{{ current?.artist || '从右上角搜索并添加音乐' }}</h2>
          <p>{{ current?.album || '互联网垃圾桶音乐控制台' }}</p>
        </div>
        <div class="source-row">
          <span class="netease-dot"><Music2 :size="13" /></span><span class="source-name">NETEASE</span>
          <span v-if="demoMode" class="preview-label">界面预览</span>
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
            @pointerdown="seeking = true"
            @pointerup="seeking = false"
            @pointercancel="seeking = false"
            @change="commitSeek"
          />
          <div class="time-row"><span>{{ formatTime(position) }}</span><span>{{ formatTime(duration) }}</span></div>
        </div>
        <div class="slider-block volume-block">
          <Volume2 :size="17" />
          <input v-model.number="volume" class="range-input volume-range" type="range" min="0" max="100" :style="volumeProgressStyle" aria-label="音量" @pointerup="commitVolume" />
          <span class="volume-value">{{ volume }}%</span>
        </div>
        <div class="transport-controls">
          <button title="上一首" @click="previousTrack"><SkipBack :size="20" /><span>上一首</span></button>
          <button title="清空播放队列" @click="clearQueue"><Trash2 :size="19" /><span>清空</span></button>
          <button class="primary-control" :title="isPlaying ? '暂停' : '继续播放'" @click="togglePlayback">
            <Pause v-if="isPlaying" :size="20" /><Play v-else :size="20" fill="currentColor" /><span>{{ isPlaying ? '暂停' : '播放' }}</span>
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
        <div class="lyrics-stage" aria-live="polite">
          <div v-if="lyricState === 'loading'" class="lyric-status">
            <LoaderCircle :size="22" class="continuous-spin" />
            <span>正在同步歌词</span>
          </div>
          <div v-else-if="lyricState === 'empty'" class="lyric-status">
            <Music2 :size="24" />
            <span>这首歌暂时没有可用歌词</span>
          </div>
          <div v-else class="lyrics-list">
            <div
              v-for="item in lyricItems"
              :key="`${lyricsTrackId}-${item.index}-${item.line.time}`"
              class="lyric-line"
              :class="{ 'is-current': item.index === activeLyricIndex, 'is-hidden': item.distance > 8 }"
              :style="{ '--offset': String(item.offset), '--distance': String(item.distance) }"
            >
              {{ item.line.text }}
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
            <img :src="current.cover || FALLBACK_COVER" alt="" @error="coverFallback" />
            <div class="queue-track-meta"><strong>{{ current.name }}</strong><span>{{ current.artist }}</span></div><span class="queue-duration">{{ formatTime(current.duration) }}</span>
          </article>
          <article v-for="(track, index) in queuedTracks" :key="`${track.id}-${track.queue_index ?? index}`" class="queue-card" :class="{ 'is-dragging': dragIndex === index, 'is-drag-over': dragIndex !== null && dragTargetIndex === index && dragIndex !== index }" draggable="true" @dragstart="handleDragStart($event, index)" @dragend="cancelDrag" @dragenter.prevent="handleDragEnter(index)" @dragover.prevent @drop.prevent="dropQueue(index)" @pointerenter="handleDragEnter(index)">
            <GripVertical class="drag-handle" :size="17" aria-label="拖动调整顺序" @pointerdown="handlePointerDragStart($event, index)" /><span class="queue-number">{{ String(index + 1).padStart(2, '0') }}</span>
            <img :src="track.cover || FALLBACK_COVER" alt="" @error="coverFallback" />
            <div class="queue-track-meta"><strong>{{ track.name }}</strong><span>{{ track.artist }}</span></div><span class="queue-duration">{{ formatTime(track.duration) }}</span>
          </article>
          <div v-if="!current && !queuedTracks.length" class="empty-queue"><Music2 :size="30" /><strong>播放队列为空</strong><span>搜索一首歌，让声音填满这里</span></div>
        </div>
        <div class="queue-footer"><GripVertical :size="14" /><span>拖动歌曲卡片调整播放顺序</span></div>
      </section>
    </section>

    <template v-if="searchOpen">
      <button class="search-scrim" aria-label="关闭搜索" @click="searchOpen = false" />
      <aside class="search-drawer" aria-label="音乐搜索菜单">
        <div class="search-drawer-head">
          <div><span class="eyebrow">MUSIC LIBRARY</span><h2>搜索音乐</h2></div>
          <button class="icon-button" title="关闭" @click="searchOpen = false"><X :size="19" /></button>
        </div>
        <div class="search-box">
          <Search :size="19" /><input ref="searchInput" v-model="query" placeholder="歌曲、艺术家或专辑" @keydown.enter="runSearch" />
          <button :disabled="searching || !query.trim()" @click="runSearch"><LoaderCircle v-if="searching" :size="17" class="continuous-spin" /><template v-else>搜索</template></button>
        </div>
        <div class="connection-picker">
          <label><span>服务器</span><span class="select-wrap"><select :value="guildId" @change="handleGuildSelection"><option v-if="!guilds.length" value="">暂无可用服务器</option><option v-for="guild in guilds" :key="guild.id" :value="guild.id">{{ guild.name }}</option></select><ChevronDown :size="15" /></span></label>
          <label><span>语音频道</span><span class="select-wrap"><select :value="channelId" @change="handleChannelSelection"><option v-if="!channels.length" value="">暂无可用频道</option><option v-for="channel in channels" :key="channel.id" :value="channel.id">{{ channel.name }}</option></select><ChevronDown :size="15" /></span></label>
          <button :class="connected ? 'disconnect-button' : 'connect-button'" @click="connectVoice">{{ connected ? '断开' : '连接' }}</button>
        </div>
        <div ref="searchResultsBox" class="search-results" @scroll.passive="handleSearchScroll">
          <button v-for="song in searchResults" :key="song.id" class="search-result" @click="addSong(song)">
            <img :src="song.al?.picUrl || FALLBACK_COVER" alt="" @error="coverFallback" />
            <span class="result-meta"><strong>{{ song.name }}</strong><span>{{ song.ar?.map((artist) => artist.name).join(' / ') || '未知艺术家' }} · {{ song.al?.name || '未知专辑' }}</span></span>
            <span class="result-duration">{{ formatTime((song.dt || 0) / 1000) }}</span><CirclePlus :size="20" />
          </button>
          <div v-if="!searchResults.length" class="search-placeholder"><Search :size="28" /><strong>寻找下一首音乐</strong><span>支持网易云歌曲名称、艺术家和专辑搜索</span></div>
          <div v-else-if="searchHasMore" class="search-load-more">
            <LoaderCircle v-if="loadingMoreSearch" :size="16" class="continuous-spin" />
            <ChevronDown v-else :size="15" />
            <span>{{ loadingMoreSearch ? '正在加载更多' : '向下滚动加载更多' }}</span>
          </div>
          <div v-else class="search-results-end">已显示全部结果</div>
        </div>
        <div class="playlist-import">
          <div><strong>导入网易云歌单</strong><span>粘贴歌单链接或输入 ID</span></div>
          <div class="playlist-import-row"><input v-model="playlistInput" placeholder="music.163.com/playlist?id=..." /><button :disabled="searching || !playlistInput.trim()" @click="importPlaylist">导入</button></div>
        </div>
      </aside>
    </template>

    <div v-if="toast" class="toast-message" role="status">{{ toast }}</div>
  </main>
</template>
